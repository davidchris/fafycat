"""Browser-facing security: Host allowlist, cross-origin write block, script-block escaping.

These tests drive the real app through ``TestClient``. The suite-wide conftest allows the
TestClient host ``testserver`` through ``FAFYCAT_ALLOWED_HOSTS``; the checks themselves stay on.
"""

import asyncio
import json
import logging
import re
import sys
from datetime import UTC, date, datetime

import pytest
import uvicorn
from fafycat import cli
from fafycat.app import create_app
from fafycat.api.ml import reset_singletons
from fafycat.core.database import CategoryORM, TransactionORM
from fafycat.core.models import ReviewPriority
from fafycat.core.security import DEFAULT_ALLOWED_HOSTS, BrowserSecurityMiddleware
from fastapi.testclient import TestClient

EVIL_ORIGIN = "https://evil.example"


def _seed_pending_prediction(session) -> None:
    cat = CategoryORM(name="groceries", type="spending", budget=0.0)
    session.add(cat)
    session.flush()
    session.add(
        TransactionORM(
            id="a" * 16,
            date=date(2025, 6, 15),
            name="REWE",
            purpose="",
            amount=-42.5,
            currency="EUR",
            predicted_category_id=cat.id,
            confidence_score=0.99,
            is_reviewed=False,
            review_priority=ReviewPriority.QUALITY_CHECK,
            import_batch="test",
            imported_at=datetime.now(UTC),
        )
    )
    session.commit()


class TestCrossOriginWrites:
    """S1: a page on another origin must not be able to change data."""

    def test_cross_origin_bulk_approve_is_rejected_and_changes_nothing(self, test_client, db_session):
        _seed_pending_prediction(db_session)

        resp = test_client.post("/api/transactions/bulk-approve", headers={"Origin": EVIL_ORIGIN})

        assert resp.status_code == 403
        db_session.expire_all()
        assert db_session.query(TransactionORM).one().is_reviewed is False

    def test_same_origin_bulk_approve_succeeds(self, test_client, db_session):
        _seed_pending_prediction(db_session)

        resp = test_client.post("/api/transactions/bulk-approve", headers={"Origin": "http://testserver"})

        assert resp.status_code == 200
        assert resp.json()["approved"] == 1

    @pytest.mark.parametrize(
        "headers",
        [
            {"Referer": f"{EVIL_ORIGIN}/attack.html"},  # no Origin: fall back to Referer
            {"Origin": "null"},  # sandboxed iframe, data: URL, or no-referrer policy
            {"Origin": "http://testserver:3000"},  # another local app on a different port
            {"Origin": "https://testserver:80"},  # same host and port, other scheme
            {"Origin": "http://testserver."},  # trailing-dot host: a different origin
        ],
        ids=["evil-referer", "null-origin", "other-port", "other-scheme", "trailing-dot"],
    )
    def test_other_cross_origin_signals_are_rejected(self, test_client, headers):
        resp = test_client.post("/api/transactions/bulk-approve", headers=headers)
        assert resp.status_code == 403

    def test_same_origin_referer_without_origin_is_allowed(self, test_client):
        resp = test_client.post("/api/transactions/bulk-approve", headers={"Referer": "http://testserver/review"})
        assert resp.status_code == 200

    def test_cross_origin_get_is_not_blocked(self, test_client):
        """Reads are protected by the Host check and the browser's same-origin policy, not by Origin."""
        resp = test_client.get("/api/transactions", headers={"Origin": EVIL_ORIGIN})
        assert resp.status_code == 200


class TestHostAllowlist:
    """S2: DNS rebinding sends the attacker's host name; such requests must not reach the app."""

    @pytest.fixture
    def make_client(self, tmp_data_dir, monkeypatch):  # noqa: ARG002 - fixture isolates the data dir
        def _make(allowed_hosts: str | None = None) -> TestClient:
            if allowed_hosts is None:
                monkeypatch.delenv("FAFYCAT_ALLOWED_HOSTS", raising=False)
            else:
                monkeypatch.setenv("FAFYCAT_ALLOWED_HOSTS", allowed_hosts)
            reset_singletons()
            return TestClient(create_app())

        return _make

    def test_rebound_host_cannot_read_export(self, make_client):
        resp = make_client().get("/api/export/transactions", headers={"Host": "evil.example"})
        assert resp.status_code == 400

    @pytest.mark.parametrize("host", ["localhost:8000", "127.0.0.1:8001", "LOCALHOST"])
    def test_loopback_hosts_are_allowed_by_default(self, make_client, host):
        resp = make_client().get("/api/transactions", headers={"Host": host})
        assert resp.status_code == 200

    def test_testserver_is_not_allowed_by_default(self, make_client):
        resp = make_client().get("/api/transactions")
        assert resp.status_code == 400

    def test_env_var_extends_allowlist(self, make_client):
        client = make_client("fafycat.lan, 192.168.1.20")
        assert client.get("/api/transactions", headers={"Host": "fafycat.lan:8000"}).status_code == 200
        assert client.get("/api/transactions", headers={"Host": "192.168.1.20:8000"}).status_code == 200
        assert client.get("/api/transactions", headers={"Host": "evil.example"}).status_code == 400

    def test_ipv6_loopback_with_port_is_allowed(self):
        """TestClient cannot send an IPv6 Host header, so drive the middleware over raw ASGI."""

        async def ok_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        def status_for(host: bytes) -> int:
            sent: list[dict] = []

            async def receive():
                return {"type": "http.request", "body": b""}

            async def send(message):
                sent.append(message)

            scope = {"type": "http", "method": "GET", "scheme": "http", "path": "/", "headers": [(b"host", host)]}
            asyncio.run(BrowserSecurityMiddleware(ok_app, DEFAULT_ALLOWED_HOSTS)(scope, receive, send))
            return sent[0]["status"]

        assert status_for(b"[::1]:8000") == 204
        assert status_for(b"[::2]:8000") == 400

    def test_malformed_host_is_rejected(self, make_client):
        resp = make_client().get("/api/transactions", headers={"Host": "localhost:notaport"})
        assert resp.status_code == 400


class TestScriptBlockEscaping:
    """S3/B20: a category name must not be able to close the inline <script> block."""

    PAYLOAD = "</script><img src=x onerror=alert(1)>"

    def test_budget_variance_fragment_escapes_category_name_in_script(self, test_client, db_session):
        cat = CategoryORM(name=self.PAYLOAD, type="spending", budget=100.0)
        db_session.add(cat)
        db_session.flush()
        db_session.add(
            TransactionORM(
                id="b" * 16,
                date=date(2025, 3, 3),
                name="Shop",
                purpose="",
                amount=-20.0,
                currency="EUR",
                category_id=cat.id,
                is_reviewed=True,
                import_batch="test",
                imported_at=datetime.now(UTC),
            )
        )
        db_session.commit()

        resp = test_client.get(
            "/api/analytics/budget-variance-html", params={"start_date": "2025-01-01", "end_date": "2025-12-31"}
        )

        assert resp.status_code == 200
        body = resp.text
        assert "<img" not in body
        assert body.lower().count("</script") == 1
        # The chart still receives the real name once the browser parses the JSON.
        script = re.search(r"updateBudgetVarianceChart\((.*)\);\s*</script>", body, re.S)
        assert script is not None
        data = json.loads(script.group(1))
        assert data["variances"][0]["category_name"] == self.PAYLOAD


class TestServeBind:
    """S4: exposing the server beyond loopback is explicit, warned about, and still Host-checked."""

    def test_serve_with_lan_host_warns_and_allows_that_host(self, tmp_data_dir, monkeypatch, capsys):
        captured: dict = {}
        monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: captured.update(kwargs))
        monkeypatch.delenv("FAFYCAT_ALLOWED_HOSTS", raising=False)
        monkeypatch.setattr(
            sys, "argv", ["fafycat", "serve", "--host", "192.168.1.20", "--data-dir", str(tmp_data_dir)]
        )

        cli.main()

        assert captured["host"] == "192.168.1.20"
        assert "NO authentication" in capsys.readouterr().err
        reset_singletons()
        client = TestClient(create_app())
        assert client.get("/api/transactions", headers={"Host": "192.168.1.20:8000"}).status_code == 200
        assert client.get("/api/transactions", headers={"Host": "evil.example"}).status_code == 400

    def test_serve_on_other_loopback_address_allows_it_without_warning(self, tmp_data_dir, monkeypatch, capsys):
        monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: None)
        monkeypatch.delenv("FAFYCAT_ALLOWED_HOSTS", raising=False)
        monkeypatch.setattr(sys, "argv", ["fafycat", "serve", "--host", "127.0.0.2", "--data-dir", str(tmp_data_dir)])

        cli.main()

        assert "WARNING" not in capsys.readouterr().err
        reset_singletons()
        client = TestClient(create_app())
        assert client.get("/api/transactions/", headers={"Host": "127.0.0.2:8000"}).status_code == 200


def test_slow_request_log_level_depends_on_endpoint(test_client, monkeypatch, caplog):
    """P10: slow requests warn through the module logger, except endpoints that are slow by design."""
    import fafycat.app

    monkeypatch.setattr(fafycat.app, "_SLOW_REQUEST_SECONDS", -1.0)  # every request counts as slow
    caplog.set_level(logging.INFO, logger="fafycat.app")

    test_client.get("/api/transactions/")
    test_client.post("/api/upload/csv", files={"file": ("x.txt", b"", "text/plain")})

    levels = {r.getMessage().split(" took ")[0]: r.levelno for r in caplog.records if r.name == "fafycat.app"}
    assert levels == {
        "Slow request: GET /api/transactions/": logging.WARNING,
        "Slow request: POST /api/upload/csv": logging.INFO,
    }

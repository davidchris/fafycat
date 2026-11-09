"""One database location for every entry point, read-only query commands, and ``fafycat status``.

These tests run the real CLI against temporary data directories. They never set
``FAFYCAT_DB_URL``: the point is to check the location each command derives on
its own.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fafycat import cli
from fafycat.core.config import AppConfig
from fafycat.core.database import DatabaseManager, TransactionORM

SAMPLE_CSV = (
    "date,name,purpose,amount,currency\n"
    "2025-01-02,REWE Markt,Groceries,-42.10,EUR\n"
    "2025-01-03,Stadtwerke,Power bill,-80.00,EUR\n"
)


@pytest.fixture
def hermetic_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Environment without FAFYCAT_* overrides and without the user's real config file."""
    monkeypatch.setenv("FAFYCAT_CONFIG", str(tmp_path / "no-config.toml"))
    monkeypatch.chdir(tmp_path)
    return {**os.environ}


@pytest.fixture
def run_cli(tmp_path: Path, hermetic_env: dict[str, str]) -> Callable[..., subprocess.CompletedProcess[str]]:
    """Run ``python -m fafycat`` in a subprocess from a scratch working directory."""

    def _run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "fafycat", *args],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(tmp_path),
            env=hermetic_env,
        )

    return _run


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_db(db_path: Path) -> None:
    """Create a current-schema database with categories and transactions in a known state."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    config = AppConfig(data_dir=db_path.parent)
    config.database.url = f"sqlite:///{db_path}"
    manager = DatabaseManager(config)
    manager.create_tables()
    with manager.engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO categories (id, name, type, budget, is_active, created_at, updated_at) VALUES "
            "(1, 'groceries', 'spending', 0, 1, '2025-01-01', '2025-01-01'), "
            "(2, 'salary', 'income', 0, 1, '2025-01-01', '2025-01-01')"
        )
        rows = [
            # id, category_id, is_reviewed
            ("t1", 1, 1),
            ("t2", 2, 1),
            ("t3", None, 0),
        ]
        for txn_id, category_id, is_reviewed in rows:
            conn.exec_driver_sql(
                "INSERT INTO transactions (id, date, value_date, name, purpose, amount, currency, import_batch, "
                "imported_at, category_id, is_reviewed) "
                "VALUES (?, '2025-01-05', '2025-01-05', 'REWE', '', -10.0, 'EUR', 'b', '2025-01-06 10:00:00', ?, ?)",
                (txn_id, category_id, is_reviewed),
            )
    manager.engine.dispose()


# ---------------------------------------------------------------------------
# B1 / G1 / G14: serve and the CLI open the same file
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("dev", [False, True], ids=["prod", "dev"])
def test_serve_opens_the_database_that_cli_import_and_queries_use(
    dev: bool, tmp_path: Path, run_cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``fafycat import`` writes the file that ``fafycat serve`` then shows; ``tx list`` reads it too."""
    data_dir = tmp_path / "data"
    flags = ["--data-dir", str(data_dir), *(["--dev"] if dev else [])]
    csv = tmp_path / "bank.csv"
    csv.write_text(SAMPLE_CSV)

    imported = run_cli(*flags, "import", str(csv))
    assert imported.returncode == 0, imported.stdout + imported.stderr
    assert json.loads(imported.stdout)["transactions_imported"] == 2

    listed = run_cli(*flags, "tx", "list")
    assert listed.returncode == 0, listed.stdout + listed.stderr
    assert json.loads(listed.stdout)["total_count"] == 2

    built: dict[str, Any] = {}

    def fake_uvicorn_run(target: str, **_kwargs: Any) -> None:
        from fafycat.app import create_app

        built["app"] = create_app()

    monkeypatch.setattr(uvicorn, "run", fake_uvicorn_run)
    monkeypatch.setattr(sys, "argv", ["fafycat", "serve", *flags])
    cli.main()

    app = built["app"]
    expected_db = data_dir / ("fafycat_dev.db" if dev else "fafycat_prod.db")
    assert app.state.config.database.url == f"sqlite:///{expected_db}"
    with app.state.db_manager.get_session() as session:
        assert session.query(TransactionORM).count() == 2
    app.state.db_manager.engine.dispose()


@pytest.mark.parametrize("dev", [False, True], ids=["prod", "dev"])
def test_resolve_config_matches_the_file_serve_has_always_used(
    dev: bool, tmp_path: Path, hermetic_env: dict[str, str]
) -> None:
    """Prod stays ``<data_dir>/fafycat_prod.db`` so existing installs keep their data."""
    from fafycat.core.config import resolve_config

    config = resolve_config(tmp_path / "d", dev=dev)

    expected = (tmp_path / "d" / ("fafycat_dev.db" if dev else "fafycat_prod.db")).resolve()
    assert config.database.url == f"sqlite:///{expected}"
    assert config.ml.model_dir == (tmp_path / "d" / "models").resolve()


def test_precedence_is_flag_then_env_then_config_file(tmp_path: Path, hermetic_env, monkeypatch) -> None:
    """``--data-dir``/``--dev`` beat ``FAFYCAT_DB_URL``, which beats ``[paths] db_url`` in the config file."""
    from fafycat.core.config import resolve_config

    file_dir = tmp_path / "from-file"
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        f'[paths]\ndata_dir = "{file_dir}"\ndb_url = "sqlite:///{tmp_path}/file.db"\nmodel_dir = "{tmp_path}/fm"\n'
    )
    monkeypatch.setenv("FAFYCAT_CONFIG", str(config_file))

    from_file = resolve_config()
    assert (from_file.database.url, from_file.database.source) == (
        f"sqlite:///{tmp_path}/file.db",
        "config file db_url",
    )
    assert from_file.data_dir == file_dir

    monkeypatch.setenv("FAFYCAT_DB_URL", f"sqlite:///{tmp_path}/env.db")
    monkeypatch.setenv("FAFYCAT_MODEL_DIR", str(tmp_path / "env-models"))
    from_env = resolve_config()
    assert (from_env.database.url, from_env.database.source) == (f"sqlite:///{tmp_path}/env.db", "FAFYCAT_DB_URL")

    flag_dir = (tmp_path / "flag").resolve()
    from_flag = resolve_config(tmp_path / "flag")
    assert from_flag.database.url == f"sqlite:///{flag_dir / 'fafycat_prod.db'}"
    assert from_flag.database.source == "--data-dir/--dev flag"
    assert from_flag.ml.model_dir == flag_dir / "models"
    assert from_flag.export_dir == flag_dir / "exports"

    dev_only = resolve_config(dev=True)
    assert dev_only.database.url == f"sqlite:///{file_dir / 'fafycat_dev.db'}"


def test_status_with_data_dir_ignores_config_file_db_url(tmp_path: Path, hermetic_env: dict[str, str]) -> None:
    """A config file naming the real database must not leak into a ``--data-dir`` run."""
    elsewhere = tmp_path / "real" / "fafycat_prod.db"
    _make_db(elsewhere)
    config_file = tmp_path / "config.toml"
    config_file.write_text(f'[paths]\ndb_url = "sqlite:///{elsewhere}"\n')
    data_dir = tmp_path / "scratch"
    _make_db(data_dir / "fafycat_prod.db")
    before = _sha256(elsewhere)

    result = subprocess.run(
        [sys.executable, "-m", "fafycat", "status", "--data-dir", str(data_dir)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(tmp_path),
        env={**hermetic_env, "FAFYCAT_CONFIG": str(config_file)},
    )

    assert result.returncode == 0, result.stdout + result.stderr
    database = json.loads(result.stdout)["database"]
    assert database["path"] == str(data_dir.resolve() / "fafycat_prod.db")
    assert database["source"] == "--data-dir/--dev flag"
    assert _sha256(elsewhere) == before


def test_bare_app_config_defaults_to_the_prod_database(tmp_path: Path, hermetic_env, monkeypatch) -> None:
    """Server modules build ``AppConfig()`` themselves; its default must be the prod file, not ``fafycat.db``."""
    monkeypatch.setenv("FAFYCAT_DATA_DIR", str(tmp_path / "d"))

    assert AppConfig().database.url == f"sqlite:///{tmp_path / 'd' / 'fafycat_prod.db'}"


def test_legacy_cwd_database_is_used_by_every_command_when_nothing_is_configured(
    tmp_path: Path, hermetic_env, monkeypatch
) -> None:
    """The old ``./data/fafycat_prod.db`` fallback applies to all commands alike, or to none."""
    from fafycat.core.config import resolve_config

    legacy = tmp_path / "data" / "fafycat_prod.db"
    _make_db(legacy)
    monkeypatch.setattr("fafycat.core.config.user_data_dir", lambda _app: str(tmp_path / "platform"))

    assert resolve_config().database.url == f"sqlite:///{legacy.resolve()}"
    assert resolve_config(dev=True).database.url == f"sqlite:///{(tmp_path / 'platform' / 'fafycat_dev.db')}"
    assert resolve_config(tmp_path / "explicit").database.url == (
        f"sqlite:///{(tmp_path / 'explicit' / 'fafycat_prod.db').resolve()}"
    )
    monkeypatch.setenv("FAFYCAT_DATA_DIR", str(tmp_path / "env"))
    assert resolve_config().database.url == f"sqlite:///{tmp_path / 'env' / 'fafycat_prod.db'}"


def test_legacy_cwd_database_in_use_is_reported_with_the_unused_platform_database(
    tmp_path: Path, hermetic_env, monkeypatch
) -> None:
    from fafycat.cli_query.status import location_warnings
    from fafycat.core.config import resolve_config

    legacy = tmp_path / "data" / "fafycat_prod.db"
    _make_db(legacy)
    platform_db = tmp_path / "platform" / "fafycat_prod.db"
    _make_db(platform_db)
    monkeypatch.setattr("fafycat.core.config.user_data_dir", lambda _app: str(tmp_path / "platform"))

    warnings = location_warnings(resolve_config())

    assert len(warnings) == 2
    assert warnings[0].startswith(f"Using the legacy database {legacy.resolve()}")
    assert f"3 transactions exists at {platform_db.resolve()}" in warnings[1]

    monkeypatch.setenv("FAFYCAT_DB_URL", f"sqlite:///{legacy.resolve()}")
    explicit = location_warnings(resolve_config())
    assert [w for w in explicit if w.startswith("Using the legacy")] == []


# ---------------------------------------------------------------------------
# G3: query commands never change the database
# ---------------------------------------------------------------------------

QUERY_COMMANDS = [
    ("tx", "list"),
    ("cat", "list"),
    ("budget", "show", "2025"),
    ("analytics", "monthly", "--year", "2025"),
    ("analytics", "breakdown", "--year", "2025"),
    ("analytics", "variance", "--year", "2025"),
    ("analytics", "savings", "--year", "2025"),
    ("analytics", "yoy"),
    ("analytics", "top", "--year", "2025", "--month", "1"),
    ("status",),
]


@pytest.mark.integration
@pytest.mark.parametrize("command", QUERY_COMMANDS, ids=lambda c: " ".join(c[:2]))
def test_query_command_leaves_the_database_file_byte_identical(command: tuple[str, ...], tmp_path: Path, run_cli):
    """A row that ``create_tables`` would repair and an index it would rebuild stay as they are."""
    data_dir = tmp_path / "d"
    db_path = data_dir / "fafycat_prod.db"
    _make_db(db_path)
    with sqlite3.connect(db_path) as conn:
        # Reviewed without a category: the startup repair would reset this row.
        conn.execute("UPDATE transactions SET is_reviewed = 1 WHERE id = 't3'")
        conn.execute("DROP INDEX idx_review_events_transaction")
    conn.close()
    before = _sha256(db_path)

    result = run_cli("--data-dir", str(data_dir), *command)

    assert result.returncode == 0, result.stdout + result.stderr
    assert _sha256(db_path) == before


@pytest.mark.parametrize("command", [("tx", "list"), ("cat", "list"), ("analytics", "monthly")])
def test_query_command_on_missing_database_fails_without_creating_it(
    command: tuple[str, ...], tmp_path: Path, run_cli
) -> None:
    data_dir = tmp_path / "empty"

    result = run_cli("--data-dir", str(data_dir), *command)

    assert result.returncode == 1, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert str(data_dir.resolve() / "fafycat_prod.db") in error
    assert "fafycat init" in error
    assert not data_dir.exists()


def test_query_command_on_outdated_schema_fails_and_does_not_upgrade(tmp_path: Path, run_cli) -> None:
    data_dir = tmp_path / "d"
    db_path = data_dir / "fafycat_prod.db"
    _make_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP INDEX ix_transactions_merchant_pattern")
        conn.execute("ALTER TABLE transactions DROP COLUMN merchant_pattern")
    conn.close()
    before = _sha256(db_path)

    result = run_cli("--data-dir", str(data_dir), "tx", "list")

    assert result.returncode == 1, result.stdout + result.stderr
    error = json.loads(result.stdout)["error"]
    assert "transactions.merchant_pattern" in error
    assert _sha256(db_path) == before


# ---------------------------------------------------------------------------
# G7: fafycat status and --version
# ---------------------------------------------------------------------------


def test_status_reports_paths_counts_model_and_stray_databases(tmp_path: Path, run_cli) -> None:
    data_dir = tmp_path / "d"
    _make_db(data_dir / "fafycat_prod.db")
    # A database the pre-0.4 CLI wrote to; serve never opened it.
    _make_db(data_dir / "fafycat.db")
    (data_dir / "models").mkdir()
    (data_dir / "models" / "ensemble_categorizer.pkl").write_bytes(b"not a pickle")

    result = run_cli("--data-dir", str(data_dir), "status")

    assert result.returncode == 0, result.stdout + result.stderr
    status = json.loads(result.stdout)
    resolved = data_dir.resolve()
    assert status["version"] == importlib.metadata.version("fafycat")
    assert status["mode"] == "production"
    assert status["data_dir"] == str(resolved)
    assert status["database"] == {
        "url": f"sqlite:///{resolved / 'fafycat_prod.db'}",
        "source": "--data-dir/--dev flag",
        "path": str(resolved / "fafycat_prod.db"),
        "exists": True,
        "schema_problems": [],
        "transactions": 3,
        "reviewed": 2,
        "unreviewed": 1,
        "categories": 2,
    }
    model = status["model"]
    assert model["path"] == str(resolved / "models" / "ensemble_categorizer.pkl")
    assert model["exists"] is True
    assert model["loads"] is False
    assert model["error"]
    assert len(status["warnings"]) == 1
    assert str(resolved / "fafycat.db") in status["warnings"][0]
    assert "3 transactions" in status["warnings"][0]


def test_status_on_missing_database_reports_it_and_exits_zero(tmp_path: Path, run_cli) -> None:
    data_dir = tmp_path / "nothing"

    result = run_cli("--data-dir", str(data_dir), "--dev", "status")

    assert result.returncode == 0, result.stdout + result.stderr
    status = json.loads(result.stdout)
    assert status["mode"] == "development"
    assert status["database"]["path"] == str(data_dir.resolve() / "fafycat_dev.db")
    assert status["database"]["exists"] is False
    assert status["database"]["transactions"] is None
    assert status["model"] == {
        "path": str(data_dir.resolve() / "models" / "ensemble_categorizer.pkl"),
        "exists": False,
        "loads": False,
        "error": None,
    }
    assert not data_dir.exists()


def test_version_flag_and_package_version_come_from_the_installed_metadata(run_cli) -> None:
    import fafycat

    expected = importlib.metadata.version("fafycat")
    result = run_cli("--version")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"fafycat {expected}"
    assert fafycat.__version__ == expected


def test_app_reports_package_version(app_factory) -> None:
    app = app_factory()
    assert app.version == importlib.metadata.version("fafycat")
    app.state.db_manager.engine.dispose()

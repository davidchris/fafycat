"""Browser-facing protections for a local server that has no authentication.

FafyCat binds to loopback and trusts whoever can reach it. A web browser on the same machine can
reach it too, on behalf of any page the user has open. This module closes the two holes that
opens:

* DNS rebinding: a hostile page rebinds its own host name to ``127.0.0.1`` and becomes
  same-origin with FafyCat. The browser then sends ``Host: <attacker name>``. A Host allowlist
  rejects such requests with 400.
* Cross-site request forgery: any page can POST a form or a "simple" ``fetch`` to
  ``http://localhost:8000`` without a CORS preflight. Every state-changing request must therefore
  come from FafyCat's own origin, judged by the ``Origin`` header (or ``Referer`` when ``Origin`` is
  missing). Cross-origin writes are rejected with 403.

It also holds :func:`script_json`, the one way to embed data in an inline ``<script>`` block.
"""

import ipaddress
import json
import os
import sys
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

ALLOWED_HOSTS_ENV = "FAFYCAT_ALLOWED_HOSTS"
"""Comma-separated extra host names or IP addresses the server answers to (any port)."""

DEFAULT_ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
_DEFAULT_PORTS = {"http": 80, "https": 443}
_WILDCARD_BIND_HOSTS = frozenset({"", "0.0.0.0", "::"})


def _normalize_host(host: str) -> str:
    """Lower-case a host name or IP and drop IPv6 brackets and a trailing dot."""
    return host.strip().strip("[]").rstrip(".").lower()


def allowed_hosts_from_env() -> frozenset[str]:
    """Return the default loopback hosts plus those listed in ``FAFYCAT_ALLOWED_HOSTS``."""
    extra = os.environ.get(ALLOWED_HOSTS_ENV, "")
    return DEFAULT_ALLOWED_HOSTS | {_normalize_host(h) for h in extra.split(",") if h.strip()}


def _is_loopback(host: str) -> bool:
    host = _normalize_host(host)
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def prepare_bind_host(host: str) -> None:
    """Allow the ``serve --host`` address and warn when it leaves the machine.

    The address is added to ``FAFYCAT_ALLOWED_HOSTS`` in the environment, so the app factory sees
    it in the uvicorn worker (and in the reloader's child process).

    Args:
        host: The address uvicorn will bind to.
    """
    if _is_loopback(host):
        return
    if _normalize_host(host) not in _WILDCARD_BIND_HOSTS:
        current = os.environ.get(ALLOWED_HOSTS_ENV, "")
        os.environ[ALLOWED_HOSTS_ENV] = f"{current},{host}" if current else host
    sys.stderr.write(
        f"⚠️  WARNING: binding to {host}. FafyCat has NO authentication: anyone who can reach this "
        "address can read and change all your financial data.\n"
        f"   Only requests whose Host header is localhost, 127.0.0.1, ::1, the --host address, or listed in "
        f"{ALLOWED_HOSTS_ENV} are served.\n"
    )


def _split_netloc(netloc: str, scheme: str) -> tuple[str, int] | None:
    """Return ``(host, port)`` for a ``host[:port]`` string, or None if it is malformed."""
    try:
        parts = urlsplit(f"//{netloc}")
        host, port = parts.hostname, parts.port
    except ValueError:
        return None
    if not host:
        return None
    return _normalize_host(host), port or _DEFAULT_PORTS.get(scheme, 80)


def _origin_of(url: str) -> tuple[str, int] | None:
    """Return ``(host, port)`` of an Origin or Referer value, or None for ``null`` or garbage."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in _DEFAULT_PORTS:
        return None
    return _split_netloc(parts.netloc, parts.scheme)


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope["headers"]:
        if key == name:
            return value.decode("latin-1")
    return None


class BrowserSecurityMiddleware:
    """Reject requests for foreign Host names (400) and cross-origin writes (403)."""

    def __init__(self, app: ASGIApp, allowed_hosts: Iterable[str]) -> None:
        """Wrap ``app``.

        Args:
            app: The ASGI app to protect.
            allowed_hosts: Host names or IPs (no port) the server answers to.
        """
        self.app = app
        self.allowed_hosts = frozenset(_normalize_host(h) for h in allowed_hosts)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Check one request, then pass it on or answer with an error."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        error = self._check(scope)
        if error is None:
            await self.app(scope, receive, send)
            return
        status, detail = error
        await JSONResponse({"detail": detail}, status_code=status)(scope, receive, send)

    def _check(self, scope: Scope) -> tuple[int, str] | None:
        scheme = scope.get("scheme", "http")
        host = _split_netloc(_header(scope, b"host") or "", scheme)
        if host is None or host[0] not in self.allowed_hosts:
            return 400, f"Invalid Host header. Add the host name to {ALLOWED_HOSTS_ENV} to allow it."

        if scope["method"] in _SAFE_METHODS:
            return None

        # Browsers send Origin on every cross-origin POST/PUT/PATCH/DELETE, from forms and fetch
        # alike, and "null" when they hide it. Referer is a fallback for old clients. A request
        # with neither did not come from a web page (curl, the CLI, scripts, TestClient). Those
        # callers can reach the socket anyway, so blocking them would protect nothing.
        source = _header(scope, b"origin") or _header(scope, b"referer")
        if source is None:
            return None
        if _origin_of(source) != host:
            return 403, "Cross-origin request rejected."
        return None


def script_json(data: Any) -> str:
    """Serialize ``data`` as JSON that is safe inside an inline ``<script>`` element.

    ``json.dumps`` alone lets a string such as ``</script><img onerror=...>`` close the script
    block. Escaping ``<``, ``>`` and ``&`` as ``\\u003c`` etc. keeps the value identical for the
    JavaScript parser while the HTML parser never sees a tag. ``ensure_ascii`` (the default) already
    writes U+2028 and U+2029 as escapes, so they cannot end a JavaScript string literal.

    Args:
        data: A JSON-serializable value.

    Returns:
        A JavaScript expression that evaluates to ``data``.
    """
    return json.dumps(data).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")

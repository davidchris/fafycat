"""Pytest configuration and shared fixtures.

This conftest centralizes every import and environment setup that the
packaging refactor will rewrite. After the refactor, only the right-hand
side of the ``importlib.import_module`` calls in the TOUCHPOINT block
below needs to change. No fixture logic or test code moves.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# Path bootstrap — REMOVE after refactor (uv sync puts fafycat on sys.path).
# ---------------------------------------------------------------------------
_SRC = Path(__file__).parent.parent / "src"
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_SRC))
sys.path.insert(0, str(_ROOT))

# ---------------------------------------------------------------------------
# TOUCHPOINT: single place that names the "moving" modules.
# Post-refactor, flip the right-hand strings:
#   "src.fafycat.core.database" -> "fafycat.core.database"
#   "src.fafycat.core.config"   -> "fafycat.core.config"
#   "main"                      -> "fafycat.app"
#   "api.dependencies"          -> "fafycat.api.dependencies"
#   "api.ml"                    -> "fafycat.api.ml"
# ---------------------------------------------------------------------------
_database_mod = importlib.import_module("src.fafycat.core.database")
_config_mod = importlib.import_module("src.fafycat.core.config")
_app_mod = importlib.import_module("main")
_deps_mod = importlib.import_module("api.dependencies")
_ml_mod = importlib.import_module("api.ml")

Base = _database_mod.Base
DatabaseManager = _database_mod.DatabaseManager
AppConfig = _config_mod.AppConfig
create_app = _app_mod.create_app
get_db_session = _deps_mod.get_db_session
get_categorizer = _ml_mod.get_categorizer


def _get_cli_module() -> str:
    """Return the CLI module name suitable for ``python -m <mod>``.

    Pre-refactor: ``cli`` (the standalone ``cli.py`` at repo root).
    Post-refactor: ``fafycat`` (via ``src/fafycat/__main__.py``).
    """
    try:
        importlib.import_module("fafycat.__main__")
        return "fafycat"
    except ImportError:
        return "cli"


# ---------------------------------------------------------------------------
# Autouse environment isolation.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _isolate_fafycat_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip FAFYCAT_* env vars before each test; restore on teardown."""
    for key in list(os.environ):
        if key.startswith("FAFYCAT_"):
            monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# Isolated data directory (the core primitive).
# ---------------------------------------------------------------------------
@pytest.fixture
def tmp_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Per-test FAFYCAT_DATA_DIR plus derived DB/model/export env vars.

    Post-refactor, ``AppConfig`` derives everything from ``FAFYCAT_DATA_DIR``.
    Pre-refactor, each env var is read independently — we set all four so the
    fixture behaves the same on both sides of the refactor.
    """
    data_dir = tmp_path / "fafycat_data"
    data_dir.mkdir()
    (data_dir / "models").mkdir()
    (data_dir / "exports").mkdir()

    monkeypatch.setenv("FAFYCAT_DATA_DIR", str(data_dir))
    monkeypatch.setenv("FAFYCAT_DB_URL", f"sqlite:///{data_dir}/test.db")
    monkeypatch.setenv("FAFYCAT_MODEL_DIR", str(data_dir / "models"))
    monkeypatch.setenv("FAFYCAT_EXPORT_DIR", str(data_dir / "exports"))
    monkeypatch.setenv("FAFYCAT_ENV", "testing")
    return data_dir


# ---------------------------------------------------------------------------
# Legacy session fixture retained for backward compatibility.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def test_data_dir() -> Path:
    """Path to pre-baked test fixture files (CSVs, etc.)."""
    return Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Database engine/session bound to the isolated data dir.
# ---------------------------------------------------------------------------
@pytest.fixture
def temp_db(tmp_data_dir: Path):
    """SQLAlchemy engine pointing at ``tmp_data_dir/test.db``."""
    db_path = tmp_data_dir / "test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db_session(temp_db) -> Iterator:
    """Session bound to ``temp_db``; rolled back & closed on teardown."""
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=temp_db)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# App factory — replaces `from main import app` (which builds at import time).
# ---------------------------------------------------------------------------
@pytest.fixture
def app_factory(tmp_data_dir: Path) -> Callable:
    """Return a zero-arg callable that builds a fresh FastAPI app.

    Resets the ``api.ml`` module-level singletons so each built app starts
    with fresh categorizer/config state — mirrors what the current
    ``test_client`` fixture does inline.
    """

    def _build():
        _ml_mod._categorizer = None
        _ml_mod._config = None
        return create_app()

    return _build


# ---------------------------------------------------------------------------
# FastAPI TestClient with DB dependency override.
# ---------------------------------------------------------------------------
@pytest.fixture
def test_client(app_factory, db_session) -> Iterator[TestClient]:
    """TestClient with ``get_db_session`` overridden to yield ``db_session``."""
    app = app_factory()

    def override_get_db_session():
        return db_session

    app.dependency_overrides[get_db_session] = override_get_db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# CLI runner — invokes the fafycat CLI as a subprocess.
# ---------------------------------------------------------------------------
@pytest.fixture
def cli_runner(tmp_data_dir: Path) -> Callable[..., subprocess.CompletedProcess]:
    """Run the fafycat CLI as a subprocess with the isolated env.

    Works on both sides of the refactor because ``_get_cli_module()``
    auto-detects the right module name to pass to ``python -m``.
    """
    module = _get_cli_module()

    def _run(*args: str, check: bool = False, timeout: int = 60) -> subprocess.CompletedProcess:
        env = {**os.environ}
        # Ensure the subprocess can find `src.fafycat.*` pre-refactor and
        # `fafycat.*` post-refactor without requiring an editable install step.
        existing_pp = env.get("PYTHONPATH", "")
        paths = [str(_ROOT), str(_SRC)]
        if existing_pp:
            paths.append(existing_pp)
        env["PYTHONPATH"] = os.pathsep.join(paths)
        return subprocess.run(
            [sys.executable, "-m", module, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
            cwd=str(_ROOT),
            env=env,
        )

    return _run

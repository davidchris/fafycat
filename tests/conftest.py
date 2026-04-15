"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fafycat.api.dependencies import get_db_session
from fafycat.api.ml import get_categorizer, reset_singletons
from fafycat.app import create_app
from fafycat.core.config import AppConfig
from fafycat.core.database import Base, DatabaseManager
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_ROOT = Path(__file__).parent.parent


@pytest.fixture(autouse=True)
def _isolate_fafycat_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip FAFYCAT_* env vars before each test; restore on teardown."""
    for key in list(os.environ):
        if key.startswith("FAFYCAT_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def tmp_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Per-test FAFYCAT_DATA_DIR plus derived DB/model/export env vars."""
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


@pytest.fixture(scope="session")
def test_data_dir() -> Path:
    """Path to pre-baked test fixture files (CSVs, etc.)."""
    return Path(__file__).parent / "fixtures"


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


@pytest.fixture
def app_factory(tmp_data_dir: Path) -> Callable:
    """Return a zero-arg callable that builds a fresh FastAPI app."""

    def _build():
        reset_singletons()
        return create_app()

    return _build


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


@pytest.fixture
def cli_runner(tmp_data_dir: Path) -> Callable[..., subprocess.CompletedProcess]:
    """Run the fafycat CLI as a subprocess with the isolated env."""

    def _run(*args: str, check: bool = False, timeout: int = 60) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "fafycat", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
            cwd=str(_ROOT),
            env={**os.environ},
        )

    return _run

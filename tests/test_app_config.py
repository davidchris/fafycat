"""Contract tests for ``AppConfig`` env-var resolution.

The packaging refactor changes ``AppConfig`` default values (data goes to
``platformdirs.user_data_dir("fafycat")`` instead of a repo-local ``data/``
directory). The override-via-env-var contract is the invariant — these
tests lock it in so the refactor can't silently regress it.
"""

import importlib
from pathlib import Path

import pytest


def _app_config_cls():
    """Return the ``AppConfig`` class from whichever import path works.

    Pre-refactor: ``src.fafycat.core.config``. Post-refactor:
    ``fafycat.core.config``. Tests don't care which — they only exercise
    public surface.
    """
    try:
        return importlib.import_module("fafycat.core.config").AppConfig
    except ImportError:
        return importlib.import_module("src.fafycat.core.config").AppConfig


@pytest.fixture
def app_config(tmp_data_dir: Path):
    AppConfig = _app_config_cls()
    return AppConfig()


def test_data_dir_honors_env_var(tmp_data_dir: Path, app_config) -> None:
    assert Path(app_config.data_dir) == tmp_data_dir


def test_model_dir_honors_env_var(tmp_data_dir: Path, app_config) -> None:
    assert Path(app_config.ml.model_dir) == tmp_data_dir / "models"


def test_export_dir_honors_env_var(tmp_data_dir: Path, app_config) -> None:
    assert Path(app_config.export_dir) == tmp_data_dir / "exports"


def test_db_url_honors_env_var(tmp_data_dir: Path, app_config) -> None:
    assert str(tmp_data_dir) in app_config.database.url
    assert app_config.database.url.startswith("sqlite:///")


def test_ensure_dirs_creates_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``ensure_dirs`` creates the data, models, and exports directories."""
    data_dir = tmp_path / "fresh"
    monkeypatch.setenv("FAFYCAT_DATA_DIR", str(data_dir))
    monkeypatch.setenv("FAFYCAT_DB_URL", f"sqlite:///{data_dir}/test.db")
    monkeypatch.setenv("FAFYCAT_MODEL_DIR", str(data_dir / "models"))
    monkeypatch.setenv("FAFYCAT_EXPORT_DIR", str(data_dir / "exports"))
    data_dir.mkdir()

    AppConfig = _app_config_cls()
    cfg = AppConfig()
    cfg.ensure_dirs()

    assert data_dir.is_dir()
    assert (data_dir / "models").is_dir()
    assert (data_dir / "exports").is_dir()

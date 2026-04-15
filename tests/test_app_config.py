"""Contract tests for ``AppConfig`` env-var resolution."""

from pathlib import Path

import pytest
from fafycat.core.config import AppConfig


@pytest.fixture
def app_config(tmp_data_dir: Path):
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


def test_app_config_with_no_env_vars_uses_defaults() -> None:
    """Without any ``FAFYCAT_*`` env vars set, ``AppConfig()`` constructs cleanly."""
    cfg = AppConfig()
    assert isinstance(cfg.data_dir, Path)
    assert isinstance(cfg.export_dir, Path)
    assert isinstance(cfg.ml.model_dir, Path)
    assert cfg.database.url.startswith("sqlite:///")


def test_ensure_dirs_creates_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``ensure_dirs`` creates the data, models, and exports directories."""
    data_dir = tmp_path / "fresh"
    monkeypatch.setenv("FAFYCAT_DATA_DIR", str(data_dir))
    monkeypatch.setenv("FAFYCAT_DB_URL", f"sqlite:///{data_dir}/test.db")
    monkeypatch.setenv("FAFYCAT_MODEL_DIR", str(data_dir / "models"))
    monkeypatch.setenv("FAFYCAT_EXPORT_DIR", str(data_dir / "exports"))
    data_dir.mkdir()

    cfg = AppConfig()
    cfg.ensure_dirs()

    assert data_dir.is_dir()
    assert (data_dir / "models").is_dir()
    assert (data_dir / "exports").is_dir()

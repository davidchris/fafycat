"""Contract tests for ``AppConfig`` env-var resolution."""

from pathlib import Path

import pytest
from fafycat.core.config import AppConfig


# ---------------------------------------------------------------------------
# Config-file precedence tests
# ---------------------------------------------------------------------------


def test_config_file_data_dir_used_when_no_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Config file [paths].data_dir is used when FAFYCAT_DATA_DIR is not set."""
    config_path = tmp_path / "config.toml"
    data_dir = tmp_path / "from_config"
    config_path.write_text(f'[paths]\ndata_dir = "{data_dir}"\n')
    monkeypatch.setenv("FAFYCAT_CONFIG", str(config_path))

    cfg = AppConfig()

    assert cfg.data_dir == data_dir


def test_env_var_beats_config_file_for_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """FAFYCAT_DATA_DIR env var takes precedence over config file [paths].data_dir."""
    config_path = tmp_path / "config.toml"
    config_data_dir = tmp_path / "from_config"
    config_path.write_text(f'[paths]\ndata_dir = "{config_data_dir}"\n')
    monkeypatch.setenv("FAFYCAT_CONFIG", str(config_path))
    env_data_dir = tmp_path / "from_env"
    monkeypatch.setenv("FAFYCAT_DATA_DIR", str(env_data_dir))

    cfg = AppConfig()

    assert cfg.data_dir == env_data_dir


def test_config_file_db_url_used_when_no_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Config file [paths].db_url is used when FAFYCAT_DB_URL is not set."""
    config_path = tmp_path / "config.toml"
    db_url = f"sqlite:///{tmp_path}/custom.db"
    config_path.write_text(f'[paths]\ndb_url = "{db_url}"\n')
    monkeypatch.setenv("FAFYCAT_CONFIG", str(config_path))

    cfg = AppConfig()

    assert cfg.database.url == db_url


def test_config_file_model_dir_used_when_no_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Config file [paths].model_dir is used when FAFYCAT_MODEL_DIR is not set."""
    config_path = tmp_path / "config.toml"
    model_dir = tmp_path / "custom_models"
    config_path.write_text(f'[paths]\nmodel_dir = "{model_dir}"\n')
    monkeypatch.setenv("FAFYCAT_CONFIG", str(config_path))

    cfg = AppConfig()

    assert cfg.ml.model_dir == model_dir


def test_config_file_export_dir_used_when_no_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Config file [paths].export_dir is used when FAFYCAT_EXPORT_DIR is not set."""
    config_path = tmp_path / "config.toml"
    export_dir = tmp_path / "custom_exports"
    config_path.write_text(f'[paths]\nexport_dir = "{export_dir}"\n')
    monkeypatch.setenv("FAFYCAT_CONFIG", str(config_path))

    cfg = AppConfig()

    assert cfg.export_dir == export_dir


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

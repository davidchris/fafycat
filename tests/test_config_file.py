"""Isolated unit tests for the config-file loader module."""

from pathlib import Path

import pytest

from fafycat.core.config_file import load_config_file


def test_missing_file_returns_empty_dict(tmp_path: Path) -> None:
    result = load_config_file(tmp_path / "nonexistent.toml")
    assert result == {}


def test_valid_file_returns_paths_keys(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text('[paths]\ndata_dir = "/some/path"\ndb_url = "sqlite:///foo.db"\n')
    result = load_config_file(config)
    assert result["data_dir"] == "/some/path"
    assert result["db_url"] == "sqlite:///foo.db"


def test_partial_schema_is_fine(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text('[paths]\ndata_dir = "/only/this"\n')
    result = load_config_file(config)
    assert result == {"data_dir": "/only/this"}


def test_all_known_keys_accepted(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        "[paths]\n"
        'data_dir = "/d"\n'
        'db_url = "sqlite:///d/fafycat.db"\n'
        'model_dir = "/d/models"\n'
        'export_dir = "/d/exports"\n'
    )
    result = load_config_file(config)
    assert result == {
        "data_dir": "/d",
        "db_url": "sqlite:///d/fafycat.db",
        "model_dir": "/d/models",
        "export_dir": "/d/exports",
    }


def test_unknown_paths_key_warns_stderr(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    config = tmp_path / "config.toml"
    config.write_text('[paths]\ndata_dir = "/ok"\nunknown_key = "bad"\n')
    result = load_config_file(config)
    assert result == {"data_dir": "/ok"}
    captured = capsys.readouterr()
    assert "unknown_key" in captured.err


def test_unknown_section_warns_stderr(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    config = tmp_path / "config.toml"
    config.write_text('[paths]\ndata_dir = "/ok"\n\n[logging]\nlevel = "DEBUG"\n')
    result = load_config_file(config)
    assert result == {"data_dir": "/ok"}
    captured = capsys.readouterr()
    assert "logging" in captured.err


def test_malformed_toml_raises_value_error(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text("[paths\ndata_dir = oops\n")
    with pytest.raises(ValueError, match="Malformed TOML"):
        load_config_file(config)


def test_fafycat_config_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "custom.toml"
    config.write_text('[paths]\ndata_dir = "/custom"\n')
    monkeypatch.setenv("FAFYCAT_CONFIG", str(config))
    result = load_config_file(None)
    assert result["data_dir"] == "/custom"


def test_none_path_missing_default_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FAFYCAT_CONFIG", raising=False)
    # Default path (~/.config/fafycat/config.toml) almost certainly doesn't exist in CI
    # If it does exist, skip to avoid environment pollution.
    default = Path("~/.config/fafycat/config.toml").expanduser()
    if default.exists():
        pytest.skip("default config file exists on this machine")
    result = load_config_file(None)
    assert result == {}

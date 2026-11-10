"""scripts/reset_and_import.py deletes exactly the database it is about to rebuild."""

import importlib.util
from pathlib import Path

import pytest

from fafycat.core.config import AppConfig, DatabaseConfig

_SCRIPT = Path(__file__).parent.parent / "scripts" / "reset_and_import.py"


def _reset_database():
    spec = importlib.util.spec_from_file_location("reset_and_import", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.reset_database


@pytest.mark.parametrize("url_form", ["sqlite:///{path}", "sqlite:///file:{path}?uri=true"])
def test_reset_removes_the_configured_sqlite_file(tmp_path, url_form):
    db = tmp_path / "accounts.db"
    db.write_bytes(b"old data")

    _reset_database()(AppConfig(database=DatabaseConfig(url=url_form.format(path=db))))

    assert not db.exists()


def test_reset_refuses_a_database_it_cannot_delete():
    with pytest.raises(SystemExit):
        _reset_database()(AppConfig(database=DatabaseConfig(url="postgresql://localhost/fafycat")))

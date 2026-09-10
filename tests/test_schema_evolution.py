"""create_tables adds columns declared by the ORM but missing from an older database."""

from sqlalchemy import create_engine, text

from fafycat.core.config import AppConfig
from fafycat.core.database import DatabaseManager


def test_create_tables_adds_missing_nullable_column(tmp_data_dir):
    db_path = tmp_data_dir / "old.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE app_settings (key VARCHAR PRIMARY KEY, value VARCHAR NOT NULL)"))
    engine.dispose()

    config = AppConfig()
    config.database.url = f"sqlite:///{db_path}"
    DatabaseManager(config).create_tables()

    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        columns = {row[1] for row in conn.exec_driver_sql('PRAGMA table_info("app_settings")')}
    engine.dispose()
    assert "updated_at" in columns

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


def _prepare_db(db_path):
    """Create the schema and one category so transactions can be inserted."""
    config = AppConfig()
    config.database.url = f"sqlite:///{db_path}"
    manager = DatabaseManager(config)
    manager.create_tables()
    with manager.engine.begin() as conn:
        conn.execute(
            text("INSERT INTO categories (id, name, type, budget, is_active) VALUES (1, 'groceries', 'spending', 0, 1)")
        )
    return manager


def _insert_txn(conn, txn_id: str, *, is_reviewed: int | None, category_id: int | None, review_priority: str | None):
    conn.execute(
        text(
            "INSERT INTO transactions (id, date, value_date, name, purpose, amount, currency, "
            "import_batch, predicted_category_id, confidence_score, category_id, is_reviewed, review_priority) "
            "VALUES (:id, '2026-01-01', '2026-01-01', 'REWE', '', -10.0, 'EUR', 'test', 1, 0.95, :cat, :rev, :prio)"
        ),
        {"id": txn_id, "cat": category_id, "rev": is_reviewed, "prio": review_priority},
    )


def test_create_tables_repairs_review_flags(tmp_data_dir):
    db_path = tmp_data_dir / "orphans.db"
    manager = _prepare_db(db_path)
    with manager.engine.begin() as conn:
        _insert_txn(conn, "orphan", is_reviewed=1, category_id=None, review_priority="auto_accepted")
        _insert_txn(conn, "reviewed", is_reviewed=1, category_id=1, review_priority="auto_accepted")
        _insert_txn(conn, "pending", is_reviewed=0, category_id=None, review_priority="standard")
        _insert_txn(conn, "labelled", is_reviewed=0, category_id=1, review_priority="standard")
        _insert_txn(conn, "legacy", is_reviewed=None, category_id=1, review_priority=None)

    manager.create_tables()

    with manager.engine.connect() as conn:
        rows = {
            row[0]: (row[1], row[2], row[3])
            for row in conn.execute(text("SELECT id, is_reviewed, category_id, review_priority FROM transactions"))
        }
    manager.engine.dispose()
    assert rows["orphan"] == (0, None, None)
    assert rows["reviewed"] == (1, 1, "auto_accepted")
    assert rows["pending"] == (0, None, "standard")
    assert rows["labelled"] == (1, 1, "standard")
    assert rows["legacy"] == (1, 1, None)

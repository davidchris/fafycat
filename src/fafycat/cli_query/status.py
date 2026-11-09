"""``fafycat status``: where the data lives and what state it is in, without changing anything."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from fafycat.core.config import (
    DB_SOURCE_LEGACY_CWD,
    LEGACY_DB_FILENAME,
    PROD_DB_FILENAME,
    AppConfig,
    legacy_cwd_database,
    sqlite_path,
)


def location_warnings(config: AppConfig) -> list[str]:
    """Warn about the legacy ``./data`` database being in use and about other databases with data.

    FafyCat never merges databases. A second file with transactions in it
    usually means an earlier version wrote somewhere this one does not read.

    Args:
        config: The resolved configuration.

    Returns:
        Human-readable warnings, empty when there is nothing to report.
    """
    active = sqlite_path(config.database.url)
    active = active.resolve() if active is not None else None
    warnings: list[str] = []
    candidates = [config.data_dir / LEGACY_DB_FILENAME]

    if config.database.source == DB_SOURCE_LEGACY_CWD:
        legacy = legacy_cwd_database()
        warnings.append(
            f"Using the legacy database {legacy} because it is in ./data of the current directory. "
            f"Other directories use {config.data_dir / PROD_DB_FILENAME}. "
            f"Set FAFYCAT_DB_URL=sqlite:///{legacy} to choose it explicitly."
        )
        candidates.append(config.data_dir / PROD_DB_FILENAME)

    for candidate in candidates:
        path = candidate.resolve()
        if path == active or not path.exists():
            continue
        count = _count_transactions(path)
        if count:
            warnings.append(
                f"Another FafyCat database with {count} transactions exists at {path}. "
                f"This command uses {active or config.database.url} instead; nothing was merged. "
                f"To use that file, set FAFYCAT_DB_URL=sqlite:///{path} and drop --data-dir/--dev."
            )
    return warnings


def _count_transactions(path: Path) -> int:
    """Count transactions in a SQLite file opened read-only; 0 when it is not a FafyCat database."""
    try:
        conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    except sqlite3.Error:
        return 0
    try:
        return int(conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0])
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def _database_status(config: AppConfig) -> dict[str, Any]:
    from sqlalchemy import func

    from fafycat.core.database import CategoryORM, DatabaseManager, TransactionORM

    path = sqlite_path(config.database.url)
    exists = path is not None and path.exists()
    status: dict[str, Any] = {
        "url": config.database.url,
        "source": config.database.source,
        "path": str(path) if path is not None else None,
        "exists": exists,
        "schema_problems": [],
        "transactions": None,
        "reviewed": None,
        "unreviewed": None,
        "categories": None,
    }
    if not exists:
        return status

    try:
        db_manager = DatabaseManager(config, read_only=True)
    except ValueError as exc:
        status["schema_problems"] = [str(exc)]
        return status
    try:
        status["schema_problems"] = db_manager.schema_problems()
        if status["schema_problems"]:
            # Counting needs the current schema; the problems list is the answer.
            return status
        with db_manager.get_session() as session:
            total = session.query(func.count(TransactionORM.id)).scalar() or 0
            reviewed_filter = TransactionORM.is_reviewed.is_(True)
            reviewed = session.query(func.count(TransactionORM.id)).filter(reviewed_filter).scalar() or 0
            status["transactions"] = total
            status["reviewed"] = reviewed
            status["unreviewed"] = total - reviewed
            status["categories"] = session.query(func.count(CategoryORM.id)).scalar() or 0
    finally:
        db_manager.engine.dispose()
    return status


def _model_status(config: AppConfig) -> dict[str, Any]:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from fafycat.ml.categorizer import TransactionCategorizer
    from fafycat.ml.ensemble_categorizer import EnsembleCategorizer

    path = config.ml.model_path
    status: dict[str, Any] = {"path": str(path), "exists": path.exists(), "loads": False, "error": None}
    if not path.exists():
        return status

    # Loading needs a session object but reads no rows; keep the user's database out of it.
    engine = create_engine("sqlite://")
    session = sessionmaker(bind=engine)()
    try:
        categorizer = (
            EnsembleCategorizer(session, config.ml)
            if config.ml.use_ensemble
            else TransactionCategorizer(session, config.ml)
        )
        categorizer.load_model(path)
        status["loads"] = True
    except Exception as exc:  # noqa: BLE001 - any load failure is the answer, not a crash
        status["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        session.close()
        engine.dispose()
    return status


def build_status(config: AppConfig, *, dev: bool, version: str) -> dict[str, Any]:
    """Describe the data location, database contents, and model state of ``config``.

    Args:
        config: The resolved configuration.
        dev: Whether the development database was selected.
        version: The installed FafyCat version.

    Returns:
        A JSON-serialisable dict; see ``docs/coding-agents.md`` for the fields.
    """
    return {
        "version": version,
        "mode": "development" if dev else "production",
        "data_dir": str(config.data_dir),
        "database": _database_status(config),
        "model": _model_status(config),
        "warnings": location_warnings(config),
    }

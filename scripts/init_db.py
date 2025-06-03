#!/usr/bin/env python3
"""Initialize the FafyCat database."""

import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fafycat.core.config import AppConfig
from fafycat.core.database import DatabaseManager


def main() -> None:
    """Initialize database with default categories."""
    config = AppConfig()
    config.ensure_dirs()

    db_manager = DatabaseManager(config)

    print("Creating database tables...")
    db_manager.create_tables()

    print("Initializing default categories...")
    db_manager.init_default_categories()

    print("Database initialization complete!")


if __name__ == "__main__":
    main()

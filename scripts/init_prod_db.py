#!/usr/bin/env python3
"""Initialize the production FafyCat database."""

import os
import sys
from pathlib import Path

# Set production environment
os.environ["FAFYCAT_DB_URL"] = "sqlite:///data/fafycat_prod.db"
os.environ["FAFYCAT_ENV"] = "production"

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fafycat.core.config import AppConfig
from fafycat.core.database import DatabaseManager


def main() -> None:
    """Initialize production database with default categories."""
    print("🐱 Initializing FafyCat PRODUCTION database")

    config = AppConfig()
    config.ensure_dirs()

    print(f"📊 Database: {config.database.url}")

    db_manager = DatabaseManager(config)

    print("Creating database tables...")
    db_manager.create_tables()

    print("Initializing default categories...")
    db_manager.init_default_categories()

    print("✅ Production database initialization complete!")
    print("\n📝 Next steps:")
    print("1. Import your real transaction data through the UI")
    print("2. Review and categorize transactions")
    print("3. Train the model with your data")
    print("4. Use: uv run python run_prod.py")


if __name__ == "__main__":
    main()

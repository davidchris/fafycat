#!/usr/bin/env python3
"""Run FafyCat in development mode with test data."""

import os
import subprocess
import sys
from pathlib import Path


def setup_dev_database():
    """Set up development database with synthetic data if needed."""
    from api.services import CategoryService, TransactionService
    from src.fafycat.core.config import AppConfig
    from src.fafycat.core.database import DatabaseManager

    config = AppConfig()
    db_manager = DatabaseManager(config)

    # Initialize database tables
    db_manager.create_tables()

    with db_manager.get_session() as session:
        # Check if we have categories
        categories = CategoryService.get_categories(session)
        if not categories:
            print("🔄 Initializing default categories...")
            db_manager.init_default_categories()
            print("✅ Created default categories")

        # Check if we have transactions
        transactions = TransactionService.get_transactions(session, limit=1)

        if not transactions:
            print("🔄 Setting up synthetic test data...")
            from src.fafycat.data.csv_processor import CSVProcessor, create_synthetic_transactions

            processor = CSVProcessor(session)
            transactions = create_synthetic_transactions()
            new_count, _ = processor.save_transactions(transactions, "synthetic_batch")
            print(f"✅ Created {new_count} synthetic transactions")
        else:
            print(f"✅ Database has {len(TransactionService.get_transactions(session, limit=100))} transactions")


def main():
    """Run FafyCat in development mode."""
    # Set development environment
    os.environ.setdefault("FAFYCAT_DB_URL", "sqlite:///data/fafycat_dev.db")
    os.environ.setdefault("FAFYCAT_ENV", "development")
    os.environ.setdefault("FAFYCAT_DEV_PORT", "8001")
    os.environ.setdefault("FAFYCAT_HOST", "0.0.0.0")

    app_dir = Path(__file__).parent

    print("🐱 Starting FafyCat in DEVELOPMENT mode (FastAPI)")
    print(f"📊 Database: {os.environ['FAFYCAT_DB_URL']}")

    # Setup dev database with test data
    setup_dev_database()

    port = os.environ.get("FAFYCAT_DEV_PORT", "8001")
    host = os.environ.get("FAFYCAT_HOST", "0.0.0.0")
    print(f"🌐 Web UI will be available at: http://localhost:{port}")
    print(f"📚 API docs available at: http://localhost:{port}/docs")
    print("-" * 50)

    try:
        port = os.environ.get("FAFYCAT_DEV_PORT", "8001")
        host = os.environ.get("FAFYCAT_HOST", "0.0.0.0")
        subprocess.run(
            [sys.executable, "-m", "uvicorn", "main:app", "--reload", "--host", host, "--port", port],
            cwd=app_dir,
        )
    except KeyboardInterrupt:
        print("\n👋 FafyCat development mode stopped.")


if __name__ == "__main__":
    main()

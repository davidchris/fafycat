#!/usr/bin/env python3
"""
Reset database and import labeled data from scratch.

This script provides a clean slate for testing by:
1. Removing existing database files
2. Initializing fresh database with default categories
3. Importing labeled data from specified source
4. Optionally training a new ML model

Usage:
    uv run python scripts/reset_and_import.py [--labeled-data-path PATH] [--train-model]
"""

import argparse
import os
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fafycat.core.config import AppConfig
from fafycat.core.database import DatabaseManager


def reset_database(config: AppConfig) -> None:
    """Remove existing database files to start fresh."""
    # Extract database file path from URL
    db_url = config.database.url
    if db_url.startswith("sqlite:///"):
        db_file_path = Path(db_url.replace("sqlite:///", ""))
        if db_file_path.exists():
            print(f"Removing existing database: {db_file_path}")
            db_file_path.unlink()

    # Also remove common database locations
    common_db_paths = [
        Path("data/fafycat_prod.db"),
        Path("data/fafycat_dev.db"),
        Path("data/fafycat.db"),
    ]

    for db_path in common_db_paths:
        if db_path.exists():
            print(f"Removing existing database: {db_path}")
            db_path.unlink()


def initialize_fresh_database(config: AppConfig) -> DatabaseManager:
    """Initialize a completely fresh database (no default categories)."""
    print("Creating fresh database (no default categories - data-driven discovery)...")

    # Ensure data directory exists
    config.ensure_dirs()

    # Create database manager and tables
    db_manager = DatabaseManager(config)
    db_manager.create_tables()

    # Don't create default categories - let import process discover from data
    print("Database tables created. Categories will be discovered from imported data.")

    print(f"Database initialized at: {config.database.url}")
    return db_manager


def import_labeled_data(labeled_data_path: Path, config: AppConfig) -> None:
    """Import labeled data using the existing import script."""
    if not labeled_data_path.exists():
        print(f"Error: Labeled data path does not exist: {labeled_data_path}")
        sys.exit(1)

    print(f"Importing labeled data from: {labeled_data_path}")

    import subprocess

    # Set environment to use the same database as the reset script
    env = os.environ.copy()
    env["FAFYCAT_DB_URL"] = config.database.url

    # Run the import script with the custom data path
    result = subprocess.run(
        [sys.executable, "scripts/import_labeled_data.py", "--data-path", str(labeled_data_path)],
        capture_output=True,
        text=True,
        cwd=str(Path.cwd()),
        env=env,
    )

    if result.returncode != 0:
        print(f"Error importing labeled data: {result.stderr}")
        sys.exit(1)

    print("Labeled data imported successfully!")
    print(result.stdout)


def train_model() -> None:
    """Train a new ML model with the imported data."""
    print("Training new ML model...")

    import subprocess

    result = subprocess.run([sys.executable, "scripts/train_model.py"], capture_output=True, text=True)

    if result.returncode != 0:
        print(f"Error training model: {result.stderr}")
        sys.exit(1)

    print("Model training completed!")
    print(result.stdout)


def main():
    parser = argparse.ArgumentParser(description="Reset database and import labeled data from scratch")
    parser.add_argument(
        "--labeled-data-path",
        type=Path,
        default=Path("/Users/david/dev/fafycat-v1/dev_data/labeld"),
        help="Path to directory containing labeled CSV files (default: fafycat-v1 location)",
    )
    parser.add_argument("--train-model", action="store_true", help="Train ML model after importing data")
    parser.add_argument(
        "--use-sample-data", action="store_true", help="Use sample test data instead of real labeled data"
    )
    parser.add_argument(
        "--dev-mode", action="store_true", help="Use development database instead of production database"
    )

    args = parser.parse_args()

    # Set environment for production database by default (matches run_prod.py)
    if not args.dev_mode:
        os.environ["FAFYCAT_DB_URL"] = "sqlite:///data/fafycat_prod.db"
        os.environ["FAFYCAT_ENV"] = "production"
        db_mode = "PRODUCTION"
    else:
        os.environ["FAFYCAT_DB_URL"] = "sqlite:///data/fafycat_dev.db"
        os.environ["FAFYCAT_ENV"] = "development"
        db_mode = "DEVELOPMENT"

    # Use sample data if requested
    if args.use_sample_data:
        # Create a temporary directory with sample data
        sample_dir = Path("tests/fixtures")
        if not sample_dir.exists():
            print("Error: Sample data directory not found")
            sys.exit(1)
        args.labeled_data_path = sample_dir

    print(f"🔄 Starting fresh database reset and import ({db_mode})...")
    print("=" * 50)

    # Step 1: Reset database
    print("Step 1: Resetting database...")
    config = AppConfig()
    reset_database(config)

    # Step 2: Initialize fresh database
    print("\nStep 2: Initializing fresh database...")
    initialize_fresh_database(config)

    # Step 3: Import labeled data
    print("\nStep 3: Importing labeled data...")
    import_labeled_data(args.labeled_data_path, config)

    # Step 4: Train model (optional)
    if args.train_model:
        print("\nStep 4: Training ML model...")
        train_model()

    print("\n✅ Reset and import completed successfully!")
    print("=" * 50)
    print(f"Database location: {config.database.url}")
    if not args.dev_mode:
        print("🚀 Start the application: uv run python run_prod.py")
    else:
        print("🚀 Start the application: uv run python run_dev.py")
    print("You can now start the application with fresh labeled data.")


if __name__ == "__main__":
    main()

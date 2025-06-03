#!/usr/bin/env python3
"""Import synthetic transaction data for testing."""

import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fafycat.core.config import AppConfig
from fafycat.core.database import DatabaseManager
from fafycat.data.csv_processor import CSVProcessor, create_synthetic_transactions


def main() -> None:
    """Import synthetic transactions."""
    config = AppConfig()
    db_manager = DatabaseManager(config)

    with db_manager.get_session() as session:
        processor = CSVProcessor(session)

        print("Creating synthetic transactions...")
        transactions = create_synthetic_transactions()

        print(f"Saving {len(transactions)} transactions...")
        new_count, duplicate_count = processor.save_transactions(transactions, "synthetic_batch")

        print(f"Import complete: {new_count} new, {duplicate_count} duplicates")


if __name__ == "__main__":
    main()

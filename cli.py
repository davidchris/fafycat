"""CLI for headless fafycat operations."""

import argparse
import json
import sys
from pathlib import Path

from src.fafycat.core.config import AppConfig
from src.fafycat.core.database import DatabaseManager
from src.fafycat.data.csv_processor import CSVProcessor


def cmd_import(args: argparse.Namespace) -> None:
    """Import a CSV file and optionally run ML categorization."""
    csv_path = Path(args.file)
    if not csv_path.exists():
        print(json.dumps({"error": f"File not found: {csv_path}"}))
        sys.exit(1)

    config = AppConfig()
    config.ensure_dirs()
    db_manager = DatabaseManager(config)
    db_manager.create_tables()

    with db_manager.get_session() as session:
        processor = CSVProcessor(session)
        transactions, errors = processor.import_csv(csv_path)

        if errors:
            print(json.dumps({"error": f"CSV processing errors: {'; '.join(errors[:5])}"}))
            sys.exit(1)

        if not transactions:
            print(json.dumps({"error": "No valid transactions found in CSV"}))
            sys.exit(1)

        new_count, duplicate_count = processor.save_transactions(transactions)

        # Run ML predictions if available
        from api.upload import predict_transaction_categories

        cat_summary = predict_transaction_categories(session, transactions, new_count)

        result = {
            "filename": csv_path.name,
            "rows_processed": len(transactions),
            "transactions_imported": new_count,
            "duplicates_skipped": duplicate_count,
            **cat_summary,
        }

        print(json.dumps(result, indent=2))


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(prog="fafycat", description="FafyCat CLI for headless operations")
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser("import", help="Import transactions from a CSV file")
    import_parser.add_argument("file", help="Path to the CSV file")

    args = parser.parse_args()

    if args.command == "import":
        cmd_import(args)


if __name__ == "__main__":
    main()

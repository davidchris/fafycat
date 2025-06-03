#!/usr/bin/env python3
"""Import labeled transaction data from fafycat-v1."""

import os
import sys
from pathlib import Path

import pandas as pd

# Add project root to Python path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Module imports after path manipulation (required by E402)
from src.fafycat.core.config import AppConfig  # noqa: E402
from src.fafycat.core.database import DatabaseManager  # noqa: E402
from src.fafycat.core.models import TransactionInput  # noqa: E402
from src.fafycat.data.csv_processor import CSVProcessor  # noqa: E402

# Set production environment
os.environ["FAFYCAT_DB_URL"] = "sqlite:///data/fafycat_prod.db"
os.environ["FAFYCAT_ENV"] = "production"


def parse_labeled_csv(file_path: Path) -> list[TransactionInput]:
    """Parse a labeled CSV file and return TransactionInput objects."""
    df = pd.read_csv(file_path)
    transactions = []

    print(f"  📄 Processing {file_path.name}: {len(df)} transactions")

    for _, row in df.iterrows():
        try:
            # Parse date
            date_str = str(row["Date"]).strip()
            txn_date = pd.to_datetime(date_str, dayfirst=True).date()

            # Parse value date if different
            value_date = None
            if "Value date" in row and pd.notna(row["Value date"]):
                value_date_str = str(row["Value date"]).strip()
                if value_date_str != date_str:
                    value_date = pd.to_datetime(value_date_str, dayfirst=True).date()

            # Extract fields
            name = str(row["Name"]).strip()
            purpose = str(row.get("Purpose", "")).strip()
            amount = float(row["Amount"])
            currency = str(row.get("Currency", "EUR")).strip()

            # Get the human-labeled category
            category = None
            if "Cat" in row and pd.notna(row["Cat"]):
                category = str(row["Cat"]).strip()

            # Create transaction
            transaction = TransactionInput(
                date=txn_date,
                value_date=value_date,
                name=name,
                purpose=purpose,
                amount=amount,
                currency=currency,
                category=category,
            )

            transactions.append(transaction)

        except Exception as e:
            print(f"    ⚠️  Error parsing row: {e}")
            continue

    return transactions


def import_all_labeled_data():
    """Import all labeled data files."""
    # Path to labeled data
    labeled_data_dir = Path("/Users/david/dev/fafycat-v1/dev_data/labeld")

    if not labeled_data_dir.exists():
        print(f"❌ Labeled data directory not found: {labeled_data_dir}")
        return

    # Get all CSV files
    csv_files = sorted(labeled_data_dir.glob("*.csv"))

    if not csv_files:
        print(f"❌ No CSV files found in {labeled_data_dir}")
        return

    print("🐱 Importing labeled data to PRODUCTION database")
    print(f"📁 Source: {labeled_data_dir}")
    print(f"📊 Found {len(csv_files)} files")
    print("-" * 60)

    # Initialize config and database
    config = AppConfig()
    config.ensure_dirs()
    db_manager = DatabaseManager(config)

    total_imported = 0
    total_duplicates = 0
    total_errors = 0

    with db_manager.get_session() as session:
        processor = CSVProcessor(session)

        for csv_file in csv_files:
            try:
                print(f"📂 Processing {csv_file.name}...")

                # Parse the CSV file
                transactions = parse_labeled_csv(csv_file)

                if transactions:
                    # Import to database
                    new_count, duplicate_count = processor.save_transactions(
                        transactions, f"labeled_import_{csv_file.stem}"
                    )

                    total_imported += new_count
                    total_duplicates += duplicate_count

                    print(f"  ✅ Imported: {new_count} new, {duplicate_count} duplicates")
                else:
                    print("  ⚠️  No valid transactions found")

            except Exception as e:
                print(f"  ❌ Error processing {csv_file.name}: {e}")
                total_errors += 1
                continue

    print("-" * 60)
    print("🎉 Import Summary:")
    print(f"  📊 Total imported: {total_imported}")
    print(f"  🔄 Duplicates skipped: {total_duplicates}")
    print(f"  ❌ Files with errors: {total_errors}")
    print(f"  📈 Success rate: {((len(csv_files) - total_errors) / len(csv_files)) * 100:.1f}%")

    if total_imported > 0:
        print("\n✨ Great! Your labeled data is now imported.")
        print("📝 Next steps:")
        print("  1. Launch production mode: uv run python run_prod.py")
        print("  2. Go to Settings → Train New Model")
        print("  3. Review predictions on new transactions")


def check_categories():
    """Check what categories exist in the labeled data."""
    labeled_data_dir = Path("/Users/david/dev/fafycat-v1/dev_data/labeld")
    csv_files = sorted(labeled_data_dir.glob("*.csv"))

    all_categories = set()

    print("🏷️  Analyzing categories in your labeled data...")

    for csv_file in csv_files:
        try:
            df = pd.read_csv(csv_file)
            if "Cat" in df.columns:
                categories = df["Cat"].dropna().unique()
                all_categories.update(categories)
        except Exception as e:
            print(f"Error reading {csv_file}: {e}")

    print(f"\n📋 Found {len(all_categories)} unique categories:")
    for cat in sorted(all_categories):
        print(f"  - {cat}")

    return all_categories


def main():
    """Main import function."""
    print("🐱 FafyCat Labeled Data Importer")
    print("=" * 50)

    # First show what categories we have
    categories = check_categories()

    print(f"Found {len(categories)} categories. Will import and categorize transactions automatically...")
    import_all_labeled_data()


if __name__ == "__main__":
    main()

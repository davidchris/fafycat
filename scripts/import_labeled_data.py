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

# Set production environment only if not already set
if "FAFYCAT_DB_URL" not in os.environ:
    os.environ["FAFYCAT_DB_URL"] = "sqlite:///data/fafycat_prod.db"
if "FAFYCAT_ENV" not in os.environ:
    os.environ["FAFYCAT_ENV"] = "production"


def parse_labeled_csv(file_path: Path) -> list[TransactionInput]:
    """Parse a labeled CSV file and return TransactionInput objects."""
    df = pd.read_csv(file_path)
    transactions = []

    print(f"  📄 Processing {file_path.name}: {len(df)} transactions")

    # Handle both capitalized and lowercase column names
    col_mapping = {}
    for col in df.columns:
        lower_col = col.lower()
        if lower_col == "date":
            col_mapping["Date"] = col
        elif lower_col == "name":
            col_mapping["Name"] = col
        elif lower_col == "purpose":
            col_mapping["Purpose"] = col
        elif lower_col == "amount":
            col_mapping["Amount"] = col
        elif lower_col == "currency":
            col_mapping["Currency"] = col
        elif lower_col in ["cat", "category"]:
            col_mapping["Cat"] = col
        elif "value" in lower_col and "date" in lower_col:
            col_mapping["Value date"] = col

    for _, row in df.iterrows():
        try:
            # Parse date
            date_col = col_mapping.get("Date")
            if not date_col:
                print(f"    ⚠️  Error parsing row: No date column found")
                continue
            
            date_str = str(row[date_col]).strip()
            txn_date = pd.to_datetime(date_str, dayfirst=True).date()

            # Parse value date if different
            value_date = None
            value_date_col = col_mapping.get("Value date")
            if value_date_col and pd.notna(row[value_date_col]):
                value_date_str = str(row[value_date_col]).strip()
                if value_date_str != date_str:
                    value_date = pd.to_datetime(value_date_str, dayfirst=True).date()

            # Extract fields
            name = str(row[col_mapping.get("Name", "")]).strip()
            purpose = str(row.get(col_mapping.get("Purpose", ""), "")).strip()
            amount = float(row[col_mapping.get("Amount", "")])
            currency = str(row.get(col_mapping.get("Currency", ""), "EUR")).strip()

            # Get the human-labeled category
            category = None
            cat_col = col_mapping.get("Cat")
            if cat_col and pd.notna(row[cat_col]):
                category = str(row[cat_col]).strip()

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


def import_all_labeled_data(data_path: Path = None):
    """Import all labeled data files."""
    # Path to labeled data - use provided path or default
    if data_path is None:
        labeled_data_dir = Path("/Users/david/dev/fafycat-v1/dev_data/labeld")
    else:
        labeled_data_dir = data_path

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

    # First, discover all categories from the labeled data
    print("🏷️  Discovering categories from labeled data...")
    discovered_categories = check_categories(labeled_data_dir)

    if discovered_categories:
        print(f"📋 Creating {len(discovered_categories)} categories (without budgets)...")
        created_count = db_manager.discover_categories_from_data(discovered_categories)
        print(f"✅ Created {created_count} new categories")
        if created_count < len(discovered_categories):
            print(f"ℹ️  {len(discovered_categories) - created_count} categories already existed")
        print()

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
        print("  2. Go to Settings → Categories to review discovered categories")
        print("  3. Set budgets for your categories (optional)")
        print("  4. Go to Settings → Train New Model")
        print("  5. Review predictions on new transactions")


def check_categories(data_path: Path = None):
    """Check what categories exist in the labeled data."""
    if data_path is None:
        labeled_data_dir = Path("/Users/david/dev/fafycat-v1/dev_data/labeld")
    else:
        labeled_data_dir = data_path
    csv_files = sorted(labeled_data_dir.glob("*.csv"))

    all_categories = set()

    print("🏷️  Analyzing categories in your labeled data...")

    for csv_file in csv_files:
        try:
            df = pd.read_csv(csv_file)
            
            # Find category column (could be "Cat", "category", or similar)
            cat_col = None
            for col in df.columns:
                if col.lower() in ["cat", "category"]:
                    cat_col = col
                    break
            
            if cat_col:
                categories = df[cat_col].dropna().unique()
                all_categories.update(categories)
        except Exception as e:
            print(f"Error reading {csv_file}: {e}")

    print(f"\n📋 Found {len(all_categories)} unique categories:")
    for cat in sorted(all_categories):
        print(f"  - {cat}")

    return all_categories


def main():
    """Main import function."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Import labeled transaction data")
    parser.add_argument(
        "--data-path",
        type=Path,
        help="Path to directory containing labeled CSV files"
    )
    
    args = parser.parse_args()
    
    print("🐱 FafyCat Labeled Data Importer")
    print("=" * 50)

    # First show what categories we have
    categories = check_categories(args.data_path)

    print(f"Found {len(categories)} categories. Will import and categorize transactions automatically...")
    import_all_labeled_data(args.data_path)


if __name__ == "__main__":
    main()

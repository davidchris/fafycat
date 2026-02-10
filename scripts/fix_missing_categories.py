#!/usr/bin/env python3
"""Fix transactions that were imported without proper category assignment."""

import os
import sys
from pathlib import Path

# Set production environment to work with the production database
os.environ["FAFYCAT_DB_URL"] = "sqlite:///data/fafycat_prod.db"
os.environ["FAFYCAT_ENV"] = "production"

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.fafycat.core.config import AppConfig
from src.fafycat.core.database import CategoryORM, DatabaseManager, TransactionORM


def fix_missing_categories() -> None:
    """Fix transactions with missing category assignments based on merchant patterns."""

    config = AppConfig()
    db_manager = DatabaseManager(config)

    with db_manager.get_session() as session:
        # Get all categories for reference
        categories = {cat.name: cat.id for cat in session.query(CategoryORM).all()}
        print(f"📋 Available categories: {list(categories.keys())}")

        # Get transactions without categories
        uncategorized_txns = session.query(TransactionORM).filter(TransactionORM.category_id.is_(None)).all()

        print(f"🔍 Found {len(uncategorized_txns)} uncategorized transactions")

        if not uncategorized_txns:
            print("✅ All transactions already have categories!")
            return

        # Define merchant patterns for automatic categorization
        merchant_patterns = {
            "groceries": [
                "edeka",
                "rewe",
                "aldi",
                "lidl",
                "kaufland",
                "netto",
                "penny",
                "real",
                "norma",
                "tegut",
                "famila",
                "combi",
                "marktkauf",
            ],
            "restaurants": [
                "mcdonald",
                "burger king",
                "kfc",
                "subway",
                "pizza",
                "vapiano",
                "restaurant",
                "cafe",
                "bistro",
                "bar",
                "imbiss",
            ],
            "transportation": [
                "bvg",
                "db bahn",
                "deutsche bahn",
                "hvv",
                "mvg",
                "rnv",
                "vgn",
                "tankstelle",
                "shell",
                "aral",
                "esso",
                "total",
                "jet",
            ],
            "utilities": [
                "vattenfall",
                "gasag",
                "bwb",
                "telekom",
                "vodafone",
                "o2",
                "strom",
                "gas",
                "wasser",
                "internet",
                "telefon",
            ],
            "rent": ["miete", "immobilien", "hausverwaltung", "wohnung"],
            "salary": ["gehalt", "lohn", "salary", "einkommen"],
            "healthcare": ["apotheke", "arzt", "krankenhaus", "klinik", "pharmacy"],
            "insurance": ["versicherung", "insurance", "axa", "allianz", "ergo"],
            "entertainment": ["kino", "theater", "concert", "spotify", "netflix", "amazon prime"],
            "shopping": ["amazon", "zalando", "otto", "ebay", "h&m", "zara", "c&a"],
            "investment": ["sparplan", "etf", "aktien", "depot", "investment", "msci", "ishares"],
        }

        categorized_count = 0

        for txn in uncategorized_txns:
            # Create a combined text to search in (name + purpose)
            search_text = f"{txn.name} {txn.purpose or ''}".lower()

            # Try to match against patterns
            matched_category = None
            for category_name, patterns in merchant_patterns.items():
                for pattern in patterns:
                    if pattern in search_text and category_name in categories:
                        matched_category = categories[category_name]
                        break
                if matched_category:
                    break

            # Update transaction if we found a match
            if matched_category:
                txn.category_id = matched_category
                categorized_count += 1

        # Commit changes
        session.commit()

        print(f"✅ Successfully categorized {categorized_count} transactions")
        print(f"📊 Remaining uncategorized: {len(uncategorized_txns) - categorized_count}")

        # Show breakdown by category
        print("\n📈 Category distribution:")
        for category_name, category_id in categories.items():
            count = session.query(TransactionORM).filter(TransactionORM.category_id == category_id).count()
            if count > 0:
                print(f"  {category_name}: {count} transactions")

        # Show total categorized transactions
        total_categorized = session.query(TransactionORM).filter(TransactionORM.category_id.isnot(None)).count()

        print(f"\n🎯 Total categorized transactions: {total_categorized}")

        if total_categorized >= 50:
            print("✨ Great! You now have enough data to train the ML model.")
            print("📝 Next steps:")
            print("  1. Run: python scripts/train_model.py")
            print("  2. Or use the Streamlit app: uv run python run_prod.py")
        else:
            print(f"⚠️  Still need {50 - total_categorized} more categorized transactions for training.")


if __name__ == "__main__":
    print("🐱 FafyCat Category Fixer")
    print("=" * 40)
    fix_missing_categories()

#!/usr/bin/env python3
"""
Migration script to add yearly budget functionality.
Creates budget_plans table and migrates existing category budgets to current year.
"""

import sys
from datetime import date, datetime
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from src.fafycat.core.config import AppConfig
from src.fafycat.core.database import BudgetPlanORM, CategoryORM, DatabaseManager


def migrate_yearly_budgets():
    """Migrate existing category budgets to yearly budget plans."""
    config = AppConfig()
    db_manager = DatabaseManager(config)

    print("🔄 Starting yearly budget migration...")

    # Create new tables
    print("📊 Creating budget_plans table...")
    db_manager.create_tables()

    current_year = date.today().year

    with db_manager.get_session() as session:
        # Get all categories with budgets > 0
        categories_with_budgets = (
            session.query(CategoryORM).filter(CategoryORM.budget > 0, CategoryORM.is_active).all()
        )

        print(f"📋 Found {len(categories_with_budgets)} categories with budgets to migrate")

        migrated_count = 0
        for category in categories_with_budgets:
            # Check if budget plan already exists for current year
            existing_plan = (
                session.query(BudgetPlanORM)
                .filter(BudgetPlanORM.category_id == category.id, BudgetPlanORM.year == current_year)
                .first()
            )

            if existing_plan:
                print(f"⚠️  Budget plan already exists for {category.name} ({current_year}), skipping...")
                continue

            # Create budget plan for current year
            budget_plan = BudgetPlanORM(
                category_id=category.id,
                year=current_year,
                monthly_budget=category.budget,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )

            session.add(budget_plan)
            migrated_count += 1
            print(f"✅ Migrated {category.name}: €{category.budget}/month → {current_year} budget plan")

        # Commit all changes
        session.commit()

        print("🎉 Migration completed!")
        print(f"   • Migrated {migrated_count} budget plans")
        print(f"   • All budgets moved to year {current_year}")
        print("   • Original category.budget values preserved as fallback")

        # Verify migration
        total_plans = session.query(BudgetPlanORM).count()
        print(f"   • Total budget plans in database: {total_plans}")


if __name__ == "__main__":
    migrate_yearly_budgets()

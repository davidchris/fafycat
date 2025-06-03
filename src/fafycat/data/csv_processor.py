"""CSV import and export functionality."""

import csv
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from ..core.database import CategoryORM, TransactionORM
from ..core.models import TransactionInput


class CSVProcessor:
    """Handle CSV import and export operations."""

    def __init__(self, session: Session):
        self.session = session

    def import_csv(self, file_path: Path, csv_format: str = "generic") -> tuple[list[TransactionInput], list[str]]:
        """Import transactions from CSV file.

        Returns:
            Tuple of (successful_transactions, error_messages)
        """
        transactions = []
        errors = []

        try:
            df = pd.read_csv(file_path)

            if csv_format == "generic":
                transactions, errors = self._parse_generic_format(df)
            else:
                errors.append(f"Unknown CSV format: {csv_format}")

        except Exception as e:
            errors.append(f"Failed to read CSV file: {str(e)}")

        return transactions, errors

    def _parse_generic_format(self, df: pd.DataFrame) -> tuple[list[TransactionInput], list[str]]:
        """Parse generic CSV format with flexible column mapping."""
        transactions = []
        errors = []

        # Column mapping - flexible to handle different formats
        column_mapping = self._detect_column_mapping(df.columns.tolist())

        if not column_mapping:
            errors.append("Could not detect required columns (date, amount, description)")
            return transactions, errors

        for idx, row in df.iterrows():
            try:
                # Extract required fields
                txn_date = self._parse_date(row[column_mapping["date"]])
                amount = float(row[column_mapping["amount"]])
                name = str(row[column_mapping.get("name", column_mapping["description"])]).strip()
                purpose = str(row[column_mapping["purpose"]]).strip() if "purpose" in column_mapping else ""

                # Optional fields
                value_date = None
                if "value_date" in column_mapping:
                    value_date = self._parse_date(row[column_mapping["value_date"]])

                category = None
                if "category" in column_mapping:
                    category = str(row[column_mapping["category"]]).strip()

                account = str(row[column_mapping["account"]]).strip() if "account" in column_mapping else None

                currency = str(row[column_mapping["currency"]]).strip() if "currency" in column_mapping else "EUR"

                # Create transaction
                transaction = TransactionInput(
                    date=txn_date,
                    value_date=value_date,
                    category=category if category and category.lower() != "nan" else None,
                    name=name,
                    purpose=purpose,
                    account=account,
                    amount=amount,
                    currency=currency,
                )

                transactions.append(transaction)

            except Exception as e:
                errors.append(f"Row {idx + 1}: {str(e)}")

        return transactions, errors

    def _detect_column_mapping(self, columns: list[str]) -> dict[str, str] | None:
        """Detect column mapping from CSV headers."""
        columns_lower = [col.lower() for col in columns]
        mapping = {}

        # Required: date
        date_candidates = ["date", "datum", "transaction_date", "buchungstag"]
        for candidate in date_candidates:
            if candidate in columns_lower:
                mapping["date"] = columns[columns_lower.index(candidate)]
                break

        # Required: amount
        amount_candidates = ["amount", "betrag", "value", "sum", "summe"]
        for candidate in amount_candidates:
            if candidate in columns_lower:
                mapping["amount"] = columns[columns_lower.index(candidate)]
                break

        # Required: description/name
        desc_candidates = ["description", "name", "merchant", "empfaenger", "verwendungszweck", "reference"]
        for candidate in desc_candidates:
            if candidate in columns_lower:
                mapping["description"] = columns[columns_lower.index(candidate)]
                break

        # Optional: separate name and purpose
        name_candidates = ["name", "merchant", "empfaenger", "zahlungsempfaenger"]
        for candidate in name_candidates:
            if candidate in columns_lower:
                mapping["name"] = columns[columns_lower.index(candidate)]
                break

        purpose_candidates = ["purpose", "verwendungszweck", "reference", "memo"]
        for candidate in purpose_candidates:
            if candidate in columns_lower:
                mapping["purpose"] = columns[columns_lower.index(candidate)]
                break

        # Optional: value date
        value_date_candidates = ["value_date", "valuta", "wertstellung"]
        for candidate in value_date_candidates:
            if candidate in columns_lower:
                mapping["value_date"] = columns[columns_lower.index(candidate)]
                break

        # Optional: category
        category_candidates = ["category", "kategorie", "type"]
        for candidate in category_candidates:
            if candidate in columns_lower:
                mapping["category"] = columns[columns_lower.index(candidate)]
                break

        # Optional: account
        account_candidates = ["account", "konto", "account_number"]
        for candidate in account_candidates:
            if candidate in columns_lower:
                mapping["account"] = columns[columns_lower.index(candidate)]
                break

        # Optional: currency
        currency_candidates = ["currency", "waehrung", "ccy"]
        for candidate in currency_candidates:
            if candidate in columns_lower:
                mapping["currency"] = columns[columns_lower.index(candidate)]
                break

        # Verify required fields
        if not all(key in mapping for key in ["date", "amount", "description"]):
            return None

        return mapping

    def _parse_date(self, date_str: Any) -> date:
        """Parse date from various formats."""
        if pd.isna(date_str):
            raise ValueError("Date is missing")

        date_str = str(date_str).strip()

        # Try common date formats
        date_formats = ["%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"]

        for fmt in date_formats:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue

        raise ValueError(f"Could not parse date: {date_str}")

    def save_transactions(
        self, transactions: list[TransactionInput], import_batch: str | None = None
    ) -> tuple[int, int]:
        """Save transactions to database with deduplication.

        Returns:
            Tuple of (new_count, duplicate_count)
        """
        if not import_batch:
            import_batch = str(uuid.uuid4())

        new_count = 0
        duplicate_count = 0

        for txn in transactions:
            txn_id = txn.generate_id()

            # Check for existing transaction
            existing = self.session.query(TransactionORM).filter(TransactionORM.id == txn_id).first()

            if existing:
                duplicate_count += 1
                continue

            # Create new transaction
            db_txn = TransactionORM(
                id=txn_id,
                date=txn.date,
                value_date=txn.value_date,
                name=txn.name,
                purpose=txn.purpose,
                amount=txn.amount,
                currency=txn.currency,
                imported_at=datetime.utcnow(),
                import_batch=import_batch,
            )

            # Try to match existing category if provided
            if txn.category:
                # Try exact match first (case insensitive)
                category = self.session.query(CategoryORM).filter(CategoryORM.name.ilike(txn.category.strip())).first()

                # If no exact match, try with lowercased input
                if not category:
                    category = (
                        self.session.query(CategoryORM).filter(CategoryORM.name == txn.category.lower().strip()).first()
                    )

                if category:
                    db_txn.category_id = category.id

            self.session.add(db_txn)
            new_count += 1

        self.session.commit()
        return new_count, duplicate_count

    def export_transactions(
        self,
        output_path: Path,
        start_date: date | None = None,
        end_date: date | None = None,
        category_ids: list[int] | None = None,
    ) -> None:
        """Export transactions to CSV."""
        query = self.session.query(TransactionORM)

        if start_date:
            query = query.filter(TransactionORM.date >= start_date)
        if end_date:
            query = query.filter(TransactionORM.date <= end_date)
        if category_ids:
            query = query.filter(TransactionORM.category_id.in_(category_ids))

        transactions = query.order_by(TransactionORM.date.desc()).all()

        # Get categories for lookup
        categories = {cat.id: cat.name for cat in self.session.query(CategoryORM).all()}

        with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)

            # Header
            writer.writerow(
                [
                    "id",
                    "date",
                    "value_date",
                    "name",
                    "purpose",
                    "amount",
                    "currency",
                    "category",
                    "predicted_category",
                    "confidence_score",
                    "is_reviewed",
                ]
            )

            # Data
            for txn in transactions:
                category_name = categories.get(txn.category_id, "") if txn.category_id else ""
                predicted_category_name = (
                    categories.get(txn.predicted_category_id, "") if txn.predicted_category_id else ""
                )

                writer.writerow(
                    [
                        txn.id,
                        txn.date.isoformat(),
                        txn.value_date.isoformat() if txn.value_date else "",
                        txn.name,
                        txn.purpose,
                        txn.amount,
                        txn.currency,
                        category_name,
                        predicted_category_name,
                        txn.confidence_score or "",
                        txn.is_reviewed,
                    ]
                )


def create_synthetic_transactions() -> list[TransactionInput]:
    """Create synthetic transaction data for testing."""
    import random
    from datetime import timedelta

    base_date = date(2024, 1, 1)
    transactions = []

    # Grocery transactions
    grocery_merchants = ["EDEKA", "REWE", "ALDI", "LIDL", "Kaufland"]
    for i in range(30):
        txn_date = base_date + timedelta(days=random.randint(0, 330))
        merchant = random.choice(grocery_merchants)
        amount = -round(random.uniform(15.50, 89.99), 2)
        transactions.append(
            TransactionInput(
                date=txn_date,
                name=f"{merchant} Markt {random.randint(1001, 9999)}",
                purpose="Lastschrift",
                amount=amount,
                category="groceries",
            )
        )

    # Restaurant transactions
    restaurants = ["McDonald's", "Burger King", "Pizza Express", "Vapiano", "Subway"]
    for i in range(15):
        txn_date = base_date + timedelta(days=random.randint(0, 330))
        restaurant = random.choice(restaurants)
        amount = -round(random.uniform(8.50, 45.90), 2)
        transactions.append(
            TransactionInput(
                date=txn_date,
                name=f"{restaurant} Berlin",
                purpose="Kartenzahlung",
                amount=amount,
                category="restaurants",
            )
        )

    # Salary
    for month in range(12):
        txn_date = date(2024, month + 1, 25)
        transactions.append(
            TransactionInput(
                date=txn_date, name="TECH COMPANY GMBH", purpose="Gehalt Januar 2024", amount=3500.00, category="salary"
            )
        )

    # Rent
    for month in range(12):
        txn_date = date(2024, month + 1, 1)
        transactions.append(
            TransactionInput(
                date=txn_date, name="IMMOBILIEN AG", purpose="Miete Wohnung", amount=-1200.00, category="rent"
            )
        )

    # Utilities
    utility_companies = ["Vattenfall", "GASAG", "BWB", "Telekom"]
    for company in utility_companies:
        for quarter in range(4):
            txn_date = base_date + timedelta(days=quarter * 90 + random.randint(1, 30))
            amount = -round(random.uniform(45.00, 120.00), 2)
            transactions.append(
                TransactionInput(
                    date=txn_date, name=company, purpose="Lastschrift Rechnung", amount=amount, category="utilities"
                )
            )

    return transactions

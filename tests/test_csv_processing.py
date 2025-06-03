"""Tests for CSV processing functionality."""

import csv
import tempfile
from datetime import date
from pathlib import Path

import pytest

from fafycat.core.config import AppConfig
from fafycat.core.database import DatabaseManager
from fafycat.data.csv_processor import CSVProcessor, create_synthetic_transactions


class TestCSVProcessor:
    """Test CSV processing functionality."""

    @pytest.fixture
    def setup_db(self):
        """Set up test database."""
        config = AppConfig()
        config.database.url = "sqlite:///:memory:"

        db_manager = DatabaseManager(config)
        db_manager.create_tables()
        db_manager.init_default_categories()

        return db_manager

    def test_column_detection(self, setup_db):
        """Test automatic column detection."""
        db_manager = setup_db

        with db_manager.get_session() as session:
            processor = CSVProcessor(session)

            # Test German format
            columns = ["datum", "empfaenger", "verwendungszweck", "betrag", "waehrung"]
            mapping = processor._detect_column_mapping(columns)

            assert mapping is not None
            assert mapping["date"] == "datum"
            assert mapping["description"] == "empfaenger"
            assert mapping["amount"] == "betrag"

    def test_date_parsing(self, setup_db):
        """Test date parsing from various formats."""
        db_manager = setup_db

        with db_manager.get_session() as session:
            processor = CSVProcessor(session)

            test_dates = [
                ("2024-01-15", date(2024, 1, 15)),
                ("15.01.2024", date(2024, 1, 15)),
                ("15/01/2024", date(2024, 1, 15)),
                ("01/15/2024", date(2024, 1, 15)),
            ]

            for date_str, expected_date in test_dates:
                result = processor._parse_date(date_str)
                assert result == expected_date

    def test_csv_import(self, setup_db):
        """Test importing transactions from CSV file."""
        db_manager = setup_db

        # Create test CSV file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            writer = csv.writer(f)
            writer.writerow(['date', 'name', 'purpose', 'amount', 'currency'])
            writer.writerow(['2024-01-15', 'EDEKA Markt', 'Lastschrift', '-45.67', 'EUR'])
            writer.writerow(['2024-01-16', 'McDonald\'s', 'Kartenzahlung', '-12.50', 'EUR'])
            writer.writerow(['2024-01-25', 'COMPANY GMBH', 'Gehalt', '3500.00', 'EUR'])

            temp_path = Path(f.name)

        try:
            with db_manager.get_session() as session:
                processor = CSVProcessor(session)

                # Import transactions
                transactions, errors = processor.import_csv(temp_path)

                assert len(errors) == 0
                assert len(transactions) == 3

                # Check transaction data
                assert transactions[0].name == 'EDEKA Markt'
                assert transactions[0].amount == -45.67
                assert transactions[1].name == 'McDonald\'s'
                assert transactions[2].amount == 3500.00

        finally:
            temp_path.unlink()

    def test_deduplication(self, setup_db):
        """Test transaction deduplication."""
        db_manager = setup_db

        # Create test CSV file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            writer = csv.writer(f)
            writer.writerow(['date', 'name', 'purpose', 'amount', 'currency'])
            writer.writerow(['2024-01-15', 'EDEKA Markt', 'Lastschrift', '-45.67', 'EUR'])
            writer.writerow(['2024-01-15', 'EDEKA Markt', 'Lastschrift', '-45.67', 'EUR'])  # Duplicate
            writer.writerow(['2024-01-16', 'McDonald\'s', 'Kartenzahlung', '-12.50', 'EUR'])

            temp_path = Path(f.name)

        try:
            with db_manager.get_session() as session:
                processor = CSVProcessor(session)

                # First import
                transactions, _ = processor.import_csv(temp_path)

                # Manually filter duplicates since CSV contains duplicates
                seen_ids = set()
                unique_transactions = []
                duplicates_in_csv = 0

                for txn in transactions:
                    txn_id = txn.generate_id()
                    if txn_id in seen_ids:
                        duplicates_in_csv += 1
                    else:
                        seen_ids.add(txn_id)
                        unique_transactions.append(txn)

                new_count1, duplicate_count1 = processor.save_transactions(unique_transactions)

                assert new_count1 == 2  # Only unique transactions
                assert duplicate_count1 == 0  # No duplicates in database yet
                assert duplicates_in_csv == 1  # One duplicate in CSV

                # Second import (all should be duplicates)
                transactions, _ = processor.import_csv(temp_path)
                new_count2, duplicate_count2 = processor.save_transactions(transactions)

                assert new_count2 == 0
                assert duplicate_count2 == 3  # All transactions are duplicates (includes original duplicate in CSV)

        finally:
            temp_path.unlink()

    def test_synthetic_data_generation(self):
        """Test synthetic transaction data generation."""
        transactions = create_synthetic_transactions()

        assert len(transactions) > 0

        # Check for different types of transactions
        transaction_types = set()
        for txn in transactions:
            if txn.category:
                transaction_types.add(txn.category)

        # Should have variety of categories
        assert 'groceries' in transaction_types
        assert 'salary' in transaction_types
        assert 'rent' in transaction_types

        # Check date range (should span a year)
        dates = [txn.date for txn in transactions]
        date_range = max(dates) - min(dates)
        assert date_range.days > 300  # Should span most of a year

    def test_export(self, setup_db):
        """Test exporting transactions to CSV."""
        db_manager = setup_db

        with db_manager.get_session() as session:
            processor = CSVProcessor(session)

            # Import some test data first
            transactions = create_synthetic_transactions()[:10]  # Just first 10
            processor.save_transactions(transactions)

            # Export to temporary file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
                export_path = Path(f.name)

            try:
                processor.export_transactions(export_path)

                # Verify export file exists and has content
                assert export_path.exists()

                # Read and verify content
                with open(export_path) as f:
                    content = f.read()
                    assert 'id,date,value_date,name,purpose,amount' in content
                    assert len(content.splitlines()) > 1  # Header + data

            finally:
                export_path.unlink()


if __name__ == "__main__":
    pytest.main([__file__])

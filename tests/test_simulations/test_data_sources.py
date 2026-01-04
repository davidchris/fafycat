"""Tests for simulations/data_sources.py"""

import tempfile
from pathlib import Path

import pytest

from simulations import CSVDataSource, DataSource, DictDataSource


class TestDictDataSource:
    """Tests for DictDataSource."""

    def test_returns_copy(self):
        """Returns a copy, not the original dict."""
        original = {'income': 5000.0, 'spending': 3000.0, 'saving': 500.0}
        source = DictDataSource(original)

        result = source.get_baseline_cashflow()
        result['income'] = 0  # Modify result

        # Original should be unchanged
        assert source.get_baseline_cashflow()['income'] == 5000.0

    def test_get_baseline_cashflow(self):
        """get_baseline_cashflow returns expected format."""
        data = {'income': 5000.0, 'spending': 3000.0, 'saving': 500.0}
        source = DictDataSource(data)

        result = source.get_baseline_cashflow()

        assert result['income'] == 5000.0
        assert result['spending'] == 3000.0
        assert result['saving'] == 500.0

    def test_get_monthly_averages(self):
        """get_monthly_averages returns same data (pre-aggregated)."""
        data = {'income': 5000.0, 'spending': 3000.0}
        source = DictDataSource(data)

        # Parameters are ignored for DictDataSource
        result = source.get_monthly_averages(months_back=6, exclude_outliers=True)

        assert result == data

    def test_implements_datasource(self):
        """DictDataSource implements DataSource interface."""
        source = DictDataSource({'income': 1000.0})
        assert isinstance(source, DataSource)


class TestCSVDataSource:
    """Tests for CSVDataSource."""

    def test_file_not_found(self):
        """Raises FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            CSVDataSource('/nonexistent/path/file.csv')

    def test_load_csv_data(self, tmp_path):
        """Loads CSV data correctly."""
        # Use recent dates (within months_back window)
        from datetime import date, timedelta

        today = date.today()
        last_month = today.replace(day=15) - timedelta(days=30)
        two_months_ago = last_month - timedelta(days=30)

        csv_content = f"""date,amount,category_type
{two_months_ago.isoformat()},5000.00,income
{two_months_ago.isoformat()},1200.00,spending
{two_months_ago.isoformat()},500.00,saving
{last_month.isoformat()},5000.00,income
{last_month.isoformat()},1100.00,spending
{last_month.isoformat()},600.00,saving
"""
        csv_file = tmp_path / 'transactions.csv'
        csv_file.write_text(csv_content)

        source = CSVDataSource(str(csv_file), months_back=12)
        result = source.get_baseline_cashflow()

        assert 'income' in result
        assert 'spending' in result
        assert 'saving' in result
        assert result['income'] > 0
        assert result['spending'] > 0

    def test_custom_column_names(self, tmp_path):
        """Supports custom column names."""
        csv_content = """transaction_date,value,type
2024-01-15,5000.00,income
2024-01-20,1200.00,spending
"""
        csv_file = tmp_path / 'custom.csv'
        csv_file.write_text(csv_content)

        source = CSVDataSource(
            str(csv_file),
            date_column='transaction_date',
            amount_column='value',
            category_type_column='type',
        )

        result = source.get_baseline_cashflow()
        assert 'income' in result

    def test_implements_datasource(self, tmp_path):
        """CSVDataSource implements DataSource interface."""
        csv_content = """date,amount,category_type
2024-01-15,5000.00,income
"""
        csv_file = tmp_path / 'test.csv'
        csv_file.write_text(csv_content)

        source = CSVDataSource(str(csv_file))
        assert isinstance(source, DataSource)

    def test_empty_category_returns_zero(self, tmp_path):
        """Returns 0 for categories with no transactions."""
        csv_content = """date,amount,category_type
2024-01-15,5000.00,income
"""
        csv_file = tmp_path / 'income_only.csv'
        csv_file.write_text(csv_content)

        source = CSVDataSource(str(csv_file), months_back=12)
        result = source.get_baseline_cashflow()

        assert result['spending'] == 0.0
        assert result['saving'] == 0.0


class TestDataSourceInterface:
    """Tests for DataSource abstract base class."""

    def test_cannot_instantiate_directly(self):
        """Cannot instantiate DataSource directly."""
        with pytest.raises(TypeError):
            DataSource()

    def test_custom_implementation(self):
        """Can create custom DataSource implementations."""

        class ConstantDataSource(DataSource):
            def get_baseline_cashflow(self) -> dict[str, float]:
                return {'income': 1000.0, 'spending': 500.0, 'saving': 100.0}

        source = ConstantDataSource()
        result = source.get_baseline_cashflow()

        assert result['income'] == 1000.0
        assert isinstance(source, DataSource)

"""Abstract data source interface and implementations for simulations."""

from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path

import pandas as pd
from dateutil.relativedelta import relativedelta


class DataSource(ABC):
    """Abstract interface for financial data sources.

    Implement this interface to provide custom data sources for simulations.
    The simulation framework only requires `get_baseline_cashflow()` which returns
    a dict with 'income', 'spending', and 'saving' monthly averages.

    Optionally override `get_monthly_averages()` for more control over filtering.
    """

    @abstractmethod
    def get_baseline_cashflow(self) -> dict[str, float]:
        """Return baseline monthly cashflow data.

        Returns:
            Dict with keys: 'income', 'spending', 'saving' (monthly averages in EUR)
        """
        pass

    def get_monthly_averages(
        self,
        year: int | list[int] | None = None,
        months_back: int = 12,
        exclude_outliers: bool = True,
        outlier_percentiles: tuple[float, float] = (1, 99),
    ) -> dict[str, float]:
        """Get monthly averages with optional filtering.

        Default implementation returns baseline cashflow.
        Override for data sources that support filtering.

        Args:
            year: Specific year(s) to analyze (ignored in default impl)
            months_back: Number of recent months to analyze (ignored in default impl)
            exclude_outliers: If True, exclude outliers (ignored in default impl)
            outlier_percentiles: Percentile range for outlier filtering (ignored in default impl)

        Returns:
            Dict with keys: 'income', 'spending', 'saving' (monthly averages)
        """
        return self.get_baseline_cashflow()


class DictDataSource(DataSource):
    """Simple data source from a dictionary.

    Useful for testing, quick prototypes, or when you already have
    pre-calculated monthly averages.

    Example:
        source = DictDataSource({
            'income': 5000.0,
            'spending': 3500.0,
            'saving': 500.0
        })
        sim = Simulation(source.get_baseline_cashflow())
    """

    def __init__(self, data: dict[str, float]):
        """Initialize with pre-calculated monthly averages.

        Args:
            data: Dict with 'income', 'spending', 'saving' keys (monthly amounts)
        """
        self._data = data.copy()

    def get_baseline_cashflow(self) -> dict[str, float]:
        """Return the stored baseline data."""
        return self._data.copy()

    def get_monthly_averages(
        self,
        year: int | list[int] | None = None,
        months_back: int = 12,
        exclude_outliers: bool = True,
        outlier_percentiles: tuple[float, float] = (1, 99),
    ) -> dict[str, float]:
        """Return the stored data (ignores parameters since data is pre-aggregated)."""
        return self._data.copy()


class CSVDataSource(DataSource):
    """Load baseline data from a transaction-level CSV file.

    Expected CSV columns:
        - date: Transaction date (parseable by pandas)
        - amount: Transaction amount (positive values)
        - category_type: One of 'income', 'spending', 'saving'

    Example CSV:
        date,amount,category_type
        2024-01-15,5000.00,income
        2024-01-20,1200.00,spending
        2024-01-25,500.00,saving

    Example usage:
        source = CSVDataSource("transactions.csv", months_back=12)
        sim = Simulation(source.get_baseline_cashflow())
    """

    def __init__(
        self,
        csv_path: str | Path,
        months_back: int = 12,
        date_column: str = "date",
        amount_column: str = "amount",
        category_type_column: str = "category_type",
    ):
        """Initialize CSV data source.

        Args:
            csv_path: Path to the CSV file
            months_back: Number of recent months to use for averages
            date_column: Name of the date column
            amount_column: Name of the amount column
            category_type_column: Name of the category type column
        """
        self.csv_path = Path(csv_path)
        self.months_back = months_back
        self.date_column = date_column
        self.amount_column = amount_column
        self.category_type_column = category_type_column

        if not self.csv_path.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_path}")

        self._df = pd.read_csv(self.csv_path)
        self._df[self.date_column] = pd.to_datetime(self._df[self.date_column])

    def get_monthly_averages(
        self,
        year: int | list[int] | None = None,
        months_back: int = 12,
        exclude_outliers: bool = True,
        outlier_percentiles: tuple[float, float] = (1, 99),
    ) -> dict[str, float]:
        """Calculate monthly averages from transaction data.

        Args:
            year: Specific year(s) to analyze (not yet supported, uses months_back)
            months_back: Number of months to analyze
            exclude_outliers: If True, exclude transactions outside percentile range
            outlier_percentiles: Tuple of (lower, upper) percentiles to keep

        Returns:
            Dict with 'income', 'spending', 'saving' monthly averages
        """
        # Note: year parameter not yet implemented for CSV, uses months_back
        months = months_back or self.months_back

        # Filter to recent months
        end_date = date.today()
        start_date = end_date - relativedelta(months=months - 1)
        start_date = start_date.replace(day=1)

        mask = (self._df[self.date_column].dt.date >= start_date) & (
            self._df[self.date_column].dt.date <= end_date
        )
        filtered_df = self._df[mask]

        # Calculate averages by category type
        monthly_averages: dict[str, float] = {}

        for category_type in ["income", "spending", "saving"]:
            type_mask = filtered_df[self.category_type_column] == category_type
            amounts = filtered_df.loc[type_mask, self.amount_column].abs().tolist()

            if not amounts:
                monthly_averages[category_type] = 0.0
                continue

            if exclude_outliers and len(amounts) > 10:
                lower_bound = pd.Series(amounts).quantile(outlier_percentiles[0] / 100)
                upper_bound = pd.Series(amounts).quantile(outlier_percentiles[1] / 100)
                filtered_amounts = [a for a in amounts if lower_bound <= a <= upper_bound]
                total_amount = sum(filtered_amounts) if filtered_amounts else sum(amounts)
            else:
                total_amount = sum(amounts)

            monthly_averages[category_type] = total_amount / months

        return monthly_averages

    def get_baseline_cashflow(self) -> dict[str, float]:
        """Get baseline monthly cash flow data for simulations.

        Returns:
            Dict suitable for Simulation initialization
        """
        return self.get_monthly_averages()

"""Data loader for FafyCat database."""

from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, func, or_
from sqlalchemy.orm import Session, sessionmaker

from simulations.data_sources import DataSource

# Optional FafyCat import - allows module to be imported without FafyCat installed
try:
    from src.fafycat.core.database import CategoryORM, TransactionORM

    FAFYCAT_AVAILABLE = True
except ImportError:
    FAFYCAT_AVAILABLE = False
    CategoryORM = None
    TransactionORM = None


class FafyCatDataLoader(DataSource):
    """Loads and processes data from FafyCat database for simulations."""

    def __init__(self, db_path: str = "data/fafycat_prod.db"):
        """Initialize data loader with database connection.

        Args:
            db_path: Path to SQLite database file

        Raises:
            ImportError: If FafyCat is not installed
            FileNotFoundError: If database file doesn't exist
        """
        if not FAFYCAT_AVAILABLE:
            raise ImportError(
                "FafyCatDataLoader requires FafyCat to be installed. "
                "Use DictDataSource or CSVDataSource instead for standalone usage."
            )

        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found: {db_path}")

        # Create database connection
        self.engine = create_engine(f"sqlite:///{self.db_path}", echo=False)
        self.SessionLocal = sessionmaker(bind=self.engine)

    def get_session(self) -> Session:
        """Get database session."""
        return self.SessionLocal()

    def get_monthly_averages(
        self,
        year: int | list[int] | None = None,
        months_back: int = 12,
        exclude_outliers: bool = True,
        outlier_percentiles: tuple = (1, 99),
    ) -> dict[str, float]:
        """Calculate monthly averages by category type from historical data.

        Args:
            year: Specific year(s) to analyze (int, list of ints, or None for recent months)
            months_back: Number of recent months to analyze if year is None
            exclude_outliers: If True, exclude transactions outside percentile range
            outlier_percentiles: Tuple of (lower, upper) percentiles to keep (e.g., (1, 99))

        Returns:
            Dict with 'income', 'spending', 'saving' monthly averages
        """
        with self.get_session() as session:
            # First, get all transactions for the time period
            base_query = (
                session.query(CategoryORM.type, TransactionORM.amount)
                .join(
                    CategoryORM,
                    CategoryORM.id == func.coalesce(TransactionORM.category_id, TransactionORM.predicted_category_id),
                )
                .filter(CategoryORM.is_active)
                .filter(or_(TransactionORM.category_id.is_not(None), TransactionORM.predicted_category_id.is_not(None)))
            )

            # Apply time filter
            if year:
                # Handle both single year and multiple years
                years = [year] if isinstance(year, int) else year

                # Create date ranges for all years
                year_conditions = []
                for y in years:
                    year_start = date(y, 1, 1)
                    year_end = date(y, 12, 31)
                    year_conditions.append(TransactionORM.date.between(year_start, year_end))

                # Combine all year conditions with OR
                base_query = base_query.filter(or_(*year_conditions))
                num_months = len(years) * 12
            else:
                # Use last N months - fix the date calculation
                from dateutil.relativedelta import relativedelta

                end_date = date.today()
                start_date = end_date - relativedelta(months=months_back - 1)
                start_date = start_date.replace(day=1)
                base_query = base_query.filter(TransactionORM.date.between(start_date, end_date))
                num_months = months_back

            # Get all transactions
            all_transactions = base_query.all()

            # Group by category type and optionally filter outliers
            totals = {category_type: [] for category_type in ["spending", "income", "saving"]}

            for transaction in all_transactions:
                category_type = transaction.type
                amount = abs(float(transaction.amount))  # Use absolute values
                totals[category_type].append(amount)

            # Calculate monthly averages, optionally excluding outliers
            monthly_averages = {}
            for category_type, amounts in totals.items():
                if not amounts:
                    monthly_averages[category_type] = 0.0
                    continue

                if exclude_outliers and len(amounts) > 10:  # Only filter if we have enough data
                    # Calculate percentiles
                    lower_bound = pd.Series(amounts).quantile(outlier_percentiles[0] / 100)
                    upper_bound = pd.Series(amounts).quantile(outlier_percentiles[1] / 100)

                    # Filter amounts within percentile range
                    filtered_amounts = [a for a in amounts if lower_bound <= a <= upper_bound]

                    total_amount = sum(filtered_amounts) if filtered_amounts else sum(amounts)
                else:
                    total_amount = sum(amounts)

                monthly_averages[category_type] = total_amount / num_months

            return monthly_averages

    def get_category_breakdown(self, year: int | None = None) -> pd.DataFrame:
        """Get detailed breakdown by category for analysis.

        Args:
            year: Year to analyze (if None, uses current year)

        Returns:
            DataFrame with category-level spending data
        """
        if year is None:
            year = date.today().year

        with self.get_session() as session:
            query = (
                session.query(
                    CategoryORM.name,
                    CategoryORM.type,
                    func.sum(TransactionORM.amount).label("total_amount"),
                    func.count(TransactionORM.id).label("transaction_count"),
                    func.avg(TransactionORM.amount).label("avg_amount"),
                )
                .join(
                    CategoryORM,
                    CategoryORM.id == func.coalesce(TransactionORM.category_id, TransactionORM.predicted_category_id),
                )
                .filter(CategoryORM.is_active)
                .filter(or_(TransactionORM.category_id.is_not(None), TransactionORM.predicted_category_id.is_not(None)))
                .filter(TransactionORM.date.between(date(year, 1, 1), date(year, 12, 31)))
                .group_by(CategoryORM.name, CategoryORM.type)
                .order_by(CategoryORM.type, func.sum(TransactionORM.amount).desc())
            )

            results = query.all()

            # Convert to DataFrame
            data = []
            for result in results:
                data.append(
                    {
                        "category": result.name,
                        "type": result.type,
                        "total_amount": abs(float(result.total_amount)),
                        "monthly_avg": abs(float(result.total_amount)) / 12,
                        "transaction_count": result.transaction_count,
                        "avg_per_transaction": abs(float(result.avg_amount)) if result.avg_amount else 0,
                    }
                )

            return pd.DataFrame(data)

    def get_baseline_cashflow(
        self, year: int | list[int] | None = None, months_back: int = 12, exclude_outliers: bool = True
    ) -> dict[str, float]:
        """Get baseline monthly cash flow data for simulations.

        Args:
            year: Year(s) to base calculations on (int, list of ints, or None for recent months)
            months_back: Months to look back if year not specified
            exclude_outliers: If True, exclude large one-off transactions

        Returns:
            Dict suitable for Simulation initialization
        """
        monthly_averages = self.get_monthly_averages(year, months_back, exclude_outliers=exclude_outliers)

        return {
            "income": monthly_averages.get("income", 0.0),
            "spending": monthly_averages.get("spending", 0.0),
            "saving": monthly_averages.get("saving", 0.0),
        }

    def get_transaction_summary(self, year: int | None = None) -> dict[str, any]:
        """Get summary statistics about transaction data.

        Args:
            year: Year to analyze (if None, uses current year)

        Returns:
            Dict with summary statistics
        """
        if year is None:
            year = date.today().year

        with self.get_session() as session:
            # Total transactions
            total_transactions = (
                session.query(func.count(TransactionORM.id))
                .filter(TransactionORM.date.between(date(year, 1, 1), date(year, 12, 31)))
                .scalar()
            )

            # Categorized transactions
            categorized = (
                session.query(func.count(TransactionORM.id))
                .filter(TransactionORM.date.between(date(year, 1, 1), date(year, 12, 31)))
                .filter(or_(TransactionORM.category_id.is_not(None), TransactionORM.predicted_category_id.is_not(None)))
                .scalar()
            )

            # Date range of data
            date_range = (
                session.query(
                    func.min(TransactionORM.date).label("min_date"), func.max(TransactionORM.date).label("max_date")
                )
                .filter(TransactionORM.date.between(date(year, 1, 1), date(year, 12, 31)))
                .first()
            )

            return {
                "year": year,
                "total_transactions": total_transactions or 0,
                "categorized_transactions": categorized or 0,
                "categorization_rate": (categorized / total_transactions * 100) if total_transactions > 0 else 0,
                "date_range": {"start": date_range.min_date, "end": date_range.max_date},
            }

    def export_data_for_analysis(self, filename: str, year: int | None = None) -> str:
        """Export transaction data to CSV for external analysis.

        Args:
            filename: Output CSV filename
            year: Year to export (if None, exports all data)

        Returns:
            Path to exported file
        """
        with self.get_session() as session:
            query = (
                session.query(
                    TransactionORM.date,
                    TransactionORM.name,
                    TransactionORM.purpose,
                    TransactionORM.amount,
                    CategoryORM.name.label("category"),
                    CategoryORM.type.label("category_type"),
                )
                .join(
                    CategoryORM,
                    CategoryORM.id == func.coalesce(TransactionORM.category_id, TransactionORM.predicted_category_id),
                )
                .filter(or_(TransactionORM.category_id.is_not(None), TransactionORM.predicted_category_id.is_not(None)))
            )

            if year:
                query = query.filter(TransactionORM.date.between(date(year, 1, 1), date(year, 12, 31)))

            query = query.order_by(TransactionORM.date.desc())
            results = query.all()

            # Convert to DataFrame and export
            data = []
            for result in results:
                data.append(
                    {
                        "date": result.date,
                        "description": f"{result.name} - {result.purpose}".rstrip(" -")
                        if result.purpose
                        else result.name,
                        "amount": result.amount,
                        "category": result.category,
                        "category_type": result.category_type,
                    }
                )

            df = pd.DataFrame(data)
            output_path = Path(filename)
            df.to_csv(output_path, index=False)

            return str(output_path)

    def get_weighted_baseline(self, year_weights: dict[int, float], exclude_outliers: bool = True) -> dict[str, float]:
        """Get weighted baseline from multiple years with custom weighting.

        Args:
            year_weights: Dict mapping year to weight (e.g., {2024: 0.5, 2023: 0.3, 2022: 0.2})
            exclude_outliers: If True, exclude large one-off transactions

        Returns:
            Dict with weighted baseline data suitable for Simulation initialization
        """
        if not year_weights:
            raise ValueError("year_weights cannot be empty")

        # Normalize weights to sum to 1
        total_weight = sum(year_weights.values())
        if total_weight == 0:
            raise ValueError("Total weight cannot be zero")

        normalized_weights = {year: weight / total_weight for year, weight in year_weights.items()}

        # Get data for each year
        year_data = {}
        for year in normalized_weights:
            try:
                year_data[year] = self.get_monthly_averages(year, exclude_outliers=exclude_outliers)
            except Exception:
                continue

        if not year_data:
            raise ValueError("No valid data found for any specified years")

        # Calculate weighted averages
        weighted_baseline = {"income": 0.0, "spending": 0.0, "saving": 0.0}

        for year, data in year_data.items():
            weight = normalized_weights[year]
            for category in weighted_baseline:
                weighted_baseline[category] += data.get(category, 0.0) * weight

        return weighted_baseline

    def compare_baselines(self, years: list[int], exclude_outliers: bool = True) -> pd.DataFrame:
        """Compare baseline data across multiple years.

        Args:
            years: List of years to compare
            exclude_outliers: If True, exclude large one-off transactions

        Returns:
            DataFrame with comparison data
        """
        comparison_data = []

        for year in years:
            try:
                baseline = self.get_baseline_cashflow(year, exclude_outliers=exclude_outliers)
                comparison_data.append(
                    {
                        "year": year,
                        "income": baseline["income"],
                        "spending": baseline["spending"],
                        "saving": baseline["saving"],
                        "net_surplus": baseline["income"] - baseline["spending"] - baseline["saving"],
                    }
                )
            except Exception:
                continue

        return pd.DataFrame(comparison_data)

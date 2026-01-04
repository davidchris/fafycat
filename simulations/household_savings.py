"""Household savings account integration for simulations."""

from datetime import date
from pathlib import Path

import pandas as pd
from dateutil.relativedelta import relativedelta


class HouseholdSavingsLoader:
    """Load and analyze household savings account data from CSV."""

    def __init__(self, csv_path: str | Path, current_balance: float = 0.0, months_back: int = 6):
        """Initialize with CSV file path and current balance.

        Args:
            csv_path: Path to household savings CSV file
            current_balance: Current account balance as of today
            months_back: Number of recent months to use for calculating averages
        """
        self.csv_path = Path(csv_path)
        self.current_balance = current_balance
        self.months_back = months_back
        self.df: pd.DataFrame = pd.DataFrame()
        self._load_data()

    def _load_data(self):
        """Load and parse CSV data."""
        self.df = pd.read_csv(self.csv_path)
        self.df['Date'] = pd.to_datetime(self.df['Date'], format='%d.%m.%Y')
        self.df['Amount'] = self.df['Amount'].astype(float)

    def get_current_balance(self) -> float:
        """Get current household savings balance."""
        return self.current_balance

    def get_etf_portfolio_value(self) -> float:
        """Calculate current ETF portfolio value from transactions."""
        etf_purchases = self.df[
            self.df['Purpose'].str.contains('Wertpapierkauf', na=False, case=False)
        ]
        etf_sales = self.df[
            self.df['Purpose'].str.contains('Verkauf', na=False, case=False)
        ]

        # ETF purchases are negative (money out), sales are positive (money in)
        net_invested = abs(etf_purchases['Amount'].sum()) - etf_sales['Amount'].sum()
        return net_invested

    def get_monthly_savings_rate(self, exclude_large_transactions: bool = True) -> float:
        """Calculate average monthly household savings rate.

        Args:
            exclude_large_transactions: If True, exclude large one-off transactions
                (e.g., house purchase, property tax) from calculation

        Returns:
            Average monthly net savings rate
        """
        df_analysis = self.df.copy()

        if exclude_large_transactions:
            # Exclude large one-off transactions (house purchase, property tax, etc.)
            large_transactions = df_analysis[
                df_analysis['Purpose'].str.contains(
                    'Immobilienkauf|Grunderwerbssteuer|Hauskauf', na=False, case=False
                )
            ]
            df_analysis = df_analysis[~df_analysis.index.isin(large_transactions.index)]

        # Use recent data based on months_back parameter
        cutoff_date = date.today() - relativedelta(months=self.months_back)
        recent_data = df_analysis[df_analysis['Date'] >= pd.Timestamp(cutoff_date)]

        # Exclude ETF internal transfers (sparplan deposits)
        sparplan_deposits = recent_data[
            recent_data['Purpose'].str.contains('Sparplan', na=False, case=False)
        ]
        etf_purchases = recent_data[
            recent_data['Purpose'].str.contains('Wertpapierkauf', na=False, case=False)
        ]

        # Real savings excluding ETF transactions
        real_savings = recent_data[
            ~recent_data.index.isin(sparplan_deposits.index) &
            ~recent_data.index.isin(etf_purchases.index)
        ]

        if len(real_savings) == 0:
            return 0.0

        # Calculate monthly average
        date_range_months = (
            real_savings['Date'].max() - real_savings['Date'].min()
        ).days / 30.44

        if date_range_months <= 0:
            return 0.0

        total_net_savings = real_savings['Amount'].sum()
        return total_net_savings / date_range_months

    def get_etf_monthly_investment(self) -> float:
        """Get regular monthly ETF investment amount.

        Returns the most recent sparplan amount, as these can change over time.
        """
        sparplan_data = self.df[
            self.df['Purpose'].str.contains('Sparplan', na=False, case=False)
        ]

        if len(sparplan_data) == 0:
            return 0.0

        # Get the most recent sparplan transaction (they may change over time)
        sparplan_data = sparplan_data.sort_values('Date', ascending=False)
        return sparplan_data['Amount'].iloc[0]

    def get_transaction_summary(self) -> dict:
        """Get summary statistics about household savings."""
        total_deposits = self.df[self.df['Amount'] > 0]['Amount'].sum()
        total_withdrawals = self.df[self.df['Amount'] < 0]['Amount'].sum()

        # Major transactions
        major_withdrawals = self.df[self.df['Amount'] < -5000].sort_values('Amount')
        major_deposits = self.df[self.df['Amount'] > 5000].sort_values('Amount', ascending=False)

        return {
            'current_balance': self.current_balance,
            'total_deposits': total_deposits,
            'total_withdrawals': total_withdrawals,
            'net_change': total_deposits + total_withdrawals,
            'date_range': {
                'start': self.df['Date'].min().date(),
                'end': self.df['Date'].max().date()
            },
            'major_withdrawals': len(major_withdrawals),
            'major_deposits': len(major_deposits),
            'etf_portfolio_value': self.get_etf_portfolio_value(),
            'monthly_savings_rate': self.get_monthly_savings_rate(),
            'monthly_etf_investment': self.get_etf_monthly_investment()
        }

    def project_balance(self, months: int, additional_monthly_flow: float = 0) -> float:
        """Project household savings balance forward.

        Args:
            months: Number of months to project
            additional_monthly_flow: Additional monthly cash flow (e.g., reduced spending)

        Returns:
            Projected balance after specified months
        """
        monthly_rate = self.get_monthly_savings_rate()
        etf_monthly = self.get_etf_monthly_investment()

        # Total monthly net flow into savings
        total_monthly_flow = monthly_rate + additional_monthly_flow - etf_monthly

        return self.current_balance + (total_monthly_flow * months)

    def get_liquidation_requirement(self, deficit: float) -> dict:
        """Calculate ETF liquidation needed to cover a deficit.

        Args:
            deficit: Amount of money needed

        Returns:
            Dict with liquidation analysis
        """
        etf_value = self.get_etf_portfolio_value()

        if deficit <= 0:
            return {
                'liquidation_needed': False,
                'amount_to_liquidate': 0,
                'remaining_etf_value': etf_value,
                'feasible': True
            }

        if deficit > etf_value:
            return {
                'liquidation_needed': True,
                'amount_to_liquidate': deficit,
                'remaining_etf_value': 0,
                'feasible': False,
                'shortfall': deficit - etf_value
            }

        return {
            'liquidation_needed': True,
            'amount_to_liquidate': deficit,
            'remaining_etf_value': etf_value - deficit,
            'feasible': True,
            'etf_percentage_liquidated': (deficit / etf_value) * 100
        }

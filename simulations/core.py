"""Core simulation framework classes."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import pandas as pd


@dataclass
class SimulationResult:
    """Holds simulation results with visualization capabilities."""

    monthly_data: pd.DataFrame
    summary: dict[str, Any]
    scenario_name: str
    parameters: dict[str, Any] = field(default_factory=dict)

    def plot_cashflow(self, figsize=(12, 8)):
        """Plot monthly cash flow over time."""
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            return

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=figsize)

        # Monthly cash flow
        ax1.plot(
            self.monthly_data.index, self.monthly_data["net_cashflow"], marker="o", linewidth=2, label="Net Cash Flow"
        )
        ax1.axhline(y=0, color="red", linestyle="--", alpha=0.5)
        ax1.set_title(f"{self.scenario_name} - Monthly Cash Flow")
        ax1.set_ylabel("EUR")
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # Cumulative savings
        ax2.plot(
            self.monthly_data.index,
            self.monthly_data["cumulative_savings"],
            color="green",
            marker="s",
            linewidth=2,
            label="Cumulative Savings",
        )
        ax2.axhline(y=0, color="red", linestyle="--", alpha=0.5)
        ax2.set_title("Cumulative Savings/Runway")
        ax2.set_ylabel("EUR")
        ax2.set_xlabel("Month")
        ax2.legend()
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        return fig

    def get_runway_months(self, use_total_liquid: bool = True) -> int | None:
        """Calculate how many months until savings run out.

        Args:
            use_total_liquid: If True, use total_liquid column (includes household).
                             If False, use cumulative_savings (personal only).
        """
        if use_total_liquid and "total_liquid" in self.monthly_data.columns:
            column = "total_liquid"
        else:
            column = "cumulative_savings"
        negative_months = self.monthly_data[self.monthly_data[column] < 0]
        if len(negative_months) == 0:
            return None  # Never runs out
        return negative_months.index[0]


class Scenario(ABC):
    """Abstract base class for financial scenarios."""

    def __init__(self, name: str):
        self.name = name
        self.parameters = {}

    @abstractmethod
    def apply_adjustments(self, baseline_data: dict[str, float], month_number: int = 1) -> dict[str, float]:
        """Apply scenario-specific adjustments to baseline monthly data.

        Args:
            baseline_data: Dict with keys like 'income', 'spending', 'saving'
            month_number: Current month in simulation (1-based)

        Returns:
            Dict with adjusted monthly amounts
        """
        pass

    def get_parameters(self) -> dict[str, Any]:
        """Return scenario parameters for documentation."""
        return self.parameters.copy()


class Simulation:
    """Main simulation engine."""

    def __init__(
        self,
        baseline_data: dict[str, float],
        initial_savings: float = 0.0,
        household_savings: float = 0.0,
        household_monthly_contribution: float = 0.0,
    ):
        """Initialize simulation with baseline monthly data.

        Args:
            baseline_data: Monthly averages by category (income, spending, saving)
            initial_savings: Starting personal savings/cash amount
            household_savings: Starting household savings balance
            household_monthly_contribution: Monthly household savings contribution
        """
        self.baseline_data = baseline_data.copy()
        self.initial_savings = initial_savings
        self.household_savings = household_savings
        self.household_monthly_contribution = household_monthly_contribution

    def run(self, scenario: Scenario, months: int = 12, start_date: date | None = None) -> SimulationResult:
        """Run simulation for given scenario and time period.

        Args:
            scenario: Scenario to simulate
            months: Number of months to simulate
            start_date: Starting date (defaults to next month)

        Returns:
            SimulationResult with monthly projections
        """
        if start_date is None:
            start_date = date.today().replace(day=1) + timedelta(days=32)
            start_date = start_date.replace(day=1)  # First of next month

        # Generate month dates
        month_dates = []
        current_date = start_date
        for _ in range(months):
            month_dates.append(current_date)
            # Move to next month
            if current_date.month == 12:
                current_date = current_date.replace(year=current_date.year + 1, month=1)
            else:
                current_date = current_date.replace(month=current_date.month + 1)

        # Run monthly simulation
        monthly_results = []
        cumulative_savings = self.initial_savings
        household_balance = self.household_savings

        for month_date in month_dates:
            month_num = month_dates.index(month_date) + 1

            # Get scenario-adjusted amounts for this month
            adjusted_data = scenario.apply_adjustments(self.baseline_data, month_num)

            # Calculate net cash flow
            monthly_income = adjusted_data.get("income", 0)
            monthly_spending = adjusted_data.get("spending", 0)
            monthly_saving = adjusted_data.get("saving", 0)
            net_cashflow = monthly_income - monthly_spending

            # Update personal savings
            cumulative_savings += net_cashflow

            # Update household savings (independent of personal cash flow)
            household_balance += self.household_monthly_contribution

            # Calculate combined liquid position
            total_liquid = cumulative_savings + household_balance

            monthly_results.append(
                {
                    "month": month_num,
                    "date": month_date,
                    "income": monthly_income,
                    "spending": monthly_spending,
                    "saving": monthly_saving,
                    "net_cashflow": net_cashflow,
                    "household_contribution": self.household_monthly_contribution,
                    "household_balance": household_balance,
                    "total_liquid": total_liquid,
                    "cumulative_savings": cumulative_savings,
                }
            )

        # Convert to DataFrame
        df = pd.DataFrame(monthly_results)
        df.set_index("month", inplace=True)

        # Calculate summary statistics
        summary = {
            "total_months": months,
            "final_savings": cumulative_savings,
            "final_household_balance": household_balance,
            "final_total_liquid": cumulative_savings + household_balance,
            "avg_monthly_cashflow": df["net_cashflow"].mean(),
            "min_savings": df["cumulative_savings"].min(),
            "min_total_liquid": df["total_liquid"].min(),
            "scenario_name": scenario.name,
        }

        return SimulationResult(
            monthly_data=df, summary=summary, scenario_name=scenario.name, parameters=scenario.get_parameters()
        )

    def calculate_required_runway(
        self, scenario: Scenario, months: int = 24, safety_margin: float = 1.5
    ) -> dict[str, float]:
        """Calculate required emergency fund for scenario.

        Args:
            scenario: Scenario to analyze
            months: Months to simulate for runway calculation
            safety_margin: Multiply required amount by this factor

        Returns:
            Dict with runway analysis
        """
        result = self.run(scenario, months)
        min_savings = result.monthly_data["cumulative_savings"].min()

        # If savings never go negative, no emergency fund needed
        required_emergency_fund = 0.0 if min_savings >= 0 else abs(min_savings) * safety_margin

        return {
            "required_emergency_fund": required_emergency_fund,
            "safety_margin": safety_margin,
            "min_savings_point": min_savings,
            "runway_months": result.get_runway_months(),
            "recommended_total_savings": self.initial_savings + required_emergency_fund,
        }

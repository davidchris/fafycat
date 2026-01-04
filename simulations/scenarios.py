"""Financial scenario implementations."""

from typing import Any

from .core import Scenario


class ParentalLeaveScenario(Scenario):
    """Scenario for parental leave with configurable parameters."""

    def __init__(
        self,
        months_without_salary: int = 3,
        salary_replacement_rate: float = 0.0,  # 0.0 = no replacement, 0.67 = 67% replacement
        inflation_rate: float = 0.03,
        kindergeld_increase: float = 250.0,  # Monthly increase for second child
        start_month: int = 1,  # Which month parental leave starts
        reduced_spending_categories: dict[str, float] | None = None,  # Category-specific spending reductions
        elterngeld_cap: float = 1800.0,  # Maximum Elterngeld per month (German law)
        name: str | None = None,  # Custom scenario name for plots
    ):
        """Initialize parental leave scenario.

        Args:
            months_without_salary: Number of months with reduced/no salary
            salary_replacement_rate: Fraction of salary replaced (e.g., 0.67 for German Elterngeld)
            inflation_rate: Annual inflation rate to apply
            kindergeld_increase: Monthly increase in child benefits
            start_month: Month when parental leave begins (1-based)
            reduced_spending_categories: Optional dict of spending reductions during leave
            elterngeld_cap: Maximum Elterngeld per month (€1,800 by German law as of 2024)
            name: Custom scenario name for distinguishing in plots and reports
        """
        # Generate descriptive name if not provided
        if name is None:
            if salary_replacement_rate > 0:
                replacement_desc = f"{salary_replacement_rate*100:.0f}% replacement"
            else:
                replacement_desc = "no benefits"
            name = f"{months_without_salary}-Month Leave ({replacement_desc})"

        super().__init__(name)

        self.months_without_salary = months_without_salary
        self.salary_replacement_rate = salary_replacement_rate
        self.inflation_rate = inflation_rate
        self.kindergeld_increase = kindergeld_increase
        self.start_month = start_month
        self.reduced_spending = reduced_spending_categories or {}
        self.elterngeld_cap = elterngeld_cap

        # Store parameters for documentation
        self.parameters = {
            'months_without_salary': months_without_salary,
            'salary_replacement_rate': salary_replacement_rate,
            'inflation_rate': inflation_rate,
            'kindergeld_increase': kindergeld_increase,
            'start_month': start_month,
            'reduced_spending': self.reduced_spending,
            'elterngeld_cap': elterngeld_cap,
            'name': self.name
        }

    def apply_adjustments(self, baseline_data: dict[str, float], month_number: int = 1) -> dict[str, float]:
        """Apply parental leave adjustments to baseline data."""
        adjusted = baseline_data.copy()

        # Apply inflation to all amounts (monthly rate)
        monthly_inflation = (1 + self.inflation_rate) ** (1/12) - 1
        for key in adjusted:
            adjusted[key] *= (1 + monthly_inflation)

        # Apply parental leave adjustments during the specified months
        if self.start_month <= month_number < self.start_month + self.months_without_salary:
            # Calculate Elterngeld (67% of salary, capped at €1,800/month)
            elterngeld = min(adjusted['income'] * self.salary_replacement_rate, self.elterngeld_cap)
            adjusted['income'] = elterngeld
            # Add child benefits increase
            adjusted['income'] += self.kindergeld_increase

            # Apply any spending reductions during parental leave
            if self.reduced_spending:
                for category, reduction_factor in self.reduced_spending.items():
                    if category in adjusted:
                        adjusted[category] *= (1 - reduction_factor)

        elif month_number >= self.start_month:
            # After parental leave - still get increased child benefits
            adjusted['income'] += self.kindergeld_increase

        return adjusted


class InflationOnlyScenario(Scenario):
    """Simple scenario that only applies inflation adjustments."""

    def __init__(self, annual_inflation_rate: float = 0.03):
        """Initialize inflation-only scenario.

        Args:
            annual_inflation_rate: Annual inflation rate (e.g., 0.03 for 3%)
        """
        super().__init__("Inflation Only")
        self.annual_inflation_rate = annual_inflation_rate
        self.parameters = {'annual_inflation_rate': annual_inflation_rate}

    def apply_adjustments(self, baseline_data: dict[str, float], month_number: int = 1) -> dict[str, float]:
        """Apply inflation to all baseline amounts."""
        monthly_inflation = (1 + self.annual_inflation_rate) ** (1/12) - 1
        return {
            key: value * (1 + monthly_inflation)
            for key, value in baseline_data.items()
        }


class IncomeChangeScenario(Scenario):
    """Scenario for general income changes (job loss, promotion, etc.)."""

    def __init__(
        self,
        income_change_percent: float,
        start_month: int = 1,
        duration_months: int = 12,
        name: str | None = None,
    ):
        """Initialize income change scenario.

        Args:
            income_change_percent: Percentage change in income (e.g., -1.0 = 100% loss, 0.2 = 20% increase)
            start_month: Month when change takes effect
            duration_months: How long the change lasts (None for permanent)
            name: Custom scenario name
        """
        if name is None:
            change_desc = "increase" if income_change_percent > 0 else "decrease"
            name = f"Income {change_desc} ({income_change_percent*100:.0f}%)"

        super().__init__(name)

        self.income_change_percent = income_change_percent
        self.start_month = start_month
        self.duration_months = duration_months

        self.parameters = {
            'income_change_percent': income_change_percent,
            'start_month': start_month,
            'duration_months': duration_months
        }

    def apply_adjustments(self, baseline_data: dict[str, float], month_number: int = 1) -> dict[str, float]:
        """Apply income change during specified period."""
        adjusted = baseline_data.copy()

        # Apply income change during specified period
        change_end = self.start_month + self.duration_months
        if self.start_month <= month_number < change_end:
            adjusted['income'] *= (1 + self.income_change_percent)

        return adjusted


class SpendingReductionScenario(Scenario):
    """Scenario for reducing spending by category or overall."""

    def __init__(
        self,
        spending_reduction_percent: float,
        category_reductions: dict[str, float] | None = None,
        name: str | None = None,
    ):
        """Initialize spending reduction scenario.

        Args:
            spending_reduction_percent: Overall spending reduction (e.g., 0.2 for 20% reduction)
            category_reductions: Optional dict of category-specific reductions
            name: Custom scenario name
        """
        if name is None:
            name = f"Spending Reduction ({spending_reduction_percent*100:.0f}%)"

        super().__init__(name)

        self.spending_reduction_percent = spending_reduction_percent
        self.category_reductions = category_reductions or {}

        self.parameters = {
            'spending_reduction_percent': spending_reduction_percent,
            'category_reductions': self.category_reductions
        }

    def apply_adjustments(self, baseline_data: dict[str, float], month_number: int = 1) -> dict[str, float]:
        """Apply spending reductions."""
        adjusted = baseline_data.copy()

        # Apply overall spending reduction
        if 'spending' in adjusted:
            adjusted['spending'] *= (1 - self.spending_reduction_percent)

        # Apply category-specific reductions
        for category, reduction_percent in self.category_reductions.items():
            if category in adjusted:
                adjusted[category] *= (1 - reduction_percent)

        return adjusted


class CustomScenario(Scenario):
    """Flexible scenario that accepts a custom adjustment function."""

    def __init__(self, adjustment_function, name: str = "Custom", parameters: dict[str, Any] | None = None):
        """Initialize custom scenario.

        Args:
            adjustment_function: Function that takes baseline_data and returns adjusted data
            name: Scenario name
            parameters: Parameters dict for documentation
        """
        super().__init__(name)
        self.adjustment_function = adjustment_function
        self.parameters = parameters or {}

    def apply_adjustments(self, baseline_data: dict[str, float], month_number: int = 1) -> dict[str, float]:
        """Apply custom adjustment function."""
        # For backwards compatibility, check if function accepts month_number
        import inspect
        sig = inspect.signature(self.adjustment_function)
        if 'month_number' in sig.parameters:
            return self.adjustment_function(baseline_data, month_number)
        return self.adjustment_function(baseline_data)


# Convenience functions for common scenarios

def create_job_loss_scenario(months: int = 6, unemployment_benefit_rate: float = 0.6) -> ParentalLeaveScenario:
    """Create a job loss scenario with unemployment benefits.

    Args:
        months: Months without job
        unemployment_benefit_rate: Fraction of income replaced by benefits

    Returns:
        ParentalLeaveScenario configured for job loss
    """
    scenario = ParentalLeaveScenario(
        months_without_salary=months,
        salary_replacement_rate=unemployment_benefit_rate,
        kindergeld_increase=0.0  # No child benefit increase for job loss
    )
    scenario.name = f"Job Loss ({months} months)"
    return scenario


def create_sabbatical_scenario(months: int = 6, savings_increase: float = 0.0) -> IncomeChangeScenario:
    """Create a sabbatical scenario.

    Args:
        months: Months of sabbatical
        savings_increase: Optional increase in savings during sabbatical

    Returns:
        IncomeChangeScenario configured for sabbatical
    """
    return IncomeChangeScenario(
        income_change_percent=-1.0,  # No income
        duration_months=months,
        name=f"Sabbatical ({months} months)"
    )

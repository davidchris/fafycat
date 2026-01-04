"""Tests for simulations/scenarios.py"""

import pytest

from simulations.scenarios import (
    CustomScenario,
    IncomeChangeScenario,
    InflationOnlyScenario,
    ParentalLeaveScenario,
    SpendingReductionScenario,
    create_job_loss_scenario,
    create_sabbatical_scenario,
)


class TestParentalLeaveScenario:
    """Tests for ParentalLeaveScenario."""

    @pytest.fixture
    def baseline(self):
        """Standard baseline data."""
        return {"income": 5000.0, "spending": 3000.0, "saving": 500.0}

    def test_no_income_during_leave(self, baseline):
        """Income drops during parental leave months (no benefits)."""
        scenario = ParentalLeaveScenario(
            months_without_salary=3,
            salary_replacement_rate=0.0,
            inflation_rate=0.0,
            kindergeld_increase=0.0,
            start_month=1,
        )

        # During leave (month 1)
        adjusted = scenario.apply_adjustments(baseline, month_number=1)
        assert adjusted["income"] == 0.0

        # After leave (month 4)
        adjusted_after = scenario.apply_adjustments(baseline, month_number=4)
        assert adjusted_after["income"] == baseline["income"]

    def test_elterngeld_cap(self, baseline):
        """Elterngeld is capped at maximum (€1,800 by default)."""
        scenario = ParentalLeaveScenario(
            months_without_salary=3,
            salary_replacement_rate=0.67,  # 67% of 5000 = 3350, should be capped
            inflation_rate=0.0,
            kindergeld_increase=0.0,
            elterngeld_cap=1800.0,
        )

        adjusted = scenario.apply_adjustments(baseline, month_number=1)
        assert adjusted["income"] == 1800.0  # Capped at 1800

    def test_elterngeld_below_cap(self, baseline):
        """Elterngeld below cap is not modified."""
        low_income_baseline = {"income": 2000.0, "spending": 1500.0, "saving": 0.0}
        scenario = ParentalLeaveScenario(
            months_without_salary=3,
            salary_replacement_rate=0.67,  # 67% of 2000 = 1340, below cap
            inflation_rate=0.0,
            kindergeld_increase=0.0,
        )

        adjusted = scenario.apply_adjustments(low_income_baseline, month_number=1)
        assert adjusted["income"] == pytest.approx(1340.0)

    def test_kindergeld_during_leave(self, baseline):
        """Kindergeld is added during parental leave."""
        scenario = ParentalLeaveScenario(
            months_without_salary=3,
            salary_replacement_rate=0.0,
            inflation_rate=0.0,
            kindergeld_increase=250.0,
            start_month=1,
        )

        adjusted = scenario.apply_adjustments(baseline, month_number=2)
        assert adjusted["income"] == 250.0  # Only kindergeld

    def test_kindergeld_after_leave(self, baseline):
        """Kindergeld continues after leave ends."""
        scenario = ParentalLeaveScenario(
            months_without_salary=3,
            salary_replacement_rate=0.0,
            inflation_rate=0.0,
            kindergeld_increase=250.0,
            start_month=1,
        )

        adjusted = scenario.apply_adjustments(baseline, month_number=5)
        assert adjusted["income"] == 5250.0  # Original income + kindergeld

    def test_inflation_applied(self, baseline):
        """Inflation is applied to all amounts."""
        scenario = ParentalLeaveScenario(
            months_without_salary=0,  # No leave, just inflation
            inflation_rate=0.12,  # 12% annual = ~0.95% monthly
            kindergeld_increase=0.0,
        )

        adjusted = scenario.apply_adjustments(baseline, month_number=1)
        # Monthly inflation factor should increase values slightly
        assert adjusted["income"] > baseline["income"]
        assert adjusted["spending"] > baseline["spending"]

    def test_auto_generated_name(self):
        """Auto-generates descriptive name."""
        scenario1 = ParentalLeaveScenario(months_without_salary=3, salary_replacement_rate=0.0)
        assert "no benefits" in scenario1.name.lower()

        scenario2 = ParentalLeaveScenario(months_without_salary=3, salary_replacement_rate=0.67)
        assert "67%" in scenario2.name

    def test_custom_name(self):
        """Custom name is used when provided."""
        scenario = ParentalLeaveScenario(months_without_salary=3, name="My Custom Scenario")
        assert scenario.name == "My Custom Scenario"


class TestInflationOnlyScenario:
    """Tests for InflationOnlyScenario."""

    def test_inflation_applied(self):
        """Inflation increases all amounts."""
        baseline = {"income": 1000.0, "spending": 500.0}
        scenario = InflationOnlyScenario(annual_inflation_rate=0.12)

        adjusted = scenario.apply_adjustments(baseline, month_number=1)

        # With 12% annual inflation, monthly factor is (1.12)^(1/12) - 1 ≈ 0.95%
        assert adjusted["income"] > 1000.0
        assert adjusted["spending"] > 500.0

    def test_zero_inflation(self):
        """Zero inflation leaves values unchanged."""
        baseline = {"income": 1000.0, "spending": 500.0}
        scenario = InflationOnlyScenario(annual_inflation_rate=0.0)

        adjusted = scenario.apply_adjustments(baseline, month_number=1)

        assert adjusted["income"] == 1000.0
        assert adjusted["spending"] == 500.0


class TestIncomeChangeScenario:
    """Tests for IncomeChangeScenario."""

    def test_income_decrease(self):
        """Income decrease is applied correctly."""
        baseline = {"income": 5000.0, "spending": 3000.0}
        scenario = IncomeChangeScenario(
            income_change_percent=-0.5,  # 50% decrease
            start_month=1,
            duration_months=3,
        )

        # During change period
        adjusted = scenario.apply_adjustments(baseline, month_number=2)
        assert adjusted["income"] == 2500.0

        # After change period
        adjusted_after = scenario.apply_adjustments(baseline, month_number=5)
        assert adjusted_after["income"] == 5000.0

    def test_income_increase(self):
        """Income increase (promotion) is applied correctly."""
        baseline = {"income": 5000.0, "spending": 3000.0}
        scenario = IncomeChangeScenario(
            income_change_percent=0.2,  # 20% increase
            start_month=1,
            duration_months=12,
        )

        adjusted = scenario.apply_adjustments(baseline, month_number=1)
        assert adjusted["income"] == 6000.0

    def test_complete_job_loss(self):
        """100% income loss (job loss)."""
        baseline = {"income": 5000.0, "spending": 3000.0}
        scenario = IncomeChangeScenario(
            income_change_percent=-1.0,  # 100% loss
            start_month=1,
            duration_months=6,
        )

        adjusted = scenario.apply_adjustments(baseline, month_number=1)
        assert adjusted["income"] == 0.0


class TestSpendingReductionScenario:
    """Tests for SpendingReductionScenario."""

    def test_overall_reduction(self):
        """Overall spending reduction is applied."""
        baseline = {"income": 5000.0, "spending": 3000.0}
        scenario = SpendingReductionScenario(spending_reduction_percent=0.2)

        adjusted = scenario.apply_adjustments(baseline, month_number=1)
        assert adjusted["spending"] == 2400.0  # 20% reduction

    def test_category_specific_reduction(self):
        """Category-specific reductions are applied."""
        baseline = {"income": 5000.0, "spending": 3000.0, "entertainment": 500.0}
        scenario = SpendingReductionScenario(
            spending_reduction_percent=0.0,
            category_reductions={"entertainment": 0.5},
        )

        adjusted = scenario.apply_adjustments(baseline, month_number=1)
        assert adjusted["entertainment"] == 250.0  # 50% reduction on entertainment only
        assert adjusted["spending"] == 3000.0  # Unchanged


class TestCustomScenario:
    """Tests for CustomScenario."""

    def test_custom_function(self):
        """Custom adjustment function is called."""

        def double_income(baseline):
            result = baseline.copy()
            result["income"] *= 2
            return result

        baseline = {"income": 1000.0, "spending": 500.0}
        scenario = CustomScenario(double_income, name="Double Income")

        adjusted = scenario.apply_adjustments(baseline, month_number=1)
        assert adjusted["income"] == 2000.0

    def test_custom_function_with_month(self):
        """Custom function can accept month_number parameter."""

        def income_by_month(baseline, month_number):
            result = baseline.copy()
            result["income"] = baseline["income"] * month_number
            return result

        baseline = {"income": 1000.0}
        scenario = CustomScenario(income_by_month, name="Income By Month")

        assert scenario.apply_adjustments(baseline, month_number=3)["income"] == 3000.0


class TestConvenienceFunctions:
    """Tests for convenience scenario factories."""

    def test_create_job_loss_scenario(self):
        """Job loss scenario is created correctly."""
        scenario = create_job_loss_scenario(months=6, unemployment_benefit_rate=0.6)

        baseline = {"income": 5000.0, "spending": 3000.0}
        adjusted = scenario.apply_adjustments(baseline, month_number=1)

        # 60% unemployment benefits, capped at 1800
        assert adjusted["income"] == pytest.approx(1800.0)  # Capped
        assert "Job Loss" in scenario.name

    def test_create_sabbatical_scenario(self):
        """Sabbatical scenario is created correctly."""
        scenario = create_sabbatical_scenario(months=6)

        baseline = {"income": 5000.0, "spending": 3000.0}
        adjusted = scenario.apply_adjustments(baseline, month_number=1)

        assert adjusted["income"] == 0.0  # No income during sabbatical
        assert "Sabbatical" in scenario.name

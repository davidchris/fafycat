"""Tests for simulations/core.py"""

from datetime import date

import pandas as pd
import pytest

from simulations import Simulation, SimulationResult
from simulations.scenarios import InflationOnlyScenario, ParentalLeaveScenario


class TestSimulationResult:
    """Tests for SimulationResult class."""

    def test_get_runway_months_never_negative(self):
        """Runway returns None when savings never go negative."""
        # Create result with positive cumulative savings throughout
        df = pd.DataFrame({
            'cumulative_savings': [1000, 2000, 3000, 4000],
            'total_liquid': [1500, 2500, 3500, 4500],
        })
        df.index = range(1, 5)
        df.index.name = 'month'

        result = SimulationResult(
            monthly_data=df,
            summary={'final_savings': 4000},
            scenario_name='Test',
        )

        assert result.get_runway_months() is None

    def test_get_runway_months_finds_first_negative(self):
        """Runway returns first month where savings < 0."""
        df = pd.DataFrame({
            'cumulative_savings': [1000, 500, -100, -500],
            'total_liquid': [1500, 1000, -50, -400],  # Also goes negative
        })
        df.index = range(1, 5)
        df.index.name = 'month'

        result = SimulationResult(
            monthly_data=df,
            summary={'final_savings': -500},
            scenario_name='Test',
        )

        # Uses total_liquid by default, which goes negative at month 3
        assert result.get_runway_months() == 3

    def test_get_runway_months_uses_total_liquid_by_default(self):
        """By default, uses total_liquid column."""
        df = pd.DataFrame({
            'cumulative_savings': [-100, -200, -300],
            'total_liquid': [1000, 500, -50],
        })
        df.index = range(1, 4)
        df.index.name = 'month'

        result = SimulationResult(
            monthly_data=df,
            summary={},
            scenario_name='Test',
        )

        # Should find negative in total_liquid at month 3, not cumulative_savings at month 1
        assert result.get_runway_months(use_total_liquid=True) == 3
        assert result.get_runway_months(use_total_liquid=False) == 1


class TestSimulation:
    """Tests for Simulation class."""

    @pytest.fixture
    def baseline_data(self):
        """Standard baseline data for tests."""
        return {
            'income': 5000.0,
            'spending': 3500.0,
            'saving': 500.0,
        }

    def test_run_basic(self, baseline_data):
        """Basic simulation runs correctly."""
        sim = Simulation(baseline_data)
        scenario = InflationOnlyScenario(annual_inflation_rate=0.0)
        result = sim.run(scenario, months=3)

        assert len(result.monthly_data) == 3
        assert result.scenario_name == 'Inflation Only'
        # Net cashflow should be income - spending = 1500
        assert result.monthly_data['net_cashflow'].iloc[0] == pytest.approx(1500.0)

    def test_run_with_initial_savings(self, baseline_data):
        """Initial savings are accounted for."""
        sim = Simulation(baseline_data, initial_savings=10000.0)
        scenario = InflationOnlyScenario(annual_inflation_rate=0.0)
        result = sim.run(scenario, months=1)

        # First month cumulative should be initial + net cashflow
        assert result.monthly_data['cumulative_savings'].iloc[0] == pytest.approx(11500.0)

    def test_run_with_household_savings(self, baseline_data):
        """Household savings and contributions are tracked."""
        sim = Simulation(
            baseline_data,
            initial_savings=5000.0,
            household_savings=10000.0,
            household_monthly_contribution=500.0,
        )
        scenario = InflationOnlyScenario(annual_inflation_rate=0.0)
        result = sim.run(scenario, months=2)

        # Household balance should grow by contribution each month
        assert result.monthly_data['household_balance'].iloc[0] == pytest.approx(10500.0)
        assert result.monthly_data['household_balance'].iloc[1] == pytest.approx(11000.0)

        # Total liquid should be cumulative savings + household balance
        assert 'total_liquid' in result.monthly_data.columns

    def test_run_with_custom_start_date(self, baseline_data):
        """Custom start date is respected."""
        sim = Simulation(baseline_data)
        scenario = InflationOnlyScenario(annual_inflation_rate=0.0)
        start = date(2025, 6, 1)
        result = sim.run(scenario, months=3, start_date=start)

        # Check dates in the data
        assert result.monthly_data['date'].iloc[0] == start
        assert result.monthly_data['date'].iloc[1] == date(2025, 7, 1)
        assert result.monthly_data['date'].iloc[2] == date(2025, 8, 1)

    def test_calculate_required_runway_no_emergency_fund_needed(self, baseline_data):
        """No emergency fund needed when savings never go negative."""
        sim = Simulation(baseline_data, initial_savings=50000.0)
        scenario = InflationOnlyScenario(annual_inflation_rate=0.0)

        runway = sim.calculate_required_runway(scenario, months=12)

        assert runway['required_emergency_fund'] == 0.0
        assert runway['runway_months'] is None

    def test_calculate_required_runway_with_deficit(self):
        """Emergency fund calculated correctly when savings go negative."""
        baseline = {'income': 0.0, 'spending': 1000.0, 'saving': 0.0}
        sim = Simulation(baseline, initial_savings=2000.0)
        scenario = InflationOnlyScenario(annual_inflation_rate=0.0)

        runway = sim.calculate_required_runway(scenario, months=6, safety_margin=1.5)

        # After 6 months: 2000 - 6*1000 = -4000 (min savings)
        # Required emergency fund = 4000 * 1.5 = 6000
        assert runway['required_emergency_fund'] == pytest.approx(6000.0)
        assert runway['safety_margin'] == 1.5
        # Runs out at month 3 (2000 - 3*1000 = -1000)
        assert runway['runway_months'] == 3

    def test_summary_statistics(self, baseline_data):
        """Summary statistics are calculated correctly."""
        sim = Simulation(baseline_data, initial_savings=10000.0)
        scenario = InflationOnlyScenario(annual_inflation_rate=0.0)
        result = sim.run(scenario, months=6)

        assert result.summary['total_months'] == 6
        assert result.summary['final_savings'] == pytest.approx(10000 + 6 * 1500)
        assert result.summary['avg_monthly_cashflow'] == pytest.approx(1500.0)
        assert 'min_savings' in result.summary
        assert 'scenario_name' in result.summary

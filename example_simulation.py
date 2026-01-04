#!/usr/bin/env python3
"""
Example script demonstrating the FafyCat financial simulation framework.

This script shows how to:
1. Load your historical financial data
2. Create different scenarios (parental leave, job loss, etc.)
3. Run simulations and analyze results
4. Calculate required emergency funds

Run with: uv run python example_simulation.py
"""

import sys
from pathlib import Path

# Add simulations to path
sys.path.append(str(Path(__file__).parent))

from simulations import FafyCatDataLoader, Simulation
from simulations.scenarios import (
    InflationOnlyScenario,
    ParentalLeaveScenario,
    create_job_loss_scenario,
)
from simulations.visualizations import compare_scenarios, quick_plot


def load_baseline_data() -> dict[str, float]:
    """Load baseline data from FafyCat or use defaults."""
    try:
        loader = FafyCatDataLoader("data/fafycat_prod.db")
        try:
            return loader.get_weighted_baseline({2024: 0.5, 2023: 0.3, 2022: 0.2})
        except Exception:
            return loader.get_baseline_cashflow(year=2024)
    except FileNotFoundError:
        return {'income': 4500.0, 'spending': 3200.0, 'saving': 800.0}


def create_scenarios() -> dict:
    """Create simulation scenarios."""
    return {
        "Baseline + Inflation": InflationOnlyScenario(annual_inflation_rate=0.03),
        "Parental Leave (3 months)": ParentalLeaveScenario(
            months_without_salary=3,
            salary_replacement_rate=0.0,
            inflation_rate=0.03,
            kindergeld_increase=250,
            start_month=6,
        ),
        "Parental Leave (6 months)": ParentalLeaveScenario(
            months_without_salary=6,
            salary_replacement_rate=0.0,
            inflation_rate=0.03,
            kindergeld_increase=250,
            start_month=6,
        ),
        "Job Loss (6 months)": create_job_loss_scenario(months=6, unemployment_benefit_rate=0.6),
    }


def run_simulations(baseline: dict, scenarios: dict, initial_savings: float, months: int) -> dict:
    """Run all scenarios and return results."""
    results = {}
    for name, scenario in scenarios.items():
        sim = Simulation(baseline, initial_savings=initial_savings)
        results[name] = sim.run(scenario, months=months)
    return results


def save_visualizations(results: dict, worst_case: tuple) -> None:
    """Save visualization files if matplotlib available."""
    try:
        import matplotlib.pyplot as plt

        fig = compare_scenarios(*results.values(), metric='cumulative_savings')
        fig.savefig('simulation_comparison.png', dpi=150, bbox_inches='tight')

        detailed_fig = quick_plot(worst_case[1], show_details=True)
        detailed_fig.savefig(
            f'detailed_{worst_case[0].lower().replace(" ", "_")}.png',
            dpi=150,
            bbox_inches='tight',
        )
        plt.close('all')
    except ImportError:
        pass


def main():
    """Run example financial simulations."""
    baseline = load_baseline_data()
    initial_savings = 15000.0
    simulation_months = 24

    scenarios = create_scenarios()
    results = run_simulations(baseline, scenarios, initial_savings, simulation_months)

    # Calculate emergency fund requirements for risk scenarios
    for name in results:
        if "Parental Leave" in name or "Job Loss" in name:
            sim = Simulation(baseline, initial_savings=0)
            sim.calculate_required_runway(scenarios[name], months=simulation_months)

    # Find worst case and save outputs
    worst_case = min(results.items(), key=lambda x: x[1].summary['final_savings'])
    save_visualizations(results, worst_case)

    import contextlib

    with contextlib.suppress(Exception):
        worst_case[1].monthly_data.to_csv('simulation_results.csv')



if __name__ == "__main__":
    main()

"""Visualization utilities for financial simulations."""


try:
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    plt = None
    # Create dummy Figure type for type hints when matplotlib not available
    Figure = type(None)

from .core import SimulationResult


class SimulationVisualizer:
    """Creates visualizations for simulation results."""

    def __init__(self, figsize: tuple[int, int] = (12, 8)):
        """Initialize visualizer.

        Args:
            figsize: Default figure size for plots
        """
        if not MATPLOTLIB_AVAILABLE:
            raise ImportError("matplotlib is required for visualizations. Install with 'uv add matplotlib'")

        self.figsize = figsize

    def plot_scenario_comparison(self, results: list[SimulationResult],
                                metric: str = 'cumulative_savings') -> Figure:
        """Compare multiple scenarios on a single plot.

        Args:
            results: List of SimulationResult objects to compare
            metric: Column name to plot ('cumulative_savings', 'net_cashflow', etc.)

        Returns:
            matplotlib Figure object
        """
        fig, ax = plt.subplots(figsize=self.figsize)

        for result in results:
            ax.plot(result.monthly_data.index, result.monthly_data[metric],
                   marker='o', linewidth=2, label=result.scenario_name)

        # Add horizontal line at zero
        if metric == 'cumulative_savings':
            ax.axhline(y=0, color='red', linestyle='--', alpha=0.5,
                      label='Break-even point')
            ax.set_ylabel('Cumulative Savings (EUR)')
            ax.set_title('Savings Runway Comparison')
        elif metric == 'net_cashflow':
            ax.axhline(y=0, color='red', linestyle='--', alpha=0.5)
            ax.set_ylabel('Monthly Cash Flow (EUR)')
            ax.set_title('Monthly Cash Flow Comparison')
        else:
            ax.set_ylabel(f'{metric} (EUR)')
            ax.set_title(f'{metric.replace("_", " ").title()} Comparison')

        ax.set_xlabel('Month')
        ax.legend()
        ax.grid(True, alpha=0.3)

        plt.tight_layout()
        return fig

    def plot_cashflow_breakdown(self, result: SimulationResult) -> Figure:
        """Create a detailed breakdown of cash flow components.

        Args:
            result: SimulationResult to visualize

        Returns:
            matplotlib Figure object
        """
        fig, axes = plt.subplots(2, 2, figsize=(15, 10))
        fig.suptitle(f'{result.scenario_name} - Detailed Analysis')

        # Monthly cash flow components
        ax1 = axes[0, 0]
        ax1.plot(result.monthly_data.index, result.monthly_data['income'],
                marker='s', color='green', label='Income')
        ax1.plot(result.monthly_data.index, result.monthly_data['spending'],
                marker='^', color='red', label='Spending')
        ax1.plot(result.monthly_data.index, result.monthly_data['saving'],
                marker='d', color='blue', label='Saving')
        ax1.set_title('Monthly Income/Spending/Saving')
        ax1.set_ylabel('EUR')
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # Net cash flow
        ax2 = axes[0, 1]
        colors = ['green' if x >= 0 else 'red' for x in result.monthly_data['net_cashflow']]
        ax2.bar(result.monthly_data.index, result.monthly_data['net_cashflow'],
               color=colors, alpha=0.7)
        ax2.axhline(y=0, color='black', linestyle='-', alpha=0.5)
        ax2.set_title('Monthly Net Cash Flow')
        ax2.set_ylabel('EUR')
        ax2.grid(True, alpha=0.3)

        # Cumulative savings
        ax3 = axes[1, 0]
        ax3.plot(result.monthly_data.index, result.monthly_data['cumulative_savings'],
                marker='o', linewidth=3, color='purple')
        ax3.axhline(y=0, color='red', linestyle='--', alpha=0.5)
        ax3.fill_between(result.monthly_data.index, result.monthly_data['cumulative_savings'],
                        0, alpha=0.3, color='purple')
        ax3.set_title('Cumulative Savings')
        ax3.set_ylabel('EUR')
        ax3.set_xlabel('Month')
        ax3.grid(True, alpha=0.3)

        # Summary statistics
        ax4 = axes[1, 1]
        ax4.axis('off')

        stats_text = f"""
        Scenario: {result.scenario_name}

        Summary Statistics:
        • Final Savings: €{result.summary['final_savings']:,.0f}
        • Min Savings: €{result.summary['min_savings']:,.0f}
        • Avg Monthly Cash Flow: €{result.summary['avg_monthly_cashflow']:,.0f}
        • Runway (months): {result.get_runway_months() or 'Never runs out'}

        Parameters:
        """ + "\n".join([f"• {k}: {v}" for k, v in result.parameters.items()])

        ax4.text(0.05, 0.95, stats_text, transform=ax4.transAxes,
                verticalalignment='top', fontfamily='monospace', fontsize=9)

        plt.tight_layout()
        return fig

    def plot_runway_sensitivity(self, scenarios_data: dict[str, SimulationResult]) -> Figure:
        """Plot how different scenario parameters affect runway.

        Args:
            scenarios_data: Dict mapping scenario descriptions to results

        Returns:
            matplotlib Figure object
        """
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))

        # Runway months comparison
        scenario_names = []
        runway_months = []
        final_savings = []

        for name, result in scenarios_data.items():
            scenario_names.append(name)
            runway = result.get_runway_months()
            runway_months.append(runway if runway is not None else 999)  # Use large number for "never"
            final_savings.append(result.summary['final_savings'])

        # Runway comparison
        colors = ['red' if x < 999 else 'green' for x in runway_months]
        bars1 = ax1.barh(scenario_names, runway_months, color=colors, alpha=0.7)
        ax1.set_xlabel('Months Until Savings Exhausted')
        ax1.set_title('Runway Comparison')
        ax1.grid(True, alpha=0.3)

        # Add value labels
        for _i, (bar, months) in enumerate(zip(bars1, runway_months, strict=False)):
            if months < 999:
                ax1.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height()/2,
                        f'{months}m', ha='left', va='center')
            else:
                ax1.text(bar.get_width() - 10, bar.get_y() + bar.get_height()/2,
                        'Safe', ha='right', va='center', color='white', fontweight='bold')

        # Final savings comparison
        colors2 = ['green' if x >= 0 else 'red' for x in final_savings]
        bars2 = ax2.barh(scenario_names, final_savings, color=colors2, alpha=0.7)
        ax2.set_xlabel('Final Savings (EUR)')
        ax2.set_title('Final Financial Position')
        ax2.axvline(x=0, color='black', linestyle='--', alpha=0.5)
        ax2.grid(True, alpha=0.3)

        # Add value labels
        for bar, savings in zip(bars2, final_savings, strict=False):
            ax2.text(savings + (abs(savings) * 0.02), bar.get_y() + bar.get_height()/2,
                    f'€{savings:,.0f}', ha='left' if savings >= 0 else 'right', va='center')

        plt.tight_layout()
        return fig

    def create_emergency_fund_chart(self, baseline_data: dict[str, float],
                                   scenarios: list[SimulationResult],
                                   safety_margins: list[float] | None = None) -> Figure:
        """Create chart showing required emergency fund for different scenarios.

        Args:
            baseline_data: Monthly baseline amounts
            scenarios: List of simulation results
            safety_margins: Different safety margin multipliers to show

        Returns:
            matplotlib Figure object
        """
        if safety_margins is None:
            safety_margins = [1.0, 1.5, 2.0]
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))

        # Calculate required emergency funds
        scenario_names = [result.scenario_name for result in scenarios]

        # For each safety margin, calculate requirements
        margin_data = {}
        for margin in safety_margins:
            requirements = []
            for result in scenarios:
                min_savings = result.monthly_data['cumulative_savings'].min()
                required = max(0, abs(min_savings) * margin) if min_savings < 0 else 0
                requirements.append(required)
            margin_data[f'{margin}x margin'] = requirements

        # Stacked bar chart for emergency fund requirements
        bottom = None
        colors = ['lightcoral', 'orange', 'gold']

        for i, (margin_name, requirements) in enumerate(margin_data.items()):
            ax1.barh(scenario_names, requirements, left=bottom,
                    label=margin_name, color=colors[i % len(colors)], alpha=0.7)
            bottom = requirements if bottom is None else [b + r for b, r in zip(bottom, requirements, strict=False)]

        ax1.set_xlabel('Required Emergency Fund (EUR)')
        ax1.set_title('Emergency Fund Requirements by Scenario')
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # Monthly expense multiples
        monthly_expenses = baseline_data.get('spending', 0)
        if monthly_expenses > 0:
            expense_multiples = [req / monthly_expenses for req in margin_data['1.5x margin']]

            bars = ax2.barh(scenario_names, expense_multiples,
                           color='steelblue', alpha=0.7)
            ax2.set_xlabel('Months of Expenses')
            ax2.set_title('Emergency Fund as Months of Regular Expenses')
            ax2.grid(True, alpha=0.3)

            # Add value labels
            for bar, months in zip(bars, expense_multiples, strict=False):
                ax2.text(bar.get_width() + 0.2, bar.get_y() + bar.get_height()/2,
                        f'{months:.1f}m', ha='left', va='center')

        plt.tight_layout()
        return fig


def quick_plot(result: SimulationResult, show_details: bool = False) -> Figure:
    """Quick plotting function for interactive use.

    Args:
        result: SimulationResult to plot
        show_details: If True, show detailed breakdown

    Returns:
        matplotlib Figure object
    """
    if not MATPLOTLIB_AVAILABLE:
        return None

    visualizer = SimulationVisualizer()

    if show_details:
        return visualizer.plot_cashflow_breakdown(result)
    return result.plot_cashflow()


def compare_scenarios(*results: SimulationResult, metric: str = 'cumulative_savings') -> Figure:
    """Quick comparison of multiple scenarios.

    Args:
        *results: SimulationResult objects to compare
        metric: Metric to compare ('cumulative_savings', 'net_cashflow', etc.)

    Returns:
        matplotlib Figure object
    """
    if not MATPLOTLIB_AVAILABLE:
        return None

    visualizer = SimulationVisualizer()
    return visualizer.plot_scenario_comparison(list(results), metric)

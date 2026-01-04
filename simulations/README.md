# Financial Simulation Framework

A modular framework for household finance simulations. Can be used standalone or with FafyCat integration.

## Features

- **Pluggable Data Sources**: Use with FafyCat, CSV files, or custom data
- **Realistic Data**: Automatically filters outliers (property purchases, etc.) for regular spending patterns
- **Scenario Planning**: Parental leave, job loss, income changes, spending reductions
- **Emergency Fund Calculation**: Required runway analysis with configurable safety margins
- **Visualization Ready**: Notebook-friendly with built-in plotting capabilities
- **Extensible**: Easy to add custom scenarios and data sources

## Quick Start

### Standalone Usage (No FafyCat Required)

```python
from simulations import DictDataSource, Simulation
from simulations.scenarios import ParentalLeaveScenario

# Define your baseline monthly data
source = DictDataSource({
    'income': 5000.0,    # Monthly income
    'spending': 3500.0,  # Monthly spending
    'saving': 500.0      # Monthly saving transfers
})

# Run simulation
sim = Simulation(source.get_baseline_cashflow(), initial_savings=20000)
scenario = ParentalLeaveScenario(months_without_salary=3)
result = sim.run(scenario, months=24)

print(f"Final savings: €{result.summary['final_savings']:,.0f}")
```

### From CSV File

```python
from simulations import CSVDataSource, Simulation

# CSV should have columns: date, amount, category_type
# category_type is one of: 'income', 'spending', 'saving'
source = CSVDataSource("my_transactions.csv", months_back=12)

sim = Simulation(source.get_baseline_cashflow(), initial_savings=15000)
```

### With FafyCat Integration

```python
from simulations import FafyCatDataLoader, Simulation
from simulations.scenarios import ParentalLeaveScenario

# Load your data (automatically filters outliers)
loader = FafyCatDataLoader("data/fafycat_prod.db")
baseline = loader.get_baseline_cashflow(year=2024)

# Create scenario
scenario = ParentalLeaveScenario(
    months_without_salary=3,
    salary_replacement_rate=0.0,  # No Elterngeld
    kindergeld_increase=250       # Second child benefit
)

# Run simulation
sim = Simulation(baseline, initial_savings=20000)
result = sim.run(scenario, months=24)

print(f"Final savings: €{result.summary['final_savings']:,.0f}")
print(f"Runway: {result.get_runway_months()} months")

# Calculate emergency fund requirement
runway_analysis = sim.calculate_required_runway(scenario)
print(f"Required emergency fund: €{runway_analysis['required_emergency_fund']:,.0f}")
```

### Visualization
```python
# Plot results
result.plot_cashflow()

# Compare scenarios
from simulations.visualizations import compare_scenarios
compare_scenarios(result1, result2, result3)
```

## Data Sources

All data sources implement the `DataSource` interface with `get_baseline_cashflow()` and `get_monthly_averages()` methods.

### `DictDataSource`
Simple data source from a dictionary. Best for testing or when you have pre-calculated averages.

```python
source = DictDataSource({'income': 5000, 'spending': 3500, 'saving': 500})
```

### `CSVDataSource`
Load transaction-level data from CSV files. Calculates monthly averages automatically.

**Expected CSV columns:**
- `date` - Transaction date
- `amount` - Transaction amount (positive values)
- `category_type` - One of: `income`, `spending`, `saving`

```python
source = CSVDataSource("transactions.csv", months_back=12)
```

### `FafyCatDataLoader`
Full integration with FafyCat database. Requires FafyCat to be installed.

**Key Methods:**
- `get_baseline_cashflow(year=2024)` - Monthly averages by category
- `get_monthly_averages(exclude_outliers=True)` - Raw monthly data
- `get_category_breakdown(year)` - Detailed spending analysis
- `get_weighted_baseline(year_weights)` - Weighted average across years
- `compare_baselines(years)` - Compare data across years

### Custom Data Sources

Implement the `DataSource` abstract class to create your own:

```python
from simulations import DataSource

class MyDataSource(DataSource):
    def get_baseline_cashflow(self) -> dict[str, float]:
        return {'income': ..., 'spending': ..., 'saving': ...}

    def get_monthly_averages(self, **kwargs) -> dict[str, float]:
        return self.get_baseline_cashflow()
```

## Simulation
Runs financial scenarios over time.

```python
sim = Simulation(baseline_data, initial_savings=15000)
result = sim.run(scenario, months=24)
emergency_fund = sim.calculate_required_runway(scenario, safety_margin=1.5)
```

### `Scenario` Classes
Define financial adjustments to apply.

**Built-in Scenarios:**
- `ParentalLeaveScenario` - Months without salary + benefits
- `InflationOnlyScenario` - Baseline + inflation adjustments
- `IncomeChangeScenario` - Job loss, promotion, etc.
- `SpendingReductionScenario` - Reduce spending by category
- `CustomScenario` - Define your own adjustment function

## Example Scenarios

### Parental Leave (3 months)
```python
scenario = ParentalLeaveScenario(
    months_without_salary=3,
    salary_replacement_rate=0.67,  # 67% Elterngeld
    inflation_rate=0.03,
    kindergeld_increase=250,
    start_month=6  # Begin leave in month 6
)
```

### Job Loss with Unemployment Benefits
```python
from simulations.scenarios import create_job_loss_scenario
scenario = create_job_loss_scenario(
    months=6,
    unemployment_benefit_rate=0.6  # 60% ALG I
)
```

### Custom Scenario
```python
def reduce_spending_during_leave(baseline, month):
    adjusted = baseline.copy()
    if 6 <= month <= 8:  # Months 6-8
        adjusted['spending'] *= 0.8  # 20% reduction
    return adjusted

scenario = CustomScenario(reduce_spending_during_leave, "Reduced Spending")
```

## Data Filtering

By default, the framework excludes transaction outliers (1st-99th percentile) to focus on regular spending patterns:

```python
# Include outliers (property purchases, etc.)
baseline = loader.get_baseline_cashflow(exclude_outliers=False)

# Custom percentile filtering
baseline = loader.get_monthly_averages(
    outlier_percentiles=(5, 95)  # More aggressive filtering
)
```

## Emergency Fund Analysis

```python
# Calculate required emergency fund
runway = sim.calculate_required_runway(scenario, months=24, safety_margin=1.5)

print(f"Required fund: €{runway['required_emergency_fund']:,.0f}")
print(f"Runway until broke: {runway['runway_months']} months")
print(f"Recommended total savings: €{runway['recommended_total_savings']:,.0f}")
```

## File Structure

```
simulations/
├── __init__.py           # Main imports
├── core.py              # Base classes (Scenario, Simulation, SimulationResult)
├── data_sources.py      # DataSource ABC, DictDataSource, CSVDataSource
├── data_loader.py       # FafyCatDataLoader (requires FafyCat)
├── scenarios.py         # Concrete scenario implementations
├── visualizations.py    # Plotting utilities
└── README.md           # This file

example_simulation.py     # Command-line example
simulation_example.ipynb  # Jupyter notebook example
```

## Requirements

**Core (standalone usage):**
- Python 3.13+
- pandas
- python-dateutil

**Optional:**
- matplotlib (for visualizations)
- FafyCat (for `FafyCatDataLoader` - includes sqlalchemy)

## Tips

1. **Start with filtered data** - Excludes property purchases and other outliers
2. **Use realistic scenarios** - Base on your actual income replacement options
3. **Test multiple safety margins** - 1.5x is conservative, 2x is very safe
4. **Export results** - Save simulation data as CSV for external analysis
5. **Iterate scenarios** - Easy to test "what if" variations
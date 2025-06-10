# 🐱 FafyCat - Local-First Transaction Categorization

FafyCat is a privacy-focused financial transaction categorization tool that uses machine learning to automatically organize your banking data with >90% accuracy. All processing happens locally on your device - no cloud services, no data sharing.

## ✨ Key Features

- **🤖 Smart Categorization**: Machine learning automatically categorizes transactions with high accuracy
- **🔒 Privacy First**: All data stays on your device - no external APIs or cloud services
- **📊 Intelligent Review**: Active learning reduces manual work by 70-90%
- **🏪 Merchant Memory**: Learns from your patterns to improve over time
- **📈 Export Ready**: Multiple export formats for your favorite analysis tools
- **⚡ Fast & Efficient**: Process thousands of transactions in seconds

## 🚀 Quick Start

### Prerequisites

- Python 3.13 or later
- uv package manager https://docs.astral.sh/uv/getting-started/installation/

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/davidchris/fafycat.git
   cd fafycat
   ```

2. **Install dependencies**
   ```bash
   uv install
   ```

3. **Configure environment** (optional)
   ```bash
   cp .env.example .env
   # Edit .env to customize paths and settings
   ```

4. **Start the application**
   ```bash
   # Development mode with sample data
   uv run python run_dev.py
   
   # Production mode with real data
   uv run python run_prod.py
   ```

5. **Open your browser**
   - Development: http://localhost:8001
   - Production: http://localhost:8000

## 📋 Getting Started Guide

### First Time Setup

1. **Import Your Data**
   - Navigate to the Import page
   - Upload your bank transaction CSV files
   - The system auto-detects column formats

2. **Review & Categorize**
   - Go to the Review page
   - Correct any miscategorized transactions
   - The system learns from your corrections

3. **Train the Model**
   - Visit Settings → Train Model
   - Click "Train ML Model Now"
   - Training takes seconds to minutes

4. **Enjoy Automation**
   - Future imports will be auto-categorized
   - Only review uncertain predictions
   - Export data for analysis

### Using Labeled Historical Data

If you have previously categorized transactions:

```bash
# Import your labeled data
uv run python scripts/import_labeled_data.py --data-path /path/to/your/data

# Or use the reset script for a fresh start
uv run python scripts/reset_and_import.py --labeled-data-path /path/to/your/data --train-model
```

#### Where do I get my banking transactions from?

- I'm getting mine via the [MoneyMoney App](https://moneymoney.app).

## 🏗️ Architecture

```
┌─────────────────┐
│   CSV Import    │ → Flexible format detection
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌──────────────────┐
│ Feature Extract │────▶│  ML Prediction   │
│  - Merchants    │     │  - LightGBM      │
│  - Amounts      │     │  - Naive Bayes   │
│  - Patterns     │     │  - Ensemble      │
└─────────────────┘     └──────────────────┘
                                 │
                                 ▼
                        ┌──────────────────┐
                        │   Review UI      │
                        │  Active Learning │
                        └──────────────────┘
                                 │
                                 ▼
                        ┌──────────────────┐
                        │   Data Export    │
                        │ CSV/Excel/JSON   │
                        └──────────────────┘
```

## 📊 Supported CSV Formats

FafyCat automatically detects and handles various banking export formats:

- **Date**: Various formats (DD/MM/YYYY, MM/DD/YYYY, YYYY-MM-DD)
- **Amount**: Positive/negative or separate debit/credit columns
- **Description**: Transaction details and merchant names
- **Category**: If present, used for training

Common bank formats supported:
- German banks (Sparkasse, DKB, etc.)
- US banks (Chase, Bank of America, etc.)
- UK banks (Barclays, HSBC, etc.)
- Generic CSV exports

## 🎯 How It Works

### Smart Learning System

1. **Initial Training**: Learn from your categorized transactions
2. **Prediction**: Automatically categorize new transactions
3. **Active Learning**: Intelligently select which transactions need review
4. **Continuous Improvement**: Learn from corrections over time

### Privacy & Security

- **Local Processing**: All ML models run on your device
- **No Cloud Services**: Zero external API calls
- **Your Data**: You own and control all your financial data
- **Open Source**: Fully auditable codebase

## 🛠️ Configuration

### Environment Variables

Create a `.env` file to customize your setup:

```bash
# Database location
FAFYCAT_DB_URL=sqlite:///data/fafycat.db

# Data directories
FAFYCAT_DATA_DIR=data
FAFYCAT_EXPORT_DIR=data/exports
FAFYCAT_MODEL_DIR=data/models

# Server settings
FAFYCAT_DEV_PORT=8001
FAFYCAT_PROD_PORT=8000
FAFYCAT_HOST=127.0.0.1
```

### Database Management

- **Development**: Uses `data/fafycat_dev.db` with synthetic test data
- **Production**: Uses `data/fafycat_prod.db` with your real data
- **Custom**: Set `FAFYCAT_DB_URL` to any SQLite path

## 📈 Performance

- **Accuracy**: >90% correct categorization
- **Speed**: <100ms per transaction
- **Scale**: Handles 100,000+ transactions
- **Efficiency**: 70-90% reduction in manual review

## 🔧 Development

### Running Tests
```bash
uv run pytest
```

### Code Quality
```bash
# Linting
uvx ruff check --fix

# Formatting
uvx ruff format

# Type checking
uv run mypy
```

### API Documentation
- FastAPI docs: http://localhost:8000/docs
- OpenAPI schema: http://localhost:8000/openapi.json

## 🤝 Contributing

tbd.

## 📄 License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Built with FastAPI, FastHTML, and scikit-learn
- Inspired by the need for privacy-preserving financial tools

---

**Note**: FafyCat is designed for personal use. Always verify categorizations for important financial decisions.
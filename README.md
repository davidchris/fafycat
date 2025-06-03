# 🐱 FafyCat - Family Finance Categorizer

A local-first transaction categorization tool that uses machine learning to automatically categorize banking transactions with <10% error rate, enabling efficient financial tracking and analysis.

## 🚀 Quick Start

### Development Mode (with synthetic test data)
```bash
# 1. Initialize development database
uv run scripts/init_db.py

# 2. Import synthetic test data
uv run scripts/import_synthetic.py

# 3. Train the ML model
uv run scripts/train_model.py

# 4. Launch in development mode
uv run python run_dev.py
```

### Production Mode (with your real data)
```bash
# 1. Initialize production database
uv run scripts/init_prod_db.py

# 2. Launch in production mode
uv run python run_prod.py

# 3. Import your real transaction CSV files through the UI
# 4. Review and categorize transactions
# 5. Train the model with your real data
```

## 📋 Features

- **🤖 Automatic Categorization**: ML-powered transaction categorization with >90% accuracy
- **🏠 Local-First**: All data stays on your device, no external APIs
- **🎯 Smart Learning**: Active learning prioritizes uncertain predictions for review
- **🏪 Merchant Rules**: High-confidence merchant mappings override ML predictions
- **📊 Multiple Formats**: Flexible CSV import supporting German and English banking formats
- **⚡ Real-time UI**: Streamlit-based interface for easy transaction review and management

## 🏗️ Architecture

```
┌─────────────────┐
│   CSV Import    │ → Flexible column detection, deduplication
│  (pandas read)  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     ┌──────────────────┐
│ Feature Extract │────▶│  ML Prediction   │ → LightGBM + confidence calibration
│  - Merchant     │     │  (LightGBM)      │
│  - Amount range │     └──────────────────┘
│  - Text tokens  │              │
│  - Temporal     │              ▼
└─────────────────┘     ┌──────────────────┐
         │              │  Review UI       │ → Streamlit interface
         │              │  (Streamlit)     │
         └─────────────▶│  + Active Learn  │
                        └──────────────────┘
                                 │
                                 ▼
                        ┌──────────────────┐
                        │   CSV Export     │ → Analysis-ready data
                        └──────────────────┘
```

## 💾 Tech Stack

- **Backend**: Python 3.13, SQLite, SQLAlchemy, Pydantic
- **ML**: LightGBM, scikit-learn, TF-IDF vectorization
- **Frontend**: Streamlit with responsive design
- **Data**: Pandas, deterministic deduplication, comprehensive feature extraction
- **Development**: uv package management, ruff linting, pytest testing

## 📊 User Flow

1. **Import CSV** → Parse & validate with flexible column detection
2. **ML Prediction** → Categorize all transactions with confidence scores  
3. **Review UI** → Show predictions sorted by uncertainty for efficient review
4. **Manual Corrections** → Update categories with active learning feedback
5. **Export** → Analysis-ready data with predictions and confidence scores

## 🎯 Performance

- **Accuracy**: >90% correct categorization on real transaction data
- **Speed**: <100ms per transaction prediction, <10s for 1000 transactions
- **Privacy**: Local-only operation, no external API calls
- **Efficiency**: Active learning reduces manual review by 70%

## 💾 Database Management

FafyCat supports separate databases for development and production:

- **Development DB**: `data/fafycat_dev.db` (synthetic test data)
- **Production DB**: `data/fafycat_prod.db` (your real transaction data)

### Manual Database Configuration

Create a `.env` file (copy from `.env.example`) to customize:

```bash
# For development
FAFYCAT_DB_URL=sqlite:///data/fafycat_dev.db

# For production
FAFYCAT_DB_URL=sqlite:///data/fafycat_prod.db

# Or use absolute paths
FAFYCAT_DB_URL=sqlite:////Users/yourname/Documents/fafycat_transactions.db
```

### Database Locations

Currently stored in:
- Development: `/Users/david/dev/fafycat/data/fafycat_dev.db`
- Production: `/Users/david/dev/fafycat/data/fafycat_prod.db`
- Models: `/Users/david/dev/fafycat/data/models/`
- Exports: `/Users/david/dev/fafycat/data/exports/`

## 🛠️ Setup from Scratch

After cloning the repository, follow these steps to get FafyCat running:

### 1. Environment Setup
```bash
# Clone the repository
git clone <repository-url>
cd fafycat

# Install dependencies
uv install
```

### 2. Initialize Database and Load Data
```bash
# Initialize production database (for real transactions)
uv run scripts/init_prod_db.py

# Option A: Import your labeled transaction data
uv run scripts/import_labeled_data.py path/to/your/transactions.csv

# Option B: Use synthetic data for testing (development only)
uv run scripts/init_db.py  # Creates dev database
uv run scripts/import_synthetic.py  # Adds test data
```

### 3. Train Your First Model
```bash
# Train the ML model with your imported data
uv run scripts/train_model.py
```

### 4. Start Categorizing and Reviewing
```bash
# Launch the application
uv run python run_prod.py  # For real data
# OR
uv run python run_dev.py   # For development/testing

# Open your browser to http://localhost:8501
# 1. Go to "Import" page to add new CSV files
# 2. Use "Review" page to check and correct predictions
# 3. Re-train model periodically as you add more labeled data
```

### 📝 Expected CSV Format

Your transaction CSV should include columns for:
- Date (various formats supported)
- Amount (positive for income, negative for expenses)  
- Description/Merchant name
- Optional: Account, Reference, etc.

The system auto-detects column names and formats during import.

## 📂 Category Management

### Reviewing Categories and Budgets

View and manage your categories through the web UI:

1. **Launch the app**: `uv run python run_prod.py` 
2. **Navigate to Settings**: Use sidebar → "Settings & Categories"
3. **View Categories**: Click "📋 Categories" tab

This shows all categories by type (Spending 💸, Income 💰, Saving 🏦) with monthly budgets and status.

### Modifying Existing Categories

**✅ Safe Operations:**
- **Update names/budgets**: Changes apply immediately to all transactions
- **Deactivate categories**: Set `is_active = False` to remove from workflows while preserving historical data

**🛡️ Protected Operations:**
- **Category deletion**: Blocked if any transactions use the category
- Error message shows usage count: `"Cannot delete category - used by 147 transactions"`

**💡 Recommended Approach:**
Instead of deleting categories with existing transactions, **deactivate** them:
- Removes category from new transaction workflows  
- Preserves all historical transaction labels
- Prevents data loss while cleaning up your category list

## 🔧 Development

```bash
# Install dependencies
uv install

# Run tests
uv run pytest

# Lint code
uvx ruff check

# Type check
uv run mypy src/
```

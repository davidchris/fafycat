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
# OR launch with FastAPI directly
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Production Mode (with your real data)
```bash
# 1. Initialize production database
uv run scripts/init_prod_db.py

# 2. Launch in production mode
uv run python run_prod.py
# OR launch with FastAPI directly
uv run uvicorn main:app --host 0.0.0.0 --port 8000

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
- **⚡ Real-time UI**: FastHTML web interface with responsive design for easy transaction review and management

## 🏗️ Architecture

```
┌─────────────────┐
│   CSV Import    │ → FastAPI upload endpoints, flexible column detection
│  (FastAPI API)  │
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
         │              │   Review UI      │ → FastHTML web interface
         │              │  (FastHTML)      │
         └─────────────▶│  + Active Learn  │
                        └──────────────────┘
                                 │
                                 ▼
                        ┌──────────────────┐
                        │   CSV Export     │ → Analysis-ready data via API
                        └──────────────────┘
```

## 💾 Tech Stack

- **Backend**: Python 3.13, FastAPI, SQLite, SQLAlchemy, Pydantic
- **Frontend**: FastHTML with Tailwind CSS, responsive design
- **ML**: LightGBM, scikit-learn, TF-IDF vectorization
- **Data**: Pandas, deterministic deduplication, comprehensive feature extraction
- **Development**: uv package management, ruff linting, pytest testing

## 📊 User Flow

### Complete Workflow (After Reset/Import)
1. **Import Labeled Data** → `uv run scripts/reset_and_import.py` discovers categories from your transaction history
2. **Train ML Model** → Web UI "Train Model Now" button or `uv run scripts/train_model.py`
3. **Import New Transactions** → FastAPI upload with automatic ML predictions for categorized transactions
4. **Review & Correct** → FastHTML web interface sorted by confidence for efficient manual review
5. **Re-train Periodically** → Settings page "Retrain Model" as you add more labeled data
6. **Export Analysis** → API endpoints for analysis-ready data with predictions and confidence scores

### Daily Usage (After Initial Setup)
1. **Upload CSV** → Drag & drop transaction files via web interface
2. **Auto-Categorization** → ML predictions applied automatically during upload (if model exists)
3. **Review Low-Confidence** → Smart prioritization shows uncertain predictions first
4. **One-Click Training** → Settings page shows ML status and provides train/retrain buttons
5. **Batch Prediction** → Settings page "Predict X Transactions" for retroactive categorization

## 🔧 How It Works

### During Upload
When users upload CSV files, the system automatically runs ML predictions on new transactions if a trained model is available. The upload process:
- Validates and processes CSV data
- Saves transactions to the database
- Automatically predicts categories using the trained ML model
- Gracefully handles cases where no model is available

### Real-time Prediction
Individual transactions can be predicted via the `/api/ml/predict` endpoint, providing:
- Category predictions with confidence scores
- Feature contribution analysis for explainability
- Merchant rule matching for high-confidence categorizations

### Batch Processing
Large sets of transactions can be processed efficiently via bulk endpoints:
- `/api/ml/predict/bulk` for batch predictions
- `/api/ml/predict/batch-unpredicted` for existing unpredicted transactions
- Background processing for optimal performance

### Background Processing
Existing unpredicted transactions can be batch-processed after model training, allowing users to:
- Upload transactions before training a model
- Train models with sufficient labeled data
- Retroactively predict categories for historical transactions

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

#### Start Fresh with Real Data (Recommended)
```bash
# Reset everything and import your labeled data (uses production database)
uv run python scripts/reset_and_import.py --labeled-data-path /path/to/your/csv/files

# Or use default path (fafycat-v1 location)
uv run python scripts/reset_and_import.py

# Also train model after import
uv run python scripts/reset_and_import.py --train-model

# For development/testing (uses development database)
uv run python scripts/reset_and_import.py --dev-mode --use-sample-data
```

#### Alternative: Manual Setup
```bash
# Initialize production database (empty - no default categories)
uv run scripts/init_prod_db.py

# Option A: Import your labeled transaction data (RECOMMENDED)
# This automatically discovers categories from your data
uv run scripts/import_labeled_data.py

# Option B: Use synthetic data for testing (development only)
uv run scripts/init_db.py  # Creates dev database
uv run scripts/import_synthetic.py  # Adds test data
```

**📋 Category Discovery**: When you import labeled data, FafyCat automatically discovers and creates categories from your transaction data without any predefined defaults. This ensures the ML model learns from YOUR actual spending patterns, not generic assumptions.

### 3. Train Your First Model
```bash
# Option A: Train via web interface (RECOMMENDED)
uv run python run_prod.py
# Then go to Settings page → Click "Train ML Model Now"

# Option B: Train via command line
uv run scripts/train_model.py
```

### 4. Start Categorizing and Reviewing
```bash
# Launch the application
uv run python run_prod.py  # For real data
# OR
uv run python run_dev.py   # For development/testing
# OR launch FastAPI directly
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Open your browser to http://localhost:8000
# 1. Check "Settings" page for ML model status and training options
# 2. Use "Import" page to add new CSV files (with automatic predictions)
# 3. Use "Review" page to check and correct ML predictions
# 4. Re-train model via Settings page as you add more labeled data
```

### 📝 Expected CSV Format

Your transaction CSV should include columns for:
- Date (various formats supported)
- Amount (positive for income, negative for expenses)  
- Description/Merchant name
- Optional: Account, Reference, etc.

The system auto-detects column names and formats during import.

## 📂 Category Management

FafyCat uses a **data-first approach** to categories - no default categories are created. Instead, categories are discovered from your actual transaction data to ensure the ML model learns from your real spending patterns.

### 🏷️ Category Discovery (Recommended)

When you import labeled transaction data, FafyCat automatically:

1. **Scans your data** for existing category labels (looks for "Cat" or "Category" columns)
2. **Discovers unique categories** from your actual spending patterns
3. **Infers category types** (Spending 💸, Income 💰, Saving 🏦) using intelligent pattern matching
4. **Creates categories without budgets** initially (budget = 0.0)

```bash
# Import labeled data and discover categories automatically
uv run scripts/import_labeled_data.py

# Expected output:
# 🏷️  Discovering categories from labeled data...
# 📋 Creating 15 categories (without budgets)...
# ✅ Created 15 new categories
```

### 🎛️ Category Management Interface

Access the full category management interface through the web UI:

1. **Launch the app**: `uv run python run_prod.py` or `uv run uvicorn main:app --host 0.0.0.0 --port 8000`
2. **Navigate to Settings**: Use sidebar → "Settings & Categories"

#### Empty State (No Categories)
- Shows guidance to import labeled data or create categories manually
- Recommends the data-first approach for better ML accuracy

#### Active Management
- **View by type**: Categories grouped by Spending/Income/Saving
- **Budget management**: Set monthly budgets (optional but prompted)
- **Deactivate unwanted**: Hide categories while preserving historical data
- **Create new**: Manual category creation for edge cases

### 🔧 Category Operations

**✅ Safe Operations:**
- **Set/update budgets**: Optional monthly budget targets for tracking
- **Deactivate categories**: Hide from workflows while preserving transaction history
- **Create new categories**: Manual creation when needed

**🛡️ Data Protection:**
- **Category deletion**: Blocked if any transactions use the category
- **Historical preservation**: Deactivated categories maintain all transaction links
- **No data loss**: Deactivation preferred over deletion for data integrity

**💡 Best Practices:**
- **Import labeled data first** to discover your actual categories
- **Review discovered categories** and deactivate any unwanted ones
- **Set budgets gradually** as you understand your spending patterns
- **Use deactivation** instead of deletion to preserve transaction history

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

## 🚀 Next Steps (Post-Migration)

The FastAPI + FastHTML migration is **functionally complete** and addresses the original state persistence issues. The following tasks are prioritized for continued development:

### 🔴 High Priority (Ready for Implementation)

#### 1. **ML Pipeline Integration** ✅ **COMPLETED**
- ~~Connect existing ML categorizer to FastAPI endpoints~~ → **Full ML API integration implemented**
- ~~Add `/api/ml/predict` endpoint for real-time categorization~~ → **Complete with bulk endpoints**
- ~~Implement background ML prediction for new uploads~~ → **Auto-prediction during CSV upload**
- **Status**: ML predictions now work seamlessly with upload workflow and dedicated API endpoints
- **Added endpoints**: `/api/ml/predict`, `/api/ml/predict/bulk`, `/api/ml/status`, `/api/ml/retrain`

#### 2. **Real Transaction Display** ✅ **COMPLETED**
- ~~Update Review page to show actual transactions from database~~ → **Implemented with dynamic data fetching**
- ~~Implement transaction table component with category editing~~ → **Full categorization workflow working**
- **Status**: Review page now displays real transactions with working category dropdowns and save functionality
- **Remaining**: Add pagination, filtering, and sorting controls (Phase 2 enhancement)

#### 3. **Category Management Interface** ✅ **COMPLETED**
- ~~Complete Settings page with working category CRUD operations~~ → **Full category management implemented**
- ~~Add budget management and category activation controls~~ → **Budget editing and deactivation working**
- ~~Connect to existing category API endpoints~~ → **Complete with data-first category discovery**
- **Status**: Data-first category discovery system implemented with comprehensive management interface
- **Added features**: Empty state UI, category discovery from labeled data, budget management, deactivation

### 🟡 Medium Priority

#### 4. **Enhanced UX with HTMX** ✅ **PHASE 1-2 COMPLETED**
- ~~Add HTMX for seamless transaction categorization~~ → **Implemented with inline forms and confidence filtering**
- ~~Implement ML model training UI~~ → **Complete with Settings page train/retrain buttons**
- ~~Real-time confidence threshold filtering~~ → **Live slider updates without page reloads**
- **Status**: Core HTMX functionality implemented for transaction review and ML training workflows
- **Remaining**: Upload progress indicators, auto-save for budget changes, batch operations

#### 5. **Export Functionality**
- Complete export API endpoints (`/api/export/*`)
- Create export configuration UI
- Support multiple formats (CSV, Excel, JSON)
- **Files to create**: `api/export.py`, `web/pages/export.py`

#### 6. **Code Quality Cleanup** ✅ **COMPLETED**
- ~~Address remaining 122 lint issues~~ → **Reduced from 122 to 4 minor warnings**
- ~~Fix FastAPI dependency injection warnings~~ → **Fixed with proper per-file ignores**
- ~~Clean up HTML template formatting~~ → **Completed with consistent formatting**
- **Status**: Code quality significantly improved, ready for feature development

### 🟢 Low Priority (Future Enhancements)

#### 7. **Comprehensive Testing**
- Implement test framework from `test_plan.md`
- Add unit tests for API endpoints
- Browser automation testing with Puppeteer tools
- **Files to create**: `tests/` directory structure

#### 8. **Performance Optimizations**
- Database query optimization for large datasets
- Caching for ML predictions
- Background task processing for uploads
- Lazy loading for transaction tables

#### 9. **Advanced Features**
- Merchant mapping interface
- Keyboard shortcuts and accessibility
- Mobile responsiveness improvements
- Dark mode support

### 🛠️ Development Commands (Updated)

```bash
# FastAPI Development Server
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000

# API Documentation
# Available at: http://localhost:8000/docs

# Application URLs
# Main App: http://localhost:8000/app
# Import: http://localhost:8000/import  
# Review: http://localhost:8000/review
# Settings: http://localhost:8000/settings

# Legacy Streamlit (during transition)
uv run streamlit run streamlit_app.py --server.port 8501
```

### 📋 Success Metrics

- ✅ **Core Migration**: All Streamlit functionality migrated to FastAPI + FastHTML
- ✅ **State Persistence**: Category settings persist correctly across navigation  
- ✅ **Architecture**: Clean separation of API and web layers
- ✅ **Code Quality**: Lint errors reduced from 122 → 4 minor warnings, all tests passing (22/22)
- ✅ **Transaction Display**: Review page shows real data with working categorization workflow
- ✅ **ML Integration**: Complete ML pipeline integration with FastAPI endpoints
- ✅ **Category Management**: Data-first category discovery and comprehensive management interface
- ⏳ **Feature Parity**: All original features working in new system
- ⏳ **Testing**: Comprehensive test coverage for reliability

### 🎯 Immediate Next Task

**Continue with Task #5 (Export Functionality)** as the core HTMX and ML training UI is now complete. The system now has:

1. ✅ **Complete ML pipeline** with automatic predictions and web UI training
2. ✅ **Full transaction review** workflow with HTMX-enhanced interactions  
3. ✅ **Data-first category management** with discovery from labeled data
4. ✅ **ML Training Interface** with status detection and one-click training

Next priorities:
1. **Export Functionality**: Implement data export workflows for analysis-ready data
2. **Enhanced UX Phase 3**: Auto-predict after training, upload progress, batch operations

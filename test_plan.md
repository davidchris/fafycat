# FafyCat Test Plan: Remaining Tasks

## Overview
The FastAPI + FastHTML migration is **functionally complete** with 66 tests and 98.5% pass rate. This plan focuses on the remaining cleanup tasks and potential improvements.

## 🔧 Immediate Cleanup Tasks

### 1. Fix Database Schema Issue
**Problem**: Missing `review_priority` column causing ML status API errors
```sql
-- Need to add to database schema:
ALTER TABLE transactions ADD COLUMN review_priority INTEGER DEFAULT 0;
```
**Files affected**: Database migration scripts, ML status API

### 2. Fix Performance Test Integration
**Problem**: `test_performance.py` requires manual server startup
```python
# Current: Requires manual `uv run python run_dev.py`
# Need: Automated server startup/shutdown in test
```
**Files affected**: `test_performance.py`

### 3. Fix Test Assertion Issues
**Problem**: Some tests return values instead of using assertions
```python
# Fix tests that do: return result
# Should do: assert expected == result
```
**Files affected**: Manual test files (`test_auto_predict_manual.py`, etc.)

### 4. Address Deprecation Warnings (1500+ warnings)
**Problem**: Deprecated API usage
```python
# Fix: datetime.utcnow() → datetime.now(datetime.UTC)
# Fix: SQLAlchemy declarative_base() → orm.declarative_base()
# Fix: Pydantic Config → ConfigDict
```
**Files affected**: `src/fafycat/core/database.py`, `src/fafycat/data/csv_processor.py`

## 🚀 Optional Enhancements

### 1. E2E Browser Testing (if desired)
The current integration tests are comprehensive, but if full browser automation is wanted:
```bash
# Use available Puppeteer tools for:
# - Visual regression testing
# - Mobile responsiveness validation
# - Complete user journey simulation
```

### 2. Load Testing (if needed)
```python
# For larger scale validation:
def test_large_dataset_import():
    """Test 10,000+ transaction import"""

def test_concurrent_users():
    """Test multiple simultaneous operations"""
```

### 3. Test Coverage Analysis
```bash
# Generate coverage report:
uv run pytest --cov=src/fafycat --cov-report=html
# Identify any uncovered code paths
```

## 🎯 Quick Wins (Priority Order)

1. **Fix database schema** - 5 minutes, resolves ML status errors
2. **Fix test assertions** - 10 minutes, improves test reliability
3. **Fix performance test** - 15 minutes, enables automated performance validation
4. **Fix deprecation warnings** - 30 minutes, future-proofs codebase

## Test Commands

```bash
# Run all tests (current: 65/66 passing)
uv run pytest

# Run specific problem areas
uv run pytest test_performance.py  # Fails without server
uv run pytest test_auto_predict_manual.py  # Has assertion issues

# Code quality
uvx ruff check && uvx ruff format && uv run mypy
```

## Success Definition

**Test plan complete when:**
- [ ] All 66 tests pass (currently 65/66)
- [ ] Zero deprecation warnings
- [ ] Performance test runs automatically
- [ ] All tests use proper assertions

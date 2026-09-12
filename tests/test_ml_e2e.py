"""End-to-end tests for ML categorization pipeline.

Tests the full training → prediction flow for both TransactionCategorizer
and EnsembleCategorizer using synthetic data seeded into a temp DB.
"""

import os
import random
import tempfile

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from fafycat.core.config import MLConfig
from fafycat.core.database import Base, CategoryORM
from fafycat.core.models import ModelMetrics, TransactionInput, TransactionPrediction
from fafycat.data.csv_processor import CSVProcessor, create_synthetic_transactions
from fafycat.ml.categorizer import TransactionCategorizer
from fafycat.ml.ensemble_categorizer import EnsembleCategorizer

# ---------------------------------------------------------------------------
# Module-scoped fixtures (train once, share across tests in this file)
# ---------------------------------------------------------------------------

CATEGORY_NAMES = ["groceries", "restaurants", "salary", "rent", "utilities"]


@pytest.fixture(scope="module")
def ml_engine():
    """Create a temporary SQLite database engine for ML tests."""
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)

    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)

    yield engine

    os.unlink(db_path)


@pytest.fixture(scope="module")
def ml_session(ml_engine):
    """Create a session from the ML test engine."""
    Session = sessionmaker(autocommit=False, autoflush=False, bind=ml_engine)
    session = Session()

    yield session

    session.close()


@pytest.fixture(scope="module")
def seeded_db(ml_session):
    """Seed the database with synthetic transactions.

    Creates CategoryORM rows first (save_transactions only looks up existing
    categories), then persists synthetic transactions via CSVProcessor.
    """
    # Deterministic synthetic data
    random.seed(42)
    transactions = create_synthetic_transactions()

    # Create categories (must exist before save_transactions)
    for name in CATEGORY_NAMES:
        ml_session.add(CategoryORM(name=name, type="spending"))
    ml_session.commit()

    # Persist transactions
    CSVProcessor(ml_session).save_transactions(transactions, "e2e-test")
    ml_session.commit()

    yield ml_session, transactions


@pytest.fixture(scope="module")
def ml_config():
    """Return default MLConfig (85 txns > min_training_samples=50)."""
    return MLConfig()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_labels_for_transactions(session, transactions: list[TransactionInput]) -> np.ndarray:
    """Look up category_id from CategoryORM by name for each transaction."""
    category_map: dict[str, int] = {}
    for cat in session.query(CategoryORM).all():
        category_map[cat.name] = cat.id

    labels = []
    for txn in transactions:
        cat_name = (txn.category or "").strip().lower()
        labels.append(category_map[cat_name])

    return np.array(labels)


# ---------------------------------------------------------------------------
# Tests — TransactionCategorizer (DB-based training path)
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestTransactionCategorizerTrain:
    """Tests for the DB-based train() path."""

    def test_train_returns_valid_metrics(self, seeded_db, ml_config):
        session, _ = seeded_db
        categorizer = TransactionCategorizer(session, ml_config)

        metrics = categorizer.train()

        assert isinstance(metrics, ModelMetrics)
        assert 0 < metrics.accuracy <= 1.0
        assert len(metrics.precision_per_category) > 0
        assert len(metrics.recall_per_category) > 0

    def test_train_enables_predictions(self, seeded_db, ml_config):
        session, transactions = seeded_db
        categorizer = TransactionCategorizer(session, ml_config)
        categorizer.train()

        preds = categorizer.predict_with_confidence(transactions[:5])

        assert len(preds) == 5
        for pred in preds:
            assert isinstance(pred, TransactionPrediction)
            assert 0.0 <= pred.confidence_score <= 1.0
            assert pred.predicted_category_id > 0

    def test_train_fits_a_temperature_calibrator(self, seeded_db, ml_config):
        session, _ = seeded_db
        categorizer = TransactionCategorizer(session, ml_config)
        categorizer.train()

        assert categorizer.calibrator is not None
        assert categorizer.is_trained is True


# ---------------------------------------------------------------------------
# Tests — TransactionCategorizer.fit() (pre-split training)
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestTransactionCategorizerFit:
    """Tests for the pre-split fit() path."""

    def test_fit_trains_model(self, seeded_db, ml_config):
        session, transactions = seeded_db
        labels = _get_labels_for_transactions(session, transactions)
        categorizer = TransactionCategorizer(session, ml_config)

        categorizer.fit(transactions, labels)

        assert categorizer.is_trained is True
        assert categorizer.calibrator is not None

    def test_fit_enables_predictions(self, seeded_db, ml_config):
        session, transactions = seeded_db
        labels = _get_labels_for_transactions(session, transactions)
        categorizer = TransactionCategorizer(session, ml_config)
        categorizer.fit(transactions, labels)

        preds = categorizer.predict_with_confidence(transactions[:5])

        assert len(preds) == 5
        for pred in preds:
            assert isinstance(pred, TransactionPrediction)
            assert 0.0 <= pred.confidence_score <= 1.0


# ---------------------------------------------------------------------------
# Tests — EnsembleCategorizer
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestEnsembleCategorizerTraining:
    """Tests for the full ensemble training pipeline."""

    def test_ensemble_train_returns_results(self, seeded_db, ml_config):
        session, _ = seeded_db
        ensemble = EnsembleCategorizer(session, ml_config)

        results = ensemble.train()

        assert 0.0 <= results["oof_accuracy"] <= 1.0
        assert results["oof_logloss"] > 0.0
        assert 0.0 <= results["auto_rate"] <= 1.0
        assert results["temperature_lgbm"] > 0.0 and results["temperature_nb"] > 0.0
        assert ensemble.stack is not None and ensemble.lgbm_component.calibrator is not None
        assert set(results["stack_importance"]) >= {"lgbm_logp", "nb_logp", "rule_logp", "rule_hit"}

    def test_out_of_fold_scoring_derives_rules_from_the_other_folds_only(self, seeded_db, ml_config, monkeypatch):
        session, transactions = seeded_db
        derive = EnsembleCategorizer._training_split_rules
        seen: list[int] = []

        def spy(txns, labels):
            seen.append(len(txns))
            return derive(txns, labels)

        monkeypatch.setattr(EnsembleCategorizer, "_training_split_rules", staticmethod(spy))

        results = EnsembleCategorizer(session, ml_config).train()

        assert len(seen) == results["n_folds"], "one rule set per fold"
        # Each fold's rules must not see the rows they are scored against.
        assert all(n < results["n_training_samples"] for n in seen)
        assert seen[0] == pytest.approx((1 - 1 / results["n_folds"]) * results["n_training_samples"], abs=1)

    def test_ensemble_enables_predictions(self, seeded_db, ml_config):
        session, transactions = seeded_db
        ensemble = EnsembleCategorizer(session, ml_config)
        ensemble.train()

        preds = ensemble.predict_with_confidence(transactions[:5])

        assert len(preds) == 5
        for pred in preds:
            assert isinstance(pred, TransactionPrediction)
            assert 0.0 <= pred.confidence_score <= 1.0
            assert "nb_text_features" in pred.feature_contributions
            assert pred.detail is not None and pred.detail.source == "ensemble"
            assert len(pred.detail.meta_features) == 14
            assert sum(pred.detail.ensemble_probs.values()) == pytest.approx(1.0, abs=1e-3)  # rounded to 4 places

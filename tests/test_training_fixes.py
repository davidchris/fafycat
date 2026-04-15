"""Tests for training CV failure fix and log-noise fixes.

Covers:
- categorizer.fit() adapts calibration folds to the smallest class count,
  so training no longer crashes when a class has < 5 samples.
- LightGBM is configured with verbose=-1 (suppresses "no further splits" spam).
- fafycat.app installs a uvicorn access-log filter that drops /api/ml/training-status lines.
"""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import date

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from fafycat.app import _TrainingStatusAccessLogFilter
from fafycat.core.config import MLConfig
from fafycat.core.database import Base
from fafycat.core.models import TransactionInput
from fafycat.ml.categorizer import TransactionCategorizer


@pytest.fixture
def empty_session():
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        os.unlink(db_path)


def _txn(name: str, amount: float) -> TransactionInput:
    return TransactionInput(
        date=date(2026, 1, 1),
        value_date=None,
        name=name,
        purpose="purpose",
        amount=amount,
        currency="EUR",
    )


class TestLgbmVerboseConfig:
    def test_lgbm_params_has_verbose_minus_one(self):
        cfg = MLConfig()
        assert cfg.lgbm_params.get("verbose") == -1


class TestFitWithSmallClasses:
    """fit() must adapt cv folds when any class has < 5 samples."""

    @pytest.mark.slow
    def test_fit_succeeds_with_class_of_two(self, empty_session):
        # Two classes: one with 8 samples, one with only 2 samples.
        # Pre-fix this raised "Requesting 5-fold cross-validation but
        # provided less than 5 examples for at least one class."
        words_a = [
            "alpha",
            "bravo",
            "charlie",
            "delta",
            "echo",
            "foxtrot",
            "golf",
            "hotel",
            "india",
            "juliet",
            "kilo",
            "lima",
            "mike",
            "november",
            "oscar",
            "papa",
            "quebec",
            "romeo",
            "sierra",
            "tango",
            "uniform",
            "victor",
            "whiskey",
            "xray",
            "yankee",
            "zulu",
            "apple",
            "banana",
            "cherry",
            "date",
        ]
        words_b = [
            "employer",
            "payroll",
            "stipend",
            "wage",
            "salary",
            "income",
            "paycheck",
            "earnings",
            "compensation",
            "remuneration",
            "bonus",
            "commission",
            "dividend",
            "interest",
            "grant",
        ]
        transactions: list[TransactionInput] = []
        labels_list: list[int] = []
        # 30 samples of class 1 with varied merchant names
        for i, w in enumerate(words_a):
            transactions.append(_txn(f"shop {w} location {i}", -10.0 - i))
            labels_list.append(1)
        # Only 2 samples of class 2 — previously broke 5-fold CV
        transactions.append(_txn(f"{words_b[0]} {words_b[1]} monthly", 3000.0))
        labels_list.append(2)
        transactions.append(_txn(f"{words_b[2]} {words_b[3]} monthly", 3100.0))
        labels_list.append(2)
        labels = np.array(labels_list)

        cfg = MLConfig(svd_n_components=8)
        categorizer = TransactionCategorizer(empty_session, cfg)
        categorizer.fit(transactions, labels)

        assert categorizer.is_trained is True
        assert categorizer.calibrated_classifier is not None


class TestTrainingStatusLogFilter:
    def test_filter_drops_training_status_lines(self):
        f = _TrainingStatusAccessLogFilter()
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg='127.0.0.1:1234 - "GET /api/ml/training-status/abc HTTP/1.1" 200 OK',
            args=(),
            exc_info=None,
        )
        assert f.filter(record) is False

    def test_filter_keeps_other_lines(self):
        f = _TrainingStatusAccessLogFilter()
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg='127.0.0.1:1234 - "POST /api/ml/retrain HTTP/1.1" 200 OK',
            args=(),
            exc_info=None,
        )
        assert f.filter(record) is True

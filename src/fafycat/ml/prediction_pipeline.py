"""Prediction Pipeline: one owner of prediction, Strategic Selection, and Review Priority.

Takes stored transactions through prediction (via a passed-in Categorizer),
Strategic Selection, Review Priority bucketing against the Auto-approve
Threshold, and persists the outcome. Entry points commit before returning.
"""

from dataclasses import dataclass
from datetime import date
from typing import Protocol, cast

from sqlalchemy.orm import Session

from ..core.config import AppConfig
from ..core.database import AppSettingsORM, TransactionORM
from ..core.models import ReviewPriority, TransactionInput, TransactionPrediction
from .active_learning import ActiveLearningSelector

MAX_REVIEW_ITEMS = 20
"""Cap on Strategic Selection review items per pipeline run."""

DEFAULT_STRATEGY = "uncertainty"
"""Default Strategic Selection strategy."""


class ConfidenceCategorizer(Protocol):
    """The Categorizer seam: anything exposing confidence-scored prediction."""

    def predict_with_confidence(self, transactions: list[TransactionInput]) -> list[TransactionPrediction]: ...


@dataclass(frozen=True)
class CategorizationSummary:
    """Per-Review-Priority counts reported after one Prediction Pipeline run."""

    auto_accepted: int = 0
    quality_check: int = 0
    high: int = 0
    standard: int = 0

    @property
    def total(self) -> int:
        """Number of transactions the run predicted."""
        return self.auto_accepted + self.quality_check + self.high + self.standard


def get_auto_approve_threshold(db: Session) -> float:
    """Resolve the Auto-approve Threshold: DB setting with config fallback."""
    try:
        setting = db.query(AppSettingsORM).filter(AppSettingsORM.key == "auto_approve_threshold").first()
        if setting and setting.value is not None:
            return float(str(setting.value))
    except Exception:
        pass
    return AppConfig().ml.auto_approve_threshold


def predict_unpredicted(
    db: Session,
    categorizer: ConfidenceCategorizer,
    *,
    limit: int = 1000,
    threshold: float | None = None,
    strategy: str = DEFAULT_STRATEGY,
) -> tuple[CategorizationSummary, int]:
    """Predict transactions that have no Prediction yet.

    Returns the Categorization Summary and the number of matching
    transactions left unprocessed because of ``limit``. Commits.
    """
    query = db.query(TransactionORM).filter(TransactionORM.predicted_category_id.is_(None))
    txns, remaining = _select_with_limit(query, limit)
    return _apply_predictions(db, txns, categorizer, threshold=threshold, strategy=strategy), remaining


def predict_new(
    db: Session,
    categorizer: ConfidenceCategorizer,
    transaction_ids: list[str],
    *,
    threshold: float | None = None,
    strategy: str = DEFAULT_STRATEGY,
) -> CategorizationSummary:
    """Predict newly imported transactions that are not yet predicted.

    Returns the Categorization Summary. Commits.
    """
    txns = (
        db.query(TransactionORM)
        .filter(
            TransactionORM.id.in_(transaction_ids),
            TransactionORM.predicted_category_id.is_(None),
        )
        .all()
    )
    return _apply_predictions(db, txns, categorizer, threshold=threshold, strategy=strategy)


def repredict_unreviewed(
    db: Session,
    categorizer: ConfidenceCategorizer,
    *,
    limit: int = 1000,
    threshold: float | None = None,
    strategy: str = DEFAULT_STRATEGY,
) -> tuple[CategorizationSummary, int]:
    """Re-predict unreviewed transactions that already have a Prediction.

    Returns the Categorization Summary and the number of matching
    transactions left unprocessed because of ``limit``. Commits.
    """
    query = db.query(TransactionORM).filter(
        TransactionORM.is_reviewed.is_(False),
        TransactionORM.predicted_category_id.is_not(None),
    )
    txns, remaining = _select_with_limit(query, limit)
    return _apply_predictions(db, txns, categorizer, threshold=threshold, strategy=strategy), remaining


def _select_with_limit(query, limit: int) -> tuple[list[TransactionORM], int]:
    """Fetch up to ``limit`` matches and count how many are left beyond it.

    A failing selection query (e.g. missing table in a fresh database) is
    treated as "nothing to predict" rather than an error.
    """
    try:
        total_matching = query.count()
        txns = query.limit(limit).all()
    except Exception:
        return [], 0
    return txns, max(0, total_matching - len(txns))


def _to_input(txn: TransactionORM) -> TransactionInput:
    return TransactionInput(
        date=cast(date, txn.date),
        value_date=cast(date, txn.value_date or txn.date),
        name=str(txn.name),
        purpose=str(txn.purpose or ""),
        amount=cast(float, txn.amount),
        currency=str(txn.currency),
    )


def _apply_predictions(
    db: Session,
    txns: list[TransactionORM],
    categorizer: ConfidenceCategorizer,
    *,
    threshold: float | None,
    strategy: str,
) -> CategorizationSummary:
    """Predict, run Strategic Selection, bucket, persist, and commit."""
    if not txns:
        return CategorizationSummary()

    predictions = categorizer.predict_with_confidence([_to_input(txn) for txn in txns])

    al_predictions = [
        TransactionPrediction(
            transaction_id=str(txn.id),
            predicted_category_id=prediction.predicted_category_id,
            confidence_score=prediction.confidence_score,
            feature_contributions=prediction.feature_contributions,
        )
        for txn, prediction in zip(txns, predictions, strict=True)
    ]
    selector = ActiveLearningSelector(db)
    strategic_selections = set(
        selector.select_for_review(
            al_predictions, max_items=min(MAX_REVIEW_ITEMS, len(al_predictions)), strategy=strategy
        )
    )

    if threshold is None:
        threshold = get_auto_approve_threshold(db)

    counts = {priority: 0 for priority in ReviewPriority}
    for txn, prediction in zip(txns, predictions, strict=True):
        priority = _bucket_transaction(txn, prediction, strategic_selections, threshold)
        counts[priority] += 1

    db.commit()
    return CategorizationSummary(
        auto_accepted=counts[ReviewPriority.AUTO_ACCEPTED],
        quality_check=counts[ReviewPriority.QUALITY_CHECK],
        high=counts[ReviewPriority.HIGH],
        standard=counts[ReviewPriority.STANDARD],
    )


def _bucket_transaction(
    txn: TransactionORM,
    prediction: TransactionPrediction,
    strategic_selections: set[str],
    threshold: float,
) -> ReviewPriority:
    """Write one transaction's Prediction and Review Priority; return the bucket."""
    txn.predicted_category_id = prediction.predicted_category_id
    txn.confidence_score = prediction.confidence_score

    if prediction.confidence_score >= threshold:
        if txn.id in strategic_selections:
            txn.is_reviewed = False
            txn.review_priority = ReviewPriority.QUALITY_CHECK
            return ReviewPriority.QUALITY_CHECK
        txn.category_id = prediction.predicted_category_id
        txn.is_reviewed = True
        txn.review_priority = ReviewPriority.AUTO_ACCEPTED
        return ReviewPriority.AUTO_ACCEPTED

    txn.is_reviewed = False
    if txn.id in strategic_selections:
        txn.review_priority = ReviewPriority.HIGH
        return ReviewPriority.HIGH
    txn.review_priority = ReviewPriority.STANDARD
    return ReviewPriority.STANDARD

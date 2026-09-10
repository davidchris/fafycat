"""Read models that tell the user whether the model is current and well calibrated.

Two questions, one module:

* *Is the model stale?* :func:`get_training_recency` counts the Review Events
  recorded since the active model was trained. That count is the review page's
  case for pressing "Retrain and re-predict the queue".
* *Is the Auto-approve Threshold set right?* :func:`get_calibration_report`
  splits reviewed transactions into confidence bands and reports how often the
  reviewer kept the predicted category. A band with near-perfect agreement is a
  band that is safe to auto-accept.

Both are read-only: nothing here writes or commits.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from sqlalchemy.orm import Session

from fafycat.core.audit_trail import ReviewActor
from fafycat.core.database import ModelMetadataORM, ReviewEventORM, TransactionORM
from fafycat.core.models import ReviewPriority
from fafycat.ml.prediction_pipeline import get_auto_approve_threshold

LABEL_ACTORS: frozenset[str] = frozenset(
    {
        ReviewActor.USER_REVIEW.value,
        ReviewActor.BULK_APPROVE.value,
        ReviewActor.IMPORT_LABEL.value,
        ReviewActor.PROPAGATION.value,
    }
)
"""Review Event actors that add training signal.

Auto-accepts are excluded: they copy the model's own Prediction back onto the
transaction and teach it nothing.
"""

CALIBRATION_BANDS: tuple[tuple[float, float], ...] = (
    (0.0, 0.5),
    (0.5, 0.8),
    (0.8, 0.9),
    (0.9, 0.95),
    (0.95, 1.0),
)
"""Confidence bands, lower bound inclusive. The top band includes 1.0."""


@dataclass(frozen=True)
class TrainingRecency:
    """How much the reviewer has taught the model since it was last trained."""

    last_trained_at: datetime | None
    """When the active model was trained, or None if no model was ever trained."""

    reviews_since_training: int
    """Review Events with training signal recorded after ``last_trained_at``."""

    def to_dict(self) -> dict:
        """Render as JSON-friendly fields for the ML status endpoint."""
        return {
            "last_trained_at": self.last_trained_at.isoformat() if self.last_trained_at else None,
            "reviews_since_training": self.reviews_since_training,
        }


@dataclass(frozen=True)
class CalibrationBand:
    """Review outcomes for the predictions that landed in one confidence band."""

    lower: float
    upper: float
    reviewed: int
    """Reviewed transactions in this band that carry both a category and a Prediction."""

    kept: int
    """Of those, how many ended up with the predicted category."""

    @property
    def overridden(self) -> int:
        """Reviewed transactions whose category differs from the Prediction."""
        return self.reviewed - self.kept

    @property
    def agreement_rate(self) -> float | None:
        """Share of reviews that kept the Prediction, or None when the band is empty."""
        return self.kept / self.reviewed if self.reviewed else None

    @property
    def label(self) -> str:
        """Band as an interval, e.g. ``0.90-0.95``."""
        return f"{self.lower:.2f}-{self.upper:.2f}"

    def to_dict(self) -> dict:
        """Render as JSON-friendly fields."""
        return {
            "lower": self.lower,
            "upper": self.upper,
            "label": self.label,
            "reviewed": self.reviewed,
            "kept": self.kept,
            "overridden": self.overridden,
            "agreement_rate": self.agreement_rate,
        }


@dataclass(frozen=True)
class CalibrationReport:
    """Evidence for where the Auto-approve Threshold belongs.

    Computed from the ``transactions`` table rather than from Prediction Events
    because it covers all history, including transactions reviewed before the
    Audit Trail existed. Two caveats come with that:

    * ``confidence_score`` holds the *latest* Prediction for a transaction,
      which is not necessarily the one the reviewer saw at the time.
    * Rows flagged reviewed but left without a category are skipped. They are
      not reviewer disagreements, and counting them as such badly distorts the
      high-confidence bands.
    """

    bands: tuple[CalibrationBand, ...]
    auto_accepted_overridden: int
    """Auto-accepted transactions the reviewer later corrected."""

    threshold: float
    """The Auto-approve Threshold in force, for marking the affected bands."""

    def to_dict(self) -> dict:
        """Render as JSON-friendly fields for the calibration endpoint."""
        return {
            "bands": [band.to_dict() for band in self.bands],
            "auto_accepted_overridden": self.auto_accepted_overridden,
            "threshold": self.threshold,
            "caveat": (
                "Confidence is the latest prediction's score, not necessarily "
                "the score shown when the transaction was reviewed."
            ),
        }


def get_training_recency(session: Session) -> TrainingRecency:
    """Report when the active model was trained and how much it has missed since.

    Args:
        session: Open database session.

    Returns:
        The training date of the active model (None if never trained) and the
        number of Review Events with training signal recorded after it. With no
        trained model every such event counts.
    """
    active_model = (
        session.query(ModelMetadataORM)
        .filter(ModelMetadataORM.is_active)
        .order_by(ModelMetadataORM.training_date.desc())
        .first()
    )
    last_trained_at = _as_utc(cast(datetime | None, active_model.training_date)) if active_model else None

    query = session.query(ReviewEventORM).filter(ReviewEventORM.actor.in_(LABEL_ACTORS))
    if last_trained_at is not None:
        query = query.filter(ReviewEventORM.created_at > _as_naive(last_trained_at))

    return TrainingRecency(last_trained_at=last_trained_at, reviews_since_training=query.count())


def get_calibration_report(session: Session) -> CalibrationReport:
    """Measure how often reviewers kept the Prediction, per confidence band.

    Args:
        session: Open database session.

    Returns:
        One :class:`CalibrationBand` per entry in :data:`CALIBRATION_BANDS`,
        the number of auto-accepted transactions later corrected, and the
        Auto-approve Threshold currently in force.
    """
    rows = (
        session.query(
            TransactionORM.confidence_score,
            TransactionORM.category_id,
            TransactionORM.predicted_category_id,
        )
        .filter(
            TransactionORM.is_reviewed.is_(True),
            TransactionORM.category_id.is_not(None),
            TransactionORM.predicted_category_id.is_not(None),
            TransactionORM.confidence_score.is_not(None),
        )
        .all()
    )

    reviewed = [0] * len(CALIBRATION_BANDS)
    kept = [0] * len(CALIBRATION_BANDS)
    for confidence, category_id, predicted_category_id in rows:
        index = _band_index(float(confidence))
        reviewed[index] += 1
        if category_id == predicted_category_id:
            kept[index] += 1

    auto_accepted_overridden = (
        session.query(TransactionORM)
        .filter(
            TransactionORM.is_reviewed.is_(True),
            TransactionORM.review_priority == ReviewPriority.AUTO_ACCEPTED.value,
            TransactionORM.predicted_category_id.is_not(None),
            TransactionORM.category_id != TransactionORM.predicted_category_id,
        )
        .count()
    )

    return CalibrationReport(
        bands=tuple(
            CalibrationBand(lower=lower, upper=upper, reviewed=reviewed[i], kept=kept[i])
            for i, (lower, upper) in enumerate(CALIBRATION_BANDS)
        ),
        auto_accepted_overridden=auto_accepted_overridden,
        threshold=get_auto_approve_threshold(session),
    )


def _band_index(confidence: float) -> int:
    """Return the index in :data:`CALIBRATION_BANDS` holding ``confidence``."""
    for index, (lower, upper) in enumerate(CALIBRATION_BANDS):
        if lower <= confidence < upper:
            return index
    return len(CALIBRATION_BANDS) - 1


def _as_utc(value: datetime | None) -> datetime | None:
    """Tag a naive timestamp as UTC; SQLite drops the timezone on write."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _as_naive(value: datetime) -> datetime:
    """Strip the timezone again so SQLite compares it against stored values."""
    return value.replace(tzinfo=None)

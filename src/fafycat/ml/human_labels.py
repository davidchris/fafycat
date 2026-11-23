"""Which transaction categories a human decided, and which ones training may trust.

An auto-accept or a bulk approve copies the model's own Prediction onto the
transaction. Grading the model on those rows would make every band above the
Auto-approve Threshold agree with itself by construction, so the calibration
table and the training metrics use Human Labels only.

Training and the Merchant Rules also learn from Trusted Auto-accepts: an
auto-accept nobody corrected for :data:`TRUSTED_AUTO_ACCEPT_MIN_AGE`. Without
them the model loses exactly the recurring merchants it auto-accepts (rent,
salary, utilities), because a human never had to label those again. They train
at :data:`AUTO_ACCEPT_LABEL_WEIGHT`, below a Human Label, and Spot Checks keep
measuring how often they are wrong. See ``docs/adr/0001-train-on-trusted-auto-accepts.md``.

The Audit Trail records who set each category, so the latest Review Event of a
transaction names its decider. Transactions categorised before the Audit Trail
existed carry no Review Event; for those the ``review_priority`` column is the
only clue, see :func:`human_label_criterion`.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, and_, exists, func, or_, select
from sqlalchemy.orm import Session

from ..core.audit_trail import ReviewActor
from ..core.database import ReviewEventORM, TransactionORM
from ..core.models import ReviewPriority

HUMAN_LABEL_ACTORS: frozenset[str] = frozenset(
    {
        ReviewActor.USER_REVIEW.value,
        ReviewActor.IMPORT_LABEL.value,
        ReviewActor.PROPAGATION.value,
    }
)
"""Review Event actors whose category is a human decision.

A propagation applies a category the reviewer just chose to its siblings, so
it counts. Auto-accepts and bulk approves copy the model's Prediction and do
not.
"""


TRUSTED_AUTO_ACCEPT_MIN_AGE = timedelta(days=14)
"""How long an auto-accept must stand uncorrected before training trusts it.

About half a monthly import cycle: long enough for the reviewer to have seen
the import, short enough that the next import's retrain learns from it.
"""

HUMAN_LABEL_WEIGHT = 1.0
"""Training weight of a Human Label; only rows of this weight grade the model."""

AUTO_ACCEPT_LABEL_WEIGHT = 0.5
"""Training weight of a Trusted Auto-accept."""


def _latest_event(column):
    """Correlated subquery: ``column`` of the transaction's latest Review Event."""
    latest_event_id = (
        select(func.max(ReviewEventORM.id))
        .where(ReviewEventORM.transaction_id == TransactionORM.id)
        .correlate(TransactionORM)
        .scalar_subquery()
    )
    return select(column).where(ReviewEventORM.id == latest_event_id).scalar_subquery()


def _has_events() -> ColumnElement[bool]:
    return exists().where(ReviewEventORM.transaction_id == TransactionORM.id)


def _labelled() -> ColumnElement[bool]:
    return and_(TransactionORM.is_reviewed.is_(True), TransactionORM.category_id.is_not(None))


def human_label_criterion() -> ColumnElement[bool]:
    """Filter for transactions whose current category a human decided.

    A transaction qualifies when it is reviewed, has a category, and either:

    * its latest Review Event has an actor in :data:`HUMAN_LABEL_ACTORS`, or
    * it has no Review Event (it predates the Audit Trail) and it is not a
      legacy auto-accept. A legacy row with Review Priority ``auto_accepted``
      counts only when its category differs from its Prediction: auto-accept
      wrote the Prediction as the category, and no prediction path rewrites the
      Prediction of a reviewed transaction, so a difference means a reviewer
      corrected it.

    Returns:
        A SQLAlchemy criterion on :class:`TransactionORM`.
    """
    legacy_human = and_(
        ~_has_events(),
        or_(
            TransactionORM.review_priority.is_(None),
            TransactionORM.review_priority != ReviewPriority.AUTO_ACCEPTED.value,
            TransactionORM.category_id != TransactionORM.predicted_category_id,
        ),
    )
    return and_(_labelled(), or_(_latest_event(ReviewEventORM.actor).in_(HUMAN_LABEL_ACTORS), legacy_human))


def trusted_auto_accept_criterion(now: datetime | None = None) -> ColumnElement[bool]:
    """Filter for auto-accepts that stood uncorrected long enough to train on.

    A transaction qualifies when it is reviewed, has a category, and either:

    * its latest Review Event is an auto-accept at least
      :data:`TRUSTED_AUTO_ACCEPT_MIN_AGE` old, or
    * it has no Review Event (it predates the Audit Trail) and is a legacy
      auto-accept nobody changed: its category still equals its Prediction.

    A correction makes the latest Review Event a human one, so a corrected
    auto-accept is a Human Label instead. Bulk approves never qualify: they
    can copy Predictions below the Auto-approve Threshold.

    Args:
        now: The current time; defaults to now in UTC.

    Returns:
        A SQLAlchemy criterion on :class:`TransactionORM`.
    """
    cutoff = (now or datetime.now(UTC)).astimezone(UTC).replace(tzinfo=None) - TRUSTED_AUTO_ACCEPT_MIN_AGE
    aged_auto_accept = and_(
        _latest_event(ReviewEventORM.actor) == ReviewActor.AUTO_ACCEPT.value,
        _latest_event(ReviewEventORM.created_at) <= cutoff,
    )
    legacy_auto_accept = and_(
        ~_has_events(),
        TransactionORM.review_priority == ReviewPriority.AUTO_ACCEPTED.value,
        TransactionORM.category_id == TransactionORM.predicted_category_id,
    )
    return and_(_labelled(), or_(aged_auto_accept, legacy_auto_accept))


def training_label_criterion(now: datetime | None = None) -> ColumnElement[bool]:
    """Filter for every transaction training and the Merchant Rules learn from.

    Args:
        now: The current time; defaults to now in UTC.

    Returns:
        Human Labels or Trusted Auto-accepts, as a criterion on :class:`TransactionORM`.
    """
    return or_(human_label_criterion(), trusted_auto_accept_criterion(now))


def training_labels(session: Session, now: datetime | None = None) -> list[tuple[TransactionORM, float]]:
    """Every training transaction with its training weight.

    Args:
        session: Database session.
        now: The current time; defaults to now in UTC.

    Returns:
        ``(transaction, weight)`` pairs: :data:`HUMAN_LABEL_WEIGHT` for a Human
        Label and :data:`AUTO_ACCEPT_LABEL_WEIGHT` for a Trusted Auto-accept.
    """
    rows = (
        session.query(TransactionORM, human_label_criterion())
        .filter(training_label_criterion(now))
        .order_by(TransactionORM.id)
        .all()
    )
    return [(txn, HUMAN_LABEL_WEIGHT if is_human else AUTO_ACCEPT_LABEL_WEIGHT) for txn, is_human in rows]


def count_training_labels(session: Session) -> int:
    """Count the transactions training would learn from.

    Training readiness must use this count, not every reviewed transaction:
    otherwise fresh auto-accepts and bulk approves advertise a training set
    that training then rejects.

    Args:
        session: Database session.

    Returns:
        The number of Human Labels plus Trusted Auto-accepts.
    """
    return session.query(TransactionORM).filter(training_label_criterion()).count()

"""Which transaction categories a human decided.

Training, the Merchant Rules, and the calibration table must learn from human
decisions only. An auto-accept or a bulk approve copies the model's own
Prediction onto the transaction; feeding it back would let each retrain learn
the previous model's confident guesses, and would make every band above the
Auto-approve Threshold agree with itself by construction.

The Audit Trail records who set each category, so the latest Review Event of a
transaction names its decider. Transactions categorised before the Audit Trail
existed carry no Review Event; for those the ``review_priority`` column is the
only clue, see :func:`human_label_criterion`.
"""

from sqlalchemy import ColumnElement, and_, exists, func, or_, select

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
    latest_event_id = (
        select(func.max(ReviewEventORM.id))
        .where(ReviewEventORM.transaction_id == TransactionORM.id)
        .correlate(TransactionORM)
        .scalar_subquery()
    )
    latest_actor = select(ReviewEventORM.actor).where(ReviewEventORM.id == latest_event_id).scalar_subquery()
    has_events = exists().where(ReviewEventORM.transaction_id == TransactionORM.id)
    legacy_human = and_(
        ~has_events,
        or_(
            TransactionORM.review_priority.is_(None),
            TransactionORM.review_priority != ReviewPriority.AUTO_ACCEPTED.value,
            TransactionORM.category_id != TransactionORM.predicted_category_id,
        ),
    )
    return and_(
        TransactionORM.is_reviewed.is_(True),
        TransactionORM.category_id.is_not(None),
        or_(latest_actor.in_(HUMAN_LABEL_ACTORS), legacy_human),
    )

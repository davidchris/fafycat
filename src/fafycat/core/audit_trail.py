"""Audit Trail: append-only record of how every transaction got its category.

Two event streams, both keyed by transaction:

* Prediction Events: one per Prediction Pipeline run, holding what the
  Merchant Rule, LightGBM, and Naive Bayes each proposed, the ensemble
  weights, and the decision against the Auto-approve Threshold.
* Review Events: one per category assignment, naming the actor (the
  reviewer, an auto-accept, a bulk approve, a labelled import, or a
  correction propagated from a sibling transaction).

Writers add rows to the session and leave committing to the caller, so an
event is persisted in the same transaction as the change it describes.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import cast

from sqlalchemy.orm import Session

from .database import CategoryORM, PredictionEventORM, ReviewEventORM, TransactionORM
from .models import ReviewPriority, TransactionPrediction


class ReviewActor(StrEnum):
    """Who set a category on a transaction."""

    USER_REVIEW = "user_review"
    AUTO_ACCEPT = "auto_accept"
    BULK_APPROVE = "bulk_approve"
    IMPORT_LABEL = "import_label"
    PROPAGATION = "propagation"


def record_prediction_event(
    db: Session,
    txn: TransactionORM,
    prediction: TransactionPrediction,
    *,
    trigger: str,
    model_id: str,
    threshold: float,
    decision: ReviewPriority,
) -> PredictionEventORM:
    """Add a Prediction Event for one transaction. Does not commit."""
    detail = prediction.detail
    event = PredictionEventORM(
        transaction_id=txn.id,
        trigger=trigger,
        model_id=model_id,
        threshold=threshold,
        decision=decision.value,
        source=detail.source if detail else "unknown",
        final_category_id=prediction.predicted_category_id,
        final_confidence=prediction.confidence_score,
        rule_pattern=detail.rule_pattern if detail else None,
        rule_category_id=detail.rule_category_id if detail else None,
        rule_confidence=detail.rule_confidence if detail else None,
        lgbm_weight=detail.lgbm_weight if detail else None,
        nb_weight=detail.nb_weight if detail else None,
        rule_weight=detail.rule_weight if detail else None,
        lgbm_probs=json.dumps(detail.lgbm_probs) if detail else None,
        nb_probs=json.dumps(detail.nb_probs) if detail else None,
        rule_probs=json.dumps(detail.rule_probs) if detail and detail.rule_probs else None,
        ensemble_probs=json.dumps(detail.ensemble_probs) if detail else None,
        feature_contributions=json.dumps(prediction.feature_contributions),
    )
    db.add(event)
    return event


def record_review_event(
    db: Session,
    txn: TransactionORM,
    *,
    actor: ReviewActor,
    from_category_id: int | None,
    to_category_id: int,
    note: str | None = None,
) -> ReviewEventORM:
    """Add a Review Event for one transaction. Does not commit."""
    event = ReviewEventORM(
        transaction_id=txn.id,
        actor=actor.value,
        from_category_id=from_category_id,
        to_category_id=to_category_id,
        predicted_category_id=txn.predicted_category_id,
        confidence_score=txn.confidence_score,
        note=note,
    )
    db.add(event)
    return event


@dataclass(frozen=True)
class Ranked:
    """A category with its probability, for display."""

    category_id: int
    category: str
    probability: float


@dataclass(frozen=True)
class PredictionEventView:
    """A Prediction Event with category ids resolved to names."""

    created_at: datetime
    trigger: str
    model_id: str
    threshold: float
    decision: str
    source: str
    final_category: str
    final_confidence: float
    rule_pattern: str | None
    rule_category: str | None
    rule_confidence: float | None
    lgbm_weight: float | None
    nb_weight: float | None
    rule_weight: float | None = None
    lgbm_top: list[Ranked] = field(default_factory=list)
    nb_top: list[Ranked] = field(default_factory=list)
    rule_top: list[Ranked] = field(default_factory=list)
    ensemble_top: list[Ranked] = field(default_factory=list)
    feature_contributions: dict[str, float] = field(default_factory=dict)

    kind: str = "prediction"


@dataclass(frozen=True)
class ReviewEventView:
    """A Review Event with category ids resolved to names."""

    created_at: datetime
    actor: str
    from_category: str | None
    to_category: str
    predicted_category: str | None
    confidence_score: float | None
    note: str | None

    kind: str = "review"


@dataclass(frozen=True)
class TransactionTrail:
    """Everything the Audit Trail knows about one transaction, newest first."""

    transaction: TransactionORM
    category: str | None
    predicted_category: str | None
    events: list[PredictionEventView | ReviewEventView]


TOP_N = 5


def get_trail(db: Session, transaction_id: str) -> TransactionTrail | None:
    """Assemble the Audit Trail for one transaction, or None if it doesn't exist."""
    txn = db.query(TransactionORM).filter(TransactionORM.id == transaction_id).first()
    if txn is None:
        return None

    names = {int(cast(int, c.id)): str(c.name) for c in db.query(CategoryORM).all()}

    def name(category_id: object) -> str | None:
        return names.get(int(cast(int, category_id)), f"#{category_id}") if category_id is not None else None

    def top(raw: object) -> list[Ranked]:
        probs: dict[str, float] = json.loads(str(raw)) if raw else {}
        ranked = sorted(probs.items(), key=lambda kv: kv[1], reverse=True)[:TOP_N]
        return [Ranked(int(cid), name(int(cid)) or f"#{cid}", p) for cid, p in ranked]

    events: list[PredictionEventView | ReviewEventView] = []
    for e in db.query(PredictionEventORM).filter(PredictionEventORM.transaction_id == transaction_id).all():
        events.append(
            PredictionEventView(
                created_at=cast(datetime, e.created_at),
                trigger=str(e.trigger),
                model_id=str(e.model_id),
                threshold=cast(float, e.threshold),
                decision=str(e.decision),
                source=str(e.source),
                final_category=name(e.final_category_id) or "?",
                final_confidence=cast(float, e.final_confidence),
                rule_pattern=cast(str | None, e.rule_pattern),
                rule_category=name(e.rule_category_id),
                rule_confidence=cast(float | None, e.rule_confidence),
                lgbm_weight=cast(float | None, e.lgbm_weight),
                nb_weight=cast(float | None, e.nb_weight),
                rule_weight=cast(float | None, e.rule_weight),
                lgbm_top=top(e.lgbm_probs),
                nb_top=top(e.nb_probs),
                rule_top=top(e.rule_probs),
                ensemble_top=top(e.ensemble_probs),
                feature_contributions=json.loads(str(e.feature_contributions)) if e.feature_contributions else {},
            )
        )
    for r in db.query(ReviewEventORM).filter(ReviewEventORM.transaction_id == transaction_id).all():
        events.append(
            ReviewEventView(
                created_at=cast(datetime, r.created_at),
                actor=str(r.actor),
                from_category=name(r.from_category_id),
                to_category=name(r.to_category_id) or "?",
                predicted_category=name(r.predicted_category_id),
                confidence_score=cast(float | None, r.confidence_score),
                note=cast(str | None, r.note),
            )
        )
    events.sort(key=lambda ev: ev.created_at, reverse=True)

    return TransactionTrail(
        transaction=txn,
        category=name(txn.category_id),
        predicted_category=name(txn.predicted_category_id),
        events=events,
    )

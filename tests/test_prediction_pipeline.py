"""Unit tests for the Prediction Pipeline module.

Drives the entry-point verbs with a fake Categorizer (scripted confidence
scores) on an in-memory database. The real Strategic Selection implementation
is used, not mocked.

Determinism note: ActiveLearningSelector's uncertainty strategy random-samples
from the medium (0.7-0.9) and high (>0.9) confidence pools. All scripted
scores stay below 0.7 so Strategic Selection deterministically picks the
``int(0.7 * max_items)`` lowest-confidence transactions. Threshold overrides
steer which Review Priority buckets those selections land in.
"""

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from fafycat.core.database import AppSettingsORM, Base, CategoryORM, TransactionORM
from fafycat.core.models import ReviewPriority, TransactionInput, TransactionPrediction
from fafycat.ml.prediction_pipeline import get_auto_approve_threshold, predict_unpredicted


class FakeCategorizer:
    """Categorizer test double with scripted confidence scores keyed by transaction name."""

    def __init__(self, scores_by_name: dict[str, float], predicted_category_id: int = 1):
        self.scores_by_name = scores_by_name
        self.predicted_category_id = predicted_category_id

    def predict_with_confidence(self, transactions: list[TransactionInput]) -> list[TransactionPrediction]:
        return [
            TransactionPrediction(
                transaction_id=txn.generate_id(),
                predicted_category_id=self.predicted_category_id,
                confidence_score=self.scores_by_name[txn.name],
                feature_contributions={"merchant_name": 1.0},
            )
            for txn in transactions
        ]


@pytest.fixture
def session() -> Session:
    """In-memory database session that keeps python attribute state after commit."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    session.add(CategoryORM(id=1, name="groceries", type="spending", budget=0.0, is_active=True))
    session.commit()
    yield session
    session.close()
    engine.dispose()


def make_txn(name: str, **overrides) -> TransactionORM:
    defaults = dict(
        id=f"id-{name}",
        date=date(2024, 3, 1),
        value_date=date(2024, 3, 1),
        name=name,
        purpose="purpose",
        amount=-10.0,
        currency="EUR",
        category_id=None,
        predicted_category_id=None,
        confidence_score=None,
        is_reviewed=False,
        imported_at=datetime(2024, 3, 1, 12, 0),
        import_batch="batch",
    )
    defaults.update(overrides)
    return TransactionORM(**defaults)


def test_predict_unpredicted_auto_accepts_confident_prediction(session: Session) -> None:
    """A single high-confidence, unselected transaction is auto-accepted and persisted."""
    txn = make_txn("solo")
    session.add(txn)
    session.commit()

    # max_items=1: n_uncertain=int(0.7)=0, no medium/high pools below 0.7 -> nothing selected
    categorizer = FakeCategorizer({"solo": 0.60})
    summary, remaining = predict_unpredicted(session, categorizer, threshold=0.50)

    assert summary.auto_accepted == 1
    assert summary.total == 1
    assert remaining == 0
    assert txn.predicted_category_id == 1
    assert txn.confidence_score == 0.60
    assert txn.category_id == 1
    assert txn.is_reviewed is True


# With two transactions max_items=2 and n_uncertain=int(1.4)=1: exactly the
# lowest-confidence transaction is strategically selected.
BUCKETING_MATRIX = [
    # (scores, threshold, expected buckets by name)
    pytest.param(
        {"low": 0.30, "confident": 0.60},
        0.50,
        {"low": "high", "confident": "auto_accepted"},
        id="selected-below-threshold-is-high, unselected-at-or-above-auto-accepts",
    ),
    pytest.param(
        {"low": 0.30, "mid": 0.40},
        0.50,
        {"low": "high", "mid": "standard"},
        id="unselected-below-threshold-is-standard",
    ),
    pytest.param(
        {"mid": 0.40, "confident": 0.60},
        0.35,
        {"mid": "quality_check", "confident": "auto_accepted"},
        id="selected-at-or-above-threshold-is-quality-check",
    ),
]


@pytest.mark.parametrize(("scores", "threshold", "expected"), BUCKETING_MATRIX)
def test_bucketing_matrix(
    session: Session, scores: dict[str, float], threshold: float, expected: dict[str, str]
) -> None:
    """All four Review Priority outcomes fall out of confidence x Strategic Selection."""
    for name in scores:
        session.add(make_txn(name))
    session.commit()

    summary, _ = predict_unpredicted(session, FakeCategorizer(scores), threshold=threshold)

    by_name = {str(t.name): t for t in session.query(TransactionORM).all()}
    for name, bucket in expected.items():
        txn = by_name[name]
        assert txn.review_priority == bucket, f"{name}: expected {bucket}, got {txn.review_priority}"
        assert txn.is_reviewed is (bucket == "auto_accepted")

    expected_counts = {bucket: list(expected.values()).count(bucket) for bucket in expected.values()}
    for bucket, count in expected_counts.items():
        assert getattr(summary, bucket) == count
    assert summary.total == len(scores)


def test_score_exactly_at_threshold_auto_accepts(session: Session) -> None:
    """The threshold boundary is inclusive: score == threshold auto-accepts."""
    session.add(make_txn("low"))
    session.add(make_txn("boundary"))
    session.commit()

    summary, _ = predict_unpredicted(session, FakeCategorizer({"low": 0.30, "boundary": 0.50}), threshold=0.50)

    assert summary.auto_accepted == 1
    boundary = session.query(TransactionORM).filter(TransactionORM.name == "boundary").one()
    assert boundary.review_priority == "auto_accepted"


def test_persisted_review_priorities_are_enum_members(session: Session) -> None:
    """Regression: the pipeline writes ReviewPriority enum members, not ad-hoc strings."""
    scores = {"a": 0.30, "b": 0.40, "c": 0.45, "d": 0.60}
    # Hold strong references: the session's identity map is weak, and a GC'd
    # instance would be re-loaded from the DB as a plain string either way.
    txns = [make_txn(name) for name in scores]
    session.add_all(txns)
    session.commit()

    predict_unpredicted(session, FakeCategorizer(scores), threshold=0.50)

    for txn in txns:
        # expire_on_commit=False keeps the python objects the pipeline assigned
        assert isinstance(txn.review_priority, ReviewPriority), (
            f"{txn.name}: got {txn.review_priority!r} ({type(txn.review_priority).__name__})"
        )
    stored = [row[0] for row in session.query(TransactionORM.review_priority).all()]
    valid_values = {member.value for member in ReviewPriority}
    assert set(stored) <= valid_values


def test_unpredicted_predicate_skips_transactions_with_predictions(session: Session) -> None:
    """Only transactions without a Prediction are selected; existing Predictions are untouched."""
    session.add(make_txn("fresh"))
    session.add(make_txn("already-predicted", predicted_category_id=1, confidence_score=0.99))
    session.commit()

    summary, remaining = predict_unpredicted(session, FakeCategorizer({"fresh": 0.60}), threshold=0.50)

    assert summary.total == 1
    assert remaining == 0
    untouched = session.query(TransactionORM).filter(TransactionORM.name == "already-predicted").one()
    assert untouched.confidence_score == 0.99
    assert untouched.review_priority == "standard"  # column default, never rewritten


def test_limit_and_remaining_unpredicted_rule(session: Session) -> None:
    """remaining = matching transactions beyond the limit; limited run predicts exactly `limit`."""
    scores = {f"t{i}": 0.60 for i in range(5)}
    for name in scores:
        session.add(make_txn(name))
    session.commit()

    summary, remaining = predict_unpredicted(session, FakeCategorizer(scores), limit=3, threshold=0.50)

    assert summary.total == 3
    assert remaining == 2

    summary2, remaining2 = predict_unpredicted(session, FakeCategorizer(scores), limit=3, threshold=0.50)
    assert summary2.total == 2
    assert remaining2 == 0


def test_threshold_resolves_from_db_setting_when_not_overridden(session: Session) -> None:
    """Without an override kwarg, the Auto-approve Threshold comes from the DB setting."""
    session.add(AppSettingsORM(key="auto_approve_threshold", value="0.55"))
    session.add(make_txn("just-below"))
    session.add(make_txn("just-above"))
    session.commit()

    summary, _ = predict_unpredicted(session, FakeCategorizer({"just-below": 0.30, "just-above": 0.60}))

    assert get_auto_approve_threshold(session) == 0.55
    above = session.query(TransactionORM).filter(TransactionORM.name == "just-above").one()
    assert above.review_priority == "auto_accepted"
    below = session.query(TransactionORM).filter(TransactionORM.name == "just-below").one()
    assert below.review_priority == "high"  # selected as the lowest-confidence item

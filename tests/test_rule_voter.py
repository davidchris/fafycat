"""The Merchant Rule as the ensemble's third voter: its vote and how the stack records it."""

from datetime import date
from types import SimpleNamespace

import numpy as np
import pytest

from fafycat.core.config import MLConfig
from fafycat.core.models import MerchantMapping, TransactionInput
from fafycat.ml.calibration import TemperatureScaler
from fafycat.ml.ensemble_categorizer import EnsembleCategorizer, rule_probability_vector, rule_votes
from fafycat.ml.merchant_mapper import MerchantRuleSet, derive_rules
from fafycat.ml.stack import META_NAMES, Voters

CLASS_IDS = [1, 2, 3]


def _rule(category_id: int, confidence: float = 0.9) -> MerchantMapping:
    return MerchantMapping(merchant_pattern="REWE", category_id=category_id, confidence=confidence)


def _txn(name: str, day: int = 4) -> TransactionInput:
    return TransactionInput(date=date(2026, 8, day), name=name, purpose="", amount=-12.5, currency="EUR")


class TestRuleVote:
    def test_match_keeps_its_confidence_and_spreads_the_rest_evenly(self):
        vote = rule_probability_vector(_rule(category_id=2, confidence=0.9), CLASS_IDS)

        assert vote == pytest.approx([0.05, 0.9, 0.05])
        assert vote.sum() == pytest.approx(1.0)

    def test_no_match_does_not_vote(self):
        assert rule_probability_vector(None, CLASS_IDS) is None

    def test_category_the_ensemble_never_saw_does_not_vote(self):
        assert rule_probability_vector(_rule(category_id=99), CLASS_IDS) is None

    def test_single_category_ensemble_votes_all_in(self):
        assert rule_probability_vector(_rule(category_id=1), [1]) == pytest.approx([1.0])

    def test_votes_mark_which_transactions_a_rule_spoke_for(self):
        rule_set = MerchantRuleSet({"REWE": (2, 0.9)})

        matches, votes, voted = rule_votes(rule_set, [_txn("REWE"), _txn("Fielmann")], CLASS_IDS)

        assert [m.category_id if m else None for m in matches] == [2, None]
        assert voted.tolist() == [True, False]
        assert votes[0] == pytest.approx([0.05, 0.9, 0.05])
        assert votes[1] == pytest.approx([0.0, 0.0, 0.0])


class TestLeakageFreeRules:
    """Rules that score the validation split must come from the training split."""

    def test_a_merchant_seen_only_in_held_out_rows_forms_no_rule(self):
        train = [_txn("REWE"), _txn("REWE"), _txn("REWE")]
        held_out = [_txn("Fielmann"), _txn("Fielmann"), _txn("Fielmann")]
        labels = np.array([1, 1, 1])

        training_rules = EnsembleCategorizer._training_split_rules(train, labels)
        all_rules = derive_rules([(t.name, 1, t.date) for t in train + held_out])

        assert "FIELMANN" in all_rules, "the held-out rows alone would form a rule"
        assert training_rules.get_category("Fielmann") is None
        assert training_rules.get_category("REWE") is not None

    def test_rules_follow_the_labels_of_the_split_they_were_derived_from(self):
        train = [_txn("REWE"), _txn("REWE"), _txn("REWE")]

        rules = EnsembleCategorizer._training_split_rules(train, np.array([7, 7, 7]))

        match = rules.get_category("REWE")
        assert match is not None and match.category_id == 7


class _FakeComponent:
    """A trained component reduced to the fixed probabilities it reports."""

    def __init__(self, probabilities: list[float], classes: list[int]):
        self.probabilities = np.array(probabilities)
        self.classes_ = np.array(classes)
        self.classifier = SimpleNamespace()  # no feature_importances_, so contributions stay short
        self.feature_names: list[str] = []
        self.merchant_mapper = SimpleNamespace(rule_set=MerchantRuleSet({}), reload=lambda: None)

    def predict_proba(self, transactions: list[TransactionInput]) -> np.ndarray:
        return np.tile(self.probabilities, (len(transactions), 1))


class _MeanStack:
    """A stand-in level-1 model: the plain mean of the three voters' distributions."""

    def __init__(self) -> None:
        self.seen: list[Voters] = []

    def predict_proba(self, voters: Voters) -> np.ndarray:
        self.seen.append(voters)
        return (voters.lgbm + voters.nb + voters.rule_probs()) / 3


def _ensemble(db_session, rules: dict[str, tuple[int, float]]) -> EnsembleCategorizer:
    ensemble = EnsembleCategorizer(db_session, MLConfig())
    ensemble.lgbm_component = _FakeComponent([0.6, 0.3, 0.1], CLASS_IDS)
    ensemble.lgbm_component.merchant_mapper.rule_set = MerchantRuleSet(rules)
    ensemble.nb_component = _FakeComponent([0.2, 0.7, 0.1], CLASS_IDS)
    ensemble.nb_temperature = TemperatureScaler()  # T = 1: leaves the fake probabilities alone
    ensemble.stack = _MeanStack()
    ensemble.seen_counts = {"REWE": 4}
    ensemble.classes_ = np.array(CLASS_IDS)
    ensemble.is_trained = True
    return ensemble


class TestEnsemblePrediction:
    def test_prediction_detail_carries_every_vote_and_the_meta_features(self, db_session):
        ensemble = _ensemble(db_session, {"REWE": (3, 0.9)})

        detail = ensemble.predict_with_confidence([_txn("REWE")])[0].detail

        assert detail is not None
        assert detail.source == "ensemble"
        assert detail.rule_pattern == "REWE" and detail.rule_category_id == 3
        assert detail.rule_probs == {1: 0.05, 2: 0.05, 3: 0.9}
        assert detail.lgbm_probs == pytest.approx({1: 0.6, 2: 0.3, 3: 0.1})
        assert detail.nb_probs == pytest.approx({1: 0.2, 2: 0.7, 3: 0.1})
        assert set(detail.meta_features) == set(META_NAMES)
        assert detail.meta_features["rule_hit"] == 1.0 and detail.meta_features["rule_conf"] == 0.9
        assert detail.meta_features["seen_log"] == pytest.approx(np.log1p(4))
        assert detail.lgbm_weight is None and detail.rule_weight is None

    def test_the_stack_decides_and_a_rule_never_overrides_it(self, db_session):
        ensemble = _ensemble(db_session, {"REWE": (3, 0.98)})

        prediction = ensemble.predict_with_confidence([_txn("REWE")])[0]

        # Mean of (0.6, 0.3, 0.1), (0.2, 0.7, 0.1), (0.01, 0.01, 0.98): category 3 by a hair.
        assert prediction.detail is not None
        assert prediction.detail.ensemble_probs == pytest.approx({1: 0.27, 2: 0.3367, 3: 0.3933}, abs=1e-4)
        assert prediction.predicted_category_id == 3
        assert prediction.confidence_score < 0.98

    def test_a_transaction_without_a_rule_records_no_rule_vote(self, db_session):
        ensemble = _ensemble(db_session, {"REWE": (3, 0.9)})

        prediction = ensemble.predict_with_confidence([_txn("Fielmann")])[0]

        assert prediction.detail is not None
        assert prediction.detail.rule_probs == {}
        assert prediction.detail.rule_pattern is None
        assert prediction.detail.meta_features["rule_hit"] == 0.0
        assert prediction.detail.meta_features["seen_log"] == 0.0
        # The stack saw a flat rule vote, so the two models decide: they agree on category 2.
        assert prediction.predicted_category_id == 2
        assert prediction.confidence_score == pytest.approx((0.3 + 0.7 + 1 / 3) / 3)

    def test_prediction_requires_a_stack(self, db_session):
        ensemble = _ensemble(db_session, {})
        ensemble.stack = None

        with pytest.raises(ValueError, match="retrain"):
            ensemble.predict_with_confidence([_txn("REWE")])

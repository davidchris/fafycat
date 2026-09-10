"""The Merchant Rule as the ensemble's third voter: its vote, the blend, its weight."""

from datetime import date
from types import SimpleNamespace

import numpy as np
import pytest

from fafycat.core.config import MLConfig
from fafycat.core.models import MerchantMapping, TransactionInput
from fafycat.ml.ensemble_categorizer import (
    MIN_MODEL_WEIGHT,
    EnsembleCategorizer,
    blend_probabilities,
    rule_probability_vector,
    rule_votes,
    weight_grid,
)
from fafycat.ml.merchant_mapper import MerchantRuleSet, derive_rules

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


class TestBlend:
    lgbm = np.array([[0.6, 0.3, 0.1], [0.6, 0.3, 0.1]])
    nb = np.array([[0.2, 0.7, 0.1], [0.2, 0.7, 0.1]])
    rule = np.array([[0.05, 0.9, 0.05], [0.0, 0.0, 0.0]])
    has_rule = np.array([True, False])

    def test_rule_row_is_the_weighted_sum_of_all_three_voters(self):
        weights = {"lgbm": 0.5, "nb": 0.3, "rule": 0.2}

        blended = blend_probabilities(self.lgbm, self.nb, self.rule, self.has_rule, weights)

        assert blended[0] == pytest.approx(0.5 * self.lgbm[0] + 0.3 * self.nb[0] + 0.2 * self.rule[0])
        assert blended[0].sum() == pytest.approx(1.0)

    def test_row_without_a_rule_renormalises_over_the_two_models(self):
        weights = {"lgbm": 0.5, "nb": 0.3, "rule": 0.2}

        blended = blend_probabilities(self.lgbm, self.nb, self.rule, self.has_rule, weights)

        assert blended[1] == pytest.approx((0.5 * self.lgbm[1] + 0.3 * self.nb[1]) / 0.8)
        assert blended[1].sum() == pytest.approx(1.0)

    def test_merchants_without_a_rule_predict_exactly_as_the_two_models_did(self):
        two_voters = blend_probabilities(
            self.lgbm, self.nb, self.rule, self.has_rule, {"lgbm": 0.625, "nb": 0.375, "rule": 0.0}
        )
        three_voters = blend_probabilities(
            self.lgbm, self.nb, self.rule, self.has_rule, {"lgbm": 0.5, "nb": 0.3, "rule": 0.2}
        )

        assert three_voters[1] == pytest.approx(two_voters[1])

    def test_a_rule_pulls_the_outcome_but_can_be_outvoted(self):
        heavy_rule = blend_probabilities(
            self.lgbm, self.nb, self.rule, self.has_rule, {"lgbm": 0.1, "nb": 0.1, "rule": 0.8}
        )
        light_rule = blend_probabilities(
            self.lgbm, self.nb, self.rule, self.has_rule, {"lgbm": 0.8, "nb": 0.1, "rule": 0.1}
        )

        assert int(np.argmax(heavy_rule[0])) == 1, "the rule's category wins when the rule is heavy"
        assert int(np.argmax(light_rule[0])) == 0, "LightGBM outvotes the rule when the rule is light"


class TestWeightGrid:
    def test_every_candidate_sums_to_one(self):
        assert all(sum(w.values()) == pytest.approx(1.0) for w in weight_grid())

    def test_both_models_keep_a_minimum_weight_and_the_rule_may_be_silent(self):
        grid = weight_grid()

        assert all(w["lgbm"] >= MIN_MODEL_WEIGHT and w["nb"] >= MIN_MODEL_WEIGHT for w in grid)
        assert all(w["rule"] >= 0.0 for w in grid)
        assert any(w["rule"] == 0.0 for w in grid), "the two-voter ensemble stays reachable"

    def test_the_grid_walks_the_whole_simplex_in_steps(self):
        grid = weight_grid(step=0.1)

        assert len(grid) == 45
        assert len({tuple(sorted(w.items())) for w in grid}) == 45


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
        self.classifier = SimpleNamespace()  # no feature_importances_, so contributions stay empty
        self.merchant_mapper = SimpleNamespace(rule_set=MerchantRuleSet({}))

    def predict_proba(self, transactions: list[TransactionInput]) -> np.ndarray:
        return np.tile(self.probabilities, (len(transactions), 1))


def _ensemble(db_session, rules: dict[str, tuple[int, float]], weights: dict[str, float]) -> EnsembleCategorizer:
    ensemble = EnsembleCategorizer(db_session, MLConfig())
    ensemble.lgbm_component = _FakeComponent([0.6, 0.3, 0.1], CLASS_IDS)
    ensemble.lgbm_component.merchant_mapper.rule_set = MerchantRuleSet(rules)
    ensemble.nb_component = _FakeComponent([0.2, 0.7, 0.1], CLASS_IDS)
    ensemble.ensemble_weights = weights
    ensemble.is_trained = True
    return ensemble


class TestEnsemblePrediction:
    def test_prediction_detail_carries_the_rule_vote_and_its_weight(self, db_session):
        ensemble = _ensemble(db_session, {"REWE": (3, 0.9)}, {"lgbm": 0.4, "nb": 0.3, "rule": 0.3})

        detail = ensemble.predict_with_confidence([_txn("REWE")])[0].detail

        assert detail is not None
        assert detail.source == "ensemble"
        assert detail.rule_pattern == "REWE" and detail.rule_category_id == 3
        assert detail.rule_probs == {1: 0.05, 2: 0.05, 3: 0.9}
        assert detail.rule_weight == 0.3
        assert detail.lgbm_weight == 0.4 and detail.nb_weight == 0.3

    def test_a_rule_no_longer_overrides_the_models(self, db_session):
        ensemble = _ensemble(db_session, {"REWE": (3, 0.98)}, {"lgbm": 0.4, "nb": 0.4, "rule": 0.2})

        prediction = ensemble.predict_with_confidence([_txn("REWE")])[0]

        assert prediction.predicted_category_id == 2, "the models outvote a 98% rule at weight 0.2"
        assert prediction.confidence_score < 0.98

    def test_a_transaction_without_a_rule_records_no_rule_vote(self, db_session):
        ensemble = _ensemble(db_session, {"REWE": (3, 0.9)}, {"lgbm": 0.4, "nb": 0.3, "rule": 0.3})

        prediction = ensemble.predict_with_confidence([_txn("Fielmann")])[0]

        assert prediction.detail is not None
        assert prediction.detail.rule_probs == {}
        assert prediction.detail.rule_weight == 0.0
        assert prediction.detail.rule_pattern is None
        # Renormalised over the two models, which agree on category 2
        assert prediction.predicted_category_id == 2
        assert prediction.confidence_score == pytest.approx((0.4 * 0.3 + 0.3 * 0.7) / 0.7)

"""The stacked ensemble's building blocks: voters, meta features, and the level-1 model."""

from datetime import date

import numpy as np
import pytest

from fafycat.core.models import TransactionInput
from fafycat.ml.stack import META_NAMES, StackLR, Voters, lookup_seen, meta_features, seen_counts


def _txn(name: str, amount: float = -10.0) -> TransactionInput:
    return TransactionInput(date=date(2026, 1, 1), name=name, purpose="", amount=amount, currency="EUR")


def _voters(n: int = 3) -> Voters:
    lgbm = np.tile([0.6, 0.3, 0.1], (n, 1))
    nb = np.tile([0.2, 0.7, 0.1], (n, 1))
    rule_vote = np.zeros((n, 3))
    rule_vote[0] = [0.9, 0.05, 0.05]
    rule_hit = np.array([True] + [False] * (n - 1))
    rule_conf = np.array([0.9] + [0.0] * (n - 1))
    return Voters(
        lgbm=lgbm,
        nb=nb,
        rule_vote=rule_vote,
        rule_hit=rule_hit,
        rule_conf=rule_conf,
        seen=np.array([5.0] + [0.0] * (n - 1)),
        amount=np.array([-12.5] * n),
    )


class TestVoters:
    def test_rule_probs_are_uniform_where_no_rule_voted(self):
        v = _voters()

        rule = v.rule_probs()

        assert rule[0].tolist() == [0.9, 0.05, 0.05]
        assert rule[1].tolist() == pytest.approx([1 / 3] * 3)

    def test_subset_keeps_rows_aligned(self):
        v = _voters(4)

        sub = v.subset(np.array([0, 2]))

        assert sub.lgbm.shape == (2, 3)
        assert sub.rule_hit.tolist() == [True, False]
        assert sub.seen.tolist() == [5.0, 0.0]


class TestMetaFeatures:
    def test_one_column_per_name(self):
        assert meta_features(_voters()).shape == (3, len(META_NAMES))

    def test_agreement_and_rule_flags(self):
        m = meta_features(_voters())
        col = {name: i for i, name in enumerate(META_NAMES)}

        # LightGBM says class 0, NB says class 1: they disagree everywhere.
        assert m[:, col["agree_lgbm_nb"]].tolist() == [0.0, 0.0, 0.0]
        # The rule (class 0) agrees with LightGBM on the one row it matched.
        assert m[:, col["agree_lgbm_rule"]].tolist() == [1.0, 0.0, 0.0]
        assert m[:, col["rule_hit"]].tolist() == [1.0, 0.0, 0.0]
        assert m[0, col["rule_conf"]] == 0.9
        assert m[0, col["seen_log"]] == pytest.approx(np.log1p(5))
        assert m[0, col["amount_sign"]] == -1.0

    def test_entropy_is_zero_for_a_point_mass_and_one_for_uniform(self):
        v = _voters(2)
        v.lgbm = np.array([[1.0, 0.0, 0.0], [1 / 3, 1 / 3, 1 / 3]])
        col = list(META_NAMES).index("lgbm_entropy")

        m = meta_features(v)

        assert m[0, col] == pytest.approx(0.0, abs=1e-9)
        assert m[1, col] == pytest.approx(1.0)


class TestSeenCounts:
    def test_counts_cleaned_patterns_and_looks_them_up(self):
        visible = [_txn("REWE SAGT DANKE"), _txn("REWE SAGT DANKE"), _txn("Fielmann")]

        counts = seen_counts(visible)
        seen = lookup_seen(counts, [_txn("REWE SAGT DANKE"), _txn("Unknown Shop")])

        assert seen.tolist() == [2.0, 0.0]


class TestStackLR:
    def _training_block(self, n: int = 300) -> tuple[Voters, np.ndarray]:
        rng = np.random.default_rng(0)
        y = rng.integers(0, 3, size=n)
        lgbm = rng.dirichlet(np.ones(3) * 0.5, size=n)
        lgbm[np.arange(n), y] += 1.5  # LightGBM is informative
        lgbm /= lgbm.sum(axis=1, keepdims=True)
        nb = rng.dirichlet(np.ones(3), size=n)  # Naive Bayes is noise here
        rule_vote = np.zeros((n, 3))
        rule_hit = np.zeros(n, dtype=bool)
        return Voters(
            lgbm=lgbm,
            nb=nb,
            rule_vote=rule_vote,
            rule_hit=rule_hit,
            rule_conf=np.zeros(n),
            seen=rng.integers(0, 10, size=n).astype(float),
            amount=rng.normal(size=n) * 50,
        ), y

    def test_learns_to_follow_the_informative_voter(self):
        v, y = self._training_block()

        stack = StackLR(c=0.3).fit(v, y, n_classes=3)
        p = stack.predict_proba(v)

        assert p.shape == (300, 3)
        assert np.allclose(p.sum(axis=1), 1.0)
        assert (p.argmax(axis=1) == y).mean() > 0.8
        importance = stack.block_importance()
        assert importance["lgbm_logp"] > importance["nb_logp"]

    def test_classes_missing_from_training_predict_zero(self):
        v, y = self._training_block()
        y = np.where(y == 2, 0, y)  # class 2 never appears

        p = StackLR().fit(v, y, n_classes=3).predict_proba(v)

        assert p.shape[1] == 3
        assert p[:, 2].max() == 0.0
        assert np.allclose(p.sum(axis=1), 1.0)

    def test_predict_before_fit_raises(self):
        with pytest.raises(ValueError, match="fitted"):
            StackLR().predict_proba(_voters())

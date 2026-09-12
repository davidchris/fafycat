"""The stacked ensemble: a level-1 model over the three voters.

LightGBM, Naive Bayes, and the Merchant Rules each turn a transaction into a
probability vector over the categories. Rather than adding those vectors up
with three weights, a multinomial logistic regression reads all three, plus a
handful of meta features (how sure each voter is, whether they agree, how
often the merchant was seen in training, the amount), and produces the final
probability vector. It is fitted on out-of-fold voter outputs only: a voter's
opinion about a row it was trained on is not evidence of anything.

Why a stack rather than weights: the weights learned on one validation split
swung between retrains on near-identical data, and no weighting can express
"trust the rule when LightGBM agrees, ignore it otherwise". The stack's
coefficients moved by less than 6% across splits in experiments/02-stacked-gate.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.linear_model import LogisticRegression

from ..core.models import TransactionInput
from .calibration import EPS
from .feature_extractor import MerchantCleaner

META_NAMES: tuple[str, ...] = (
    "lgbm_top",
    "lgbm_entropy",
    "nb_top",
    "nb_entropy",
    "rule_top",
    "rule_entropy",
    "rule_hit",
    "rule_conf",
    "agree_lgbm_nb",
    "agree_lgbm_rule",
    "agree_nb_rule",
    "seen_log",
    "log_amount",
    "amount_sign",
)
"""The meta features, in the column order :func:`meta_features` produces them."""


@dataclass
class Voters:
    """Level-0 outputs for a block of rows, all aligned to the same category columns.

    Attributes:
        lgbm: LightGBM probabilities, shape ``(n, K)``.
        nb: Naive Bayes probabilities, shape ``(n, K)``.
        rule_vote: Merchant Rule votes, shape ``(n, K)``; all-zero rows where no rule matched.
        rule_hit: Which rows a rule voted on, shape ``(n,)``.
        rule_conf: Confidence of the matched rule, 0 where none matched.
        seen: Training rows sharing the row's cleaned merchant pattern.
        amount: Signed transaction amount.
    """

    lgbm: np.ndarray
    nb: np.ndarray
    rule_vote: np.ndarray
    rule_hit: np.ndarray
    rule_conf: np.ndarray
    seen: np.ndarray
    amount: np.ndarray

    def rule_probs(self) -> np.ndarray:
        """The rule vote as a distribution: uniform on the rows no rule voted on."""
        out = self.rule_vote.copy()
        out[~self.rule_hit] = 1.0 / out.shape[1]
        return out

    def subset(self, idx: np.ndarray) -> Voters:
        """The same voters restricted to the rows in ``idx``."""
        return Voters(
            lgbm=self.lgbm[idx],
            nb=self.nb[idx],
            rule_vote=self.rule_vote[idx],
            rule_hit=self.rule_hit[idx],
            rule_conf=self.rule_conf[idx],
            seen=self.seen[idx],
            amount=self.amount[idx],
        )


def seen_counts(visible: list[TransactionInput]) -> dict[str, int]:
    """How many of ``visible`` share each cleaned merchant pattern.

    Args:
        visible: The rows a model was trained on.

    Returns:
        Cleaned merchant pattern mapped to its row count. Empty patterns are skipped.
    """
    cleaner = MerchantCleaner()
    counts: dict[str, int] = {}
    for txn in visible:
        pattern = cleaner.clean(txn.name)
        if pattern:
            counts[pattern] = counts.get(pattern, 0) + 1
    return counts


def lookup_seen(counts: dict[str, int], transactions: list[TransactionInput]) -> np.ndarray:
    """The ``seen`` column for ``transactions``, read from :func:`seen_counts` output."""
    cleaner = MerchantCleaner()
    return np.array([counts.get(cleaner.clean(txn.name), 0) for txn in transactions], dtype=float)


def _entropy(p: np.ndarray) -> np.ndarray:
    """Shannon entropy per row, divided by ``log K`` so it lands in ``[0, 1]``."""
    if p.shape[1] < 2:
        return np.zeros(len(p))
    q = np.clip(p, EPS, 1.0)
    return -(q * np.log(q)).sum(axis=1) / np.log(p.shape[1])


def meta_features(v: Voters) -> np.ndarray:
    """The meta features of :data:`META_NAMES`, one row per transaction, in that order."""
    rule = v.rule_probs()
    top_lgbm, top_nb, top_rule = v.lgbm.argmax(axis=1), v.nb.argmax(axis=1), rule.argmax(axis=1)
    hit = v.rule_hit.astype(float)
    return np.column_stack(
        [
            v.lgbm.max(axis=1),
            _entropy(v.lgbm),
            v.nb.max(axis=1),
            _entropy(v.nb),
            rule.max(axis=1),
            _entropy(rule),
            hit,
            v.rule_conf,
            (top_lgbm == top_nb).astype(float),
            (top_lgbm == top_rule).astype(float) * hit,
            (top_nb == top_rule).astype(float) * hit,
            np.log1p(v.seen),
            np.log1p(np.abs(v.amount)),
            np.sign(v.amount),
        ]
    )


def _logp(p: np.ndarray) -> np.ndarray:
    return np.log(np.clip(p, EPS, 1.0))


class StackLR:
    """Multinomial logistic regression over the voters' log-probabilities and the meta features.

    The rule columns carry the uniform vector on rows without a match, so "no
    rule" is a flat, uninformative vote; the ``rule_hit`` meta feature tells
    the model the difference. Plain attributes only, so it pickles with the model.
    """

    def __init__(self, c: float = 0.03, max_iter: int = 3000) -> None:
        self.c = c
        self.max_iter = max_iter
        self.model_: LogisticRegression | None = None
        self.n_classes_ = 0

    def design(self, v: Voters) -> np.ndarray:
        """The level-1 feature matrix: ``[log lgbm | log nb | log rule | meta]``."""
        return np.column_stack([_logp(v.lgbm), _logp(v.nb), _logp(v.rule_probs()), meta_features(v)])

    def fit(self, v: Voters, y: np.ndarray, n_classes: int) -> StackLR:
        """Fit on out-of-fold voter outputs.

        Args:
            v: Voters for the training rows, each produced by models that never saw the row.
            y: Labels encoded ``0..n_classes-1``.
            n_classes: Number of category columns; classes absent from ``y`` predict 0.

        Returns:
            Self, fitted.
        """
        self.n_classes_ = n_classes
        self.model_ = LogisticRegression(C=self.c, max_iter=self.max_iter, n_jobs=1)
        self.model_.fit(self.design(v), y)
        return self

    def predict_proba(self, v: Voters) -> np.ndarray:
        """Probabilities of shape ``(n, n_classes)``, rows summing to 1."""
        if self.model_ is None:
            raise ValueError("Stack must be fitted before prediction")
        p = self.model_.predict_proba(self.design(v))
        if p.shape[1] != self.n_classes_:
            full = np.zeros((len(p), self.n_classes_))
            full[:, self.model_.classes_] = p
            p = full / np.clip(full.sum(axis=1, keepdims=True), EPS, None)
        return p

    def block_importance(self) -> dict[str, float]:
        """Mean absolute coefficient per voter block and per meta feature."""
        if self.model_ is None:
            raise ValueError("Stack must be fitted before reading its coefficients")
        coef = np.abs(np.asarray(self.model_.coef_, dtype=float))
        k = self.n_classes_
        out = {
            "lgbm_logp": float(coef[:, :k].mean()),
            "nb_logp": float(coef[:, k : 2 * k].mean()),
            "rule_logp": float(coef[:, 2 * k : 3 * k].mean()),
        }
        for j, name in enumerate(META_NAMES):
            out[name] = float(coef[:, 3 * k + j].mean())
        return out

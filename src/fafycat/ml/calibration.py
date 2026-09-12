"""Probability calibration fitted on out-of-fold predictions.

A calibrator fitted on a model's own training rows learns that the model is
nearly always right, because on those rows it is. Every calibrator here is
therefore fitted on *out-of-fold* probabilities: each training row is scored
by a model that never saw it (:func:`oof_probs`), and the calibrator maps
those honest scores onto the final model, which is fitted on all rows.

Temperature scaling is the only method in use. One scalar ``T`` rescales the
log-probabilities, so it cannot overfit a few thousand rows and never changes
which category a row ranks first.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Protocol

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import softmax
from sklearn.model_selection import StratifiedKFold

EPS = 1e-12
"""Floor for probabilities before taking their log."""


class Estimator(Protocol):
    """The slice of the scikit-learn estimator API :func:`oof_probs` needs."""

    classes_: Any

    def fit(self, x: Any, y: np.ndarray) -> Any: ...

    def predict_proba(self, x: Any) -> np.ndarray: ...


def _take(x: Any, idx: np.ndarray) -> Any:
    """Index rows of a feature matrix or of a plain list of inputs."""
    if isinstance(x, np.ndarray):
        return x[idx]
    return [x[int(i)] for i in idx]


def fold_count(y: np.ndarray, n_splits: int) -> int:
    """Number of stratified folds the label counts allow, at least 2.

    Args:
        y: Integer labels.
        n_splits: Desired number of folds.

    Returns:
        ``n_splits`` capped at the size of the smallest class.
    """
    smallest = int(np.bincount(y).min()) if len(y) else 0
    return max(2, min(n_splits, smallest))


def oof_probs(
    make_model: Callable[[], Estimator],
    x: Sequence[Any] | np.ndarray,
    y: np.ndarray,
    n_splits: int = 5,
    seed: int = 0,
) -> np.ndarray:
    """Out-of-fold probabilities for every training row.

    Args:
        make_model: Zero-argument factory returning a fresh, unfitted estimator.
        x: Feature matrix or list of model inputs, one entry per row of ``y``.
        y: Integer labels encoded ``0..K-1``.
        n_splits: Stratified folds; reduced when the smallest class is smaller.
        seed: Shuffle seed for the fold assignment.

    Returns:
        Probabilities of shape ``(n_rows, K)`` with column ``k`` for label
        ``k`` even when a fold's training side misses a class.
    """
    classes = np.unique(y)
    k = int(classes.max()) + 1 if len(classes) else 0
    oof = np.zeros((len(y), k))
    skf = StratifiedKFold(n_splits=fold_count(y, n_splits), shuffle=True, random_state=seed)
    for train_idx, test_idx in skf.split(np.zeros(len(y)), y):
        model = make_model()
        model.fit(_take(x, train_idx), y[train_idx])
        probs = model.predict_proba(_take(x, test_idx))
        for j, cls in enumerate(model.classes_):
            oof[test_idx, int(cls)] = probs[:, j]
    return oof


class TemperatureScaler:
    """Single scalar ``T`` applied as ``softmax(log p / T)``.

    ``T > 1`` spreads probability mass out (fixes over-confidence), ``T < 1``
    sharpens it (fixes under-confidence). Plain attributes only, so a fitted
    scaler pickles with the model.
    """

    def __init__(self, bounds: tuple[float, float] = (0.05, 20.0)) -> None:
        self.bounds = bounds
        self.temperature_: float = 1.0

    def fit(self, probs: np.ndarray, y: np.ndarray) -> TemperatureScaler:
        """Pick ``T`` by minimising the multiclass log-loss of ``probs`` against ``y``.

        Args:
            probs: Probabilities of shape ``(n_rows, K)``, ideally out-of-fold.
            y: Integer labels encoded ``0..K-1``, indexing the columns of ``probs``.

        Returns:
            Self, fitted.
        """
        logp = np.log(np.clip(probs, EPS, 1.0))
        rows = np.arange(len(y))

        def nll(t: float) -> float:
            q = softmax(logp / t, axis=1)
            return float(-np.log(np.clip(q[rows, y], EPS, 1.0)).mean())

        result = minimize_scalar(nll, bounds=self.bounds, method="bounded")
        self.temperature_ = float(result.x)
        return self

    def predict_proba(self, probs: np.ndarray) -> np.ndarray:
        """Rescale a probability matrix with the fitted temperature."""
        logp = np.log(np.clip(probs, EPS, 1.0))
        return softmax(logp / self.temperature_, axis=1)

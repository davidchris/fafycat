"""Out-of-fold calibration: honest probabilities before anything trusts them."""

import numpy as np
import pytest
from sklearn.linear_model import LogisticRegression

from fafycat.ml.calibration import TemperatureScaler, fold_count, oof_probs


def _blobs(n_per_class: int = 60, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    x = np.vstack([rng.normal(loc=c * 2.0, scale=1.5, size=(n_per_class, 2)) for c in range(3)])
    y = np.repeat(np.arange(3), n_per_class)
    return x, y


class TestOofProbs:
    def test_every_row_is_scored_and_rows_sum_to_one(self):
        x, y = _blobs()

        oof = oof_probs(lambda: LogisticRegression(), x, y, n_splits=5)

        assert oof.shape == (len(y), 3)
        assert np.allclose(oof.sum(axis=1), 1.0)

    def test_columns_follow_the_encoded_label_even_when_a_fold_misses_a_class(self):
        # Class 2 has two rows: with 2 folds each training side sees it once at most.
        x = np.array([[0.0], [0.1], [0.2], [5.0], [5.1], [5.2], [9.0], [9.1]])
        y = np.array([0, 0, 0, 1, 1, 1, 2, 2])

        oof = oof_probs(lambda: LogisticRegression(), x, y, n_splits=2)

        assert oof.shape == (8, 3)
        assert oof[:3, 0].mean() > oof[:3, 1].mean()

    def test_accepts_a_list_of_inputs_instead_of_a_matrix(self):
        class Lengths:
            def fit(self, x, y):
                self.classes_ = np.unique(y)
                return self

            def predict_proba(self, x):
                out = np.zeros((len(x), len(self.classes_)))
                out[:, 0] = 1.0
                return out

        oof = oof_probs(Lengths, ["a", "bb", "ccc", "d", "ee", "fff"], np.array([0, 1, 0, 1, 0, 1]), n_splits=2)

        assert oof[:, 0].tolist() == [1.0] * 6

    def test_fold_count_never_exceeds_the_smallest_class(self):
        assert fold_count(np.array([0, 0, 0, 1, 1]), 5) == 2
        assert fold_count(np.array([0] * 9 + [1] * 9), 5) == 5


class TestTemperatureScaler:
    def test_overconfident_probabilities_get_a_temperature_above_one(self):
        rng = np.random.default_rng(1)
        y = rng.integers(0, 3, size=600)
        probs = np.full((600, 3), 0.02)
        # Confident on the true class only 60% of the time: badly over-confident.
        right = rng.random(600) < 0.6
        probs[np.arange(600), np.where(right, y, (y + 1) % 3)] = 0.96

        scaler = TemperatureScaler().fit(probs, y)

        assert scaler.temperature_ > 1.0
        assert scaler.predict_proba(probs).max(axis=1).mean() < 0.9

    def test_scaling_never_reorders_the_classes_of_a_row(self):
        rng = np.random.default_rng(2)
        probs = rng.dirichlet(np.ones(4), size=50)
        scaler = TemperatureScaler()
        scaler.temperature_ = 3.0

        scaled = scaler.predict_proba(probs)

        assert (scaled.argmax(axis=1) == probs.argmax(axis=1)).all()
        assert np.allclose(scaled.sum(axis=1), 1.0)

    def test_underconfident_probabilities_get_sharpened(self):
        y = np.array([0, 1, 2] * 100)
        probs = np.full((300, 3), 0.3)
        probs[np.arange(300), y] = 0.4  # always right, never sure

        scaler = TemperatureScaler().fit(probs, y)

        assert scaler.temperature_ < 1.0
        assert scaler.predict_proba(probs)[0, 0] > 0.9

    def test_fit_returns_self_for_chaining(self):
        y = np.array([0, 1] * 20)
        probs = np.tile([0.7, 0.3], (40, 1))

        assert isinstance(TemperatureScaler().fit(probs, y), TemperatureScaler)

    def test_temperature_stays_within_bounds(self):
        y = np.array([0, 1] * 20)
        probs = np.tile([0.5, 0.5], (40, 1))

        scaler = TemperatureScaler(bounds=(0.5, 2.0)).fit(probs, y)

        assert 0.5 <= scaler.temperature_ <= 2.0 or scaler.temperature_ == pytest.approx(0.5, abs=1e-6)

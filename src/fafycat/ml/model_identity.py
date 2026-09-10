"""Small helpers shared by the Categorizers for the Audit Trail."""

import hashlib
from pathlib import Path

import numpy as np


def model_fingerprint(model_path: Path) -> str:
    """Stable identity of a saved model file: first 12 hex chars of its SHA-256."""
    digest = hashlib.sha256()
    with open(model_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()[:12]


def probs_by_category(class_ids: list[int], proba: np.ndarray) -> dict[int, float]:
    """Map a probability vector onto category ids, rounded for storage."""
    return {category_id: round(float(p), 4) for category_id, p in zip(class_ids, proba, strict=True)}

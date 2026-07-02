"""Shared fake objects for rendering tests."""

from dataclasses import dataclass


@dataclass
class FakeTransaction:
    """Minimal transaction-like object for rendering tests."""

    id: str = "abc123"
    date: str = "2025-06-15"
    description: str = "Test Store"
    amount: float = -10.0
    actual_category: str | None = None
    predicted_category: str | None = None
    confidence: float | None = 0.75
    is_reviewed: bool = False

"""Core data models for FafyCat."""

import hashlib
from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class CategoryType(str, Enum):
    """Category types for transactions."""

    SPENDING = "spending"
    INCOME = "income"
    SAVING = "saving"


class Category(BaseModel):
    """Category model with budget tracking."""

    id: int | None = None
    type: CategoryType
    name: str = Field(..., min_length=1, max_length=50)
    budget: float = Field(ge=0.0)  # Default budget, fallback for years without specific budget
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Normalize category name."""
        return v.strip().lower()


class BudgetPlan(BaseModel):
    """Year-specific budget plan for a category."""

    id: int | None = None
    category_id: int
    year: int = Field(ge=2020, le=2030)  # Reasonable year range
    monthly_budget: float = Field(ge=0.0)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TransactionInput(BaseModel):
    """Raw transaction from CSV import."""

    date: date
    value_date: date | None = None
    category: str | None = None
    name: str
    purpose: str
    account: str | None = None
    bank: str | None = None
    amount: float
    currency: str = "EUR"

    def generate_id(self) -> str:
        """Generate deterministic ID for deduplication."""
        key = f"{self.date}|{self.amount}|{self.name}|{self.purpose}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]


class Transaction(BaseModel):
    """Database transaction model."""

    id: str
    date: date
    value_date: date | None = None
    name: str
    purpose: str
    amount: float
    currency: str = "EUR"
    category_id: int | None = None
    predicted_category_id: int | None = None
    confidence_score: float | None = Field(None, ge=0.0, le=1.0)
    is_reviewed: bool = False
    imported_at: datetime
    import_batch: str


class TransactionPrediction(BaseModel):
    """ML prediction result for a transaction."""

    transaction_id: str
    predicted_category_id: int
    confidence_score: float = Field(ge=0.0, le=1.0)
    feature_contributions: dict[str, float]


class MerchantMapping(BaseModel):
    """High-confidence merchant to category mapping."""

    id: int | None = None
    merchant_pattern: str
    category_id: int
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    occurrence_count: int = 1
    last_seen: date | None = None
    created_at: datetime | None = None


class ModelMetadata(BaseModel):
    """ML model metadata and performance metrics."""

    id: int | None = None
    model_version: str
    training_date: datetime
    accuracy: float | None = None
    feature_importance: dict[str, float] | None = None
    parameters: dict[str, Any] | None = None
    is_active: bool = False


class ModelMetrics(BaseModel):
    """Model performance metrics."""

    accuracy: float
    precision_per_category: dict[str, float]
    recall_per_category: dict[str, float]
    confusion_matrix: list[list[int]]
    feature_importance: dict[str, float]

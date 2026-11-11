"""Pydantic models for API requests and responses."""

import re
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from fafycat.core.models import ReviewPriority


class TransactionResponse(BaseModel):
    """Response model for transaction data."""

    id: str
    date: date
    description: str
    amount: float
    account: str
    predicted_category: str | None = None
    actual_category: str | None = None
    predicted_category_id: int | None = None
    actual_category_id: int | None = None
    confidence: float | None = None
    is_reviewed: bool = False
    review_priority: str | None = None
    pending_siblings: int | None = None
    """Unreviewed transactions sharing the merchant pattern, this one included; None when not counted."""
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TransactionUpdate(BaseModel):
    """Request model for updating transaction category.

    Give the category as ``actual_category`` (a name, or ``name (type)``) or as
    ``category_id``. The id never collides; the web forms send it.
    """

    actual_category: str | None = None
    category_id: int | None = None
    is_reviewed: bool = True

    @model_validator(mode="after")
    def _one_category_reference(self) -> "TransactionUpdate":
        if (self.actual_category is None) == (self.category_id is None):
            raise ValueError("give exactly one of actual_category or category_id")
        return self


class BulkCategorizeRequest(BaseModel):
    """Request model for bulk categorization."""

    transaction_ids: list[str]
    category: str


class BulkApproveRequest(BaseModel):
    """Request model for bulk-approving unreviewed predictions.

    With neither field set, every unreviewed prediction at or above the
    Auto-approve Threshold is approved.
    """

    review_priority: ReviewPriority | None = None
    min_confidence: float | None = Field(None, ge=0, le=1)


class CategoryResponse(BaseModel):
    """Response model for category data."""

    id: int
    name: str
    type: str
    is_active: bool
    budget: float | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


CATEGORY_NAME_MAX_LENGTH = 50
"""Matches ``categories.name`` (``String(50)``) and the core ``Category`` model."""


_TYPE_SUFFIX = re.compile(r" \((spending|income|saving)\)$")


def _normalize_category_name(name: str | None) -> str | None:
    """Strip and lowercase, as CSV import and the core model do.

    Raises:
        ValueError: The name ends in `` (spending)``, `` (income)`` or `` (saving)``,
            the form reserved for telling apart categories that share a name.
    """
    if name is None:
        return None
    name = name.strip().lower()
    if _TYPE_SUFFIX.search(name):
        raise ValueError("a category name may not end in a type in parentheses, such as ' (income)'")
    return name


class CategoryCreate(BaseModel):
    """Request model for creating a category."""

    name: str = Field(..., min_length=1, max_length=CATEGORY_NAME_MAX_LENGTH)
    type: str = Field(..., pattern="^(spending|income|saving)$")
    budget: float | None = Field(None, ge=0)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, v: object) -> object:
        """Strip and lowercase the name before the length check."""
        return _normalize_category_name(v) if isinstance(v, str) else v


class CategoryUpdate(BaseModel):
    """Request model for updating a category."""

    name: str | None = Field(None, min_length=1, max_length=CATEGORY_NAME_MAX_LENGTH)
    type: str | None = Field(None, pattern="^(spending|income|saving)$")
    is_active: bool | None = None
    budget: float | None = Field(None, ge=0)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, v: object) -> object:
        """Strip and lowercase the name before the length check."""
        return _normalize_category_name(v) if isinstance(v, str) else v


class UploadResponse(BaseModel):
    """Response model for file upload."""

    upload_id: str
    filename: str
    rows_processed: int
    transactions_imported: int
    duplicates_skipped: int
    predictions_made: int = 0
    auto_accepted: int = 0
    needs_review: int = 0
    already_reviewed: int = 0
    """Rows that came with a category in the CSV and kept it."""
    prediction_error: str | None = None
    """Why nothing was predicted when a model exists but could not be used."""


class ExportRequest(BaseModel):
    """Request model for data export."""

    format: str = Field(..., pattern="^(csv|excel|json)$")
    start_date: date | None = None
    end_date: date | None = None
    categories: list[str] | None = None


class TransactionPredictRequest(BaseModel):
    """Request model for ML prediction of a transaction."""

    date: date
    name: str
    purpose: str = ""
    amount: float
    currency: str = "EUR"
    value_date: date | None = None


class TransactionPredictResponse(BaseModel):
    """Response model for ML prediction."""

    predicted_category_id: int | None = None
    predicted_category_name: str | None = None
    confidence_score: float
    feature_contributions: dict[str, float]
    confidence_level: str
    merchant_suggestions: list[dict] | None = None


class BulkPredictRequest(BaseModel):
    """Request model for bulk ML predictions."""

    transactions: list[TransactionPredictRequest]


class BulkPredictResponse(BaseModel):
    """Response model for bulk ML predictions."""

    predictions: list[TransactionPredictResponse]
    total_processed: int
    processing_time_ms: float

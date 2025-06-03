"""Pydantic models for API requests and responses."""

from datetime import date, datetime

from pydantic import BaseModel, Field


class TransactionResponse(BaseModel):
    """Response model for transaction data."""

    id: str
    date: date
    description: str
    amount: float
    account: str
    predicted_category: str | None = None
    actual_category: str | None = None
    confidence: float | None = None
    is_reviewed: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TransactionUpdate(BaseModel):
    """Request model for updating transaction category."""

    actual_category: str
    is_reviewed: bool = True


class BulkCategorizeRequest(BaseModel):
    """Request model for bulk categorization."""

    transaction_ids: list[str]
    category: str


class CategoryResponse(BaseModel):
    """Response model for category data."""

    id: int
    name: str
    type: str
    is_active: bool
    budget: float | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CategoryCreate(BaseModel):
    """Request model for creating a category."""

    name: str = Field(..., min_length=1, max_length=100)
    type: str = Field(..., pattern="^(spending|income|saving)$")
    budget: float | None = Field(None, ge=0)


class CategoryUpdate(BaseModel):
    """Request model for updating a category."""

    name: str | None = Field(None, min_length=1, max_length=100)
    type: str | None = Field(None, pattern="^(spending|income|saving)$")
    is_active: bool | None = None
    budget: float | None = Field(None, ge=0)


class UploadResponse(BaseModel):
    """Response model for file upload."""

    upload_id: str
    filename: str
    rows_processed: int
    transactions_imported: int
    duplicates_skipped: int
    predictions_made: int = 0


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

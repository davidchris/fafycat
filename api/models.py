"""Pydantic models for API requests and responses."""

from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class TransactionResponse(BaseModel):
    """Response model for transaction data."""
    id: str
    date: date
    description: str
    amount: float
    account: str
    predicted_category: Optional[str] = None
    actual_category: Optional[str] = None
    confidence: Optional[float] = None
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
    transaction_ids: List[str]
    category: str


class CategoryResponse(BaseModel):
    """Response model for category data."""
    id: int
    name: str
    type: str
    is_active: bool
    budget: Optional[float] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CategoryCreate(BaseModel):
    """Request model for creating a category."""
    name: str = Field(..., min_length=1, max_length=100)
    type: str = Field(..., pattern="^(spending|income|saving)$")
    budget: Optional[float] = Field(None, ge=0)


class CategoryUpdate(BaseModel):
    """Request model for updating a category."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    type: Optional[str] = Field(None, pattern="^(spending|income|saving)$")
    is_active: Optional[bool] = None
    budget: Optional[float] = Field(None, ge=0)


class UploadResponse(BaseModel):
    """Response model for file upload."""
    upload_id: str
    filename: str
    rows_processed: int
    transactions_imported: int
    duplicates_skipped: int


class ExportRequest(BaseModel):
    """Request model for data export."""
    format: str = Field(..., pattern="^(csv|excel|json)$")
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    categories: Optional[List[str]] = None
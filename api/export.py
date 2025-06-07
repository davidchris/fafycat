"""API routes for data export operations."""

import io
import json
from datetime import date
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session, joinedload

from api.dependencies import get_db_session
from api.models import ExportRequest
from src.fafycat.core.database import CategoryORM, TransactionORM

router = APIRouter(prefix="/export", tags=["export"])


class ExportService:
    """Service for data export operations."""

    @staticmethod
    def get_export_data(
        session: Session,
        start_date: date | None = None,
        end_date: date | None = None,
        categories: list[str] | None = None,
        include_predictions: bool = True,
    ) -> list[dict[str, Any]]:
        """Get transaction data for export."""
        query = session.query(TransactionORM).options(
            joinedload(TransactionORM.category), joinedload(TransactionORM.predicted_category)
        )

        # Apply date filters
        if start_date:
            query = query.filter(TransactionORM.date >= start_date)
        if end_date:
            query = query.filter(TransactionORM.date <= end_date)

        # Apply category filters
        if categories:
            query = query.join(CategoryORM, TransactionORM.category_id == CategoryORM.id)
            query = query.filter(CategoryORM.name.in_(categories))

        # Order by date for consistent export
        query = query.order_by(TransactionORM.date.desc())

        transactions = query.all()

        # Convert to export format
        export_data = []
        for t in transactions:
            data = {
                "id": t.id,
                "date": t.date.isoformat(),
                "value_date": t.value_date.isoformat() if t.value_date else None,
                "name": t.name,
                "purpose": t.purpose,
                "amount": t.amount,
                "currency": t.currency,
                "category": t.category.name if t.category else None,
                "category_type": t.category.type if t.category else None,
                "is_reviewed": t.is_reviewed,
                "import_batch": t.import_batch,
                "imported_at": t.imported_at.isoformat(),
            }

            if include_predictions:
                data.update(
                    {
                        "predicted_category": t.predicted_category.name if t.predicted_category else None,
                        "predicted_category_type": t.predicted_category.type if t.predicted_category else None,
                        "confidence_score": t.confidence_score,
                    }
                )

            export_data.append(data)

        return export_data

    @staticmethod
    def export_to_csv(data: list[dict[str, Any]]) -> str:
        """Export data to CSV format."""
        if not data:
            return "No data to export"

        df = pd.DataFrame(data)
        return df.to_csv(index=False)

    @staticmethod
    def export_to_excel(data: list[dict[str, Any]]) -> bytes:
        """Export data to Excel format."""
        if not data:
            # Return empty Excel file
            df = pd.DataFrame()
            buffer = io.BytesIO()
            df.to_excel(buffer, index=False)
            return buffer.getvalue()

        df = pd.DataFrame(data)
        buffer = io.BytesIO()

        # Create Excel with multiple sheets if we have categories
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            # Main transactions sheet
            df.to_excel(writer, sheet_name="Transactions", index=False)

            # Summary by category if categories exist
            if "category" in df.columns and df["category"].notna().any():
                group_cols = ["category"]
                if "category_type" in df.columns:
                    group_cols.append("category_type")

                agg_dict = {"amount": ["count", "sum", "mean"]}
                if "confidence_score" in df.columns:
                    agg_dict["confidence_score"] = "mean"

                category_summary = df.groupby(group_cols).agg(agg_dict).round(2)

                if "confidence_score" in df.columns:
                    category_summary.columns = ["Transaction_Count", "Total_Amount", "Avg_Amount", "Avg_Confidence"]
                else:
                    category_summary.columns = ["Transaction_Count", "Total_Amount", "Avg_Amount"]

                category_summary.to_excel(writer, sheet_name="Category_Summary")

            # Monthly summary
            df["month"] = pd.to_datetime(df["date"]).dt.to_period("M")
            monthly_group_cols = ["month"]
            if "category_type" in df.columns:
                monthly_group_cols.append("category_type")

            monthly_summary = df.groupby(monthly_group_cols).agg({"amount": ["count", "sum"]}).round(2)
            monthly_summary.columns = ["Transaction_Count", "Total_Amount"]
            monthly_summary.to_excel(writer, sheet_name="Monthly_Summary")

        return buffer.getvalue()

    @staticmethod
    def export_to_json(data: list[dict[str, Any]]) -> str:
        """Export data to JSON format."""
        return json.dumps(data, indent=2, default=str)


@router.post("/transactions")
async def export_transactions(
    request: ExportRequest,
    db: Session = Depends(get_db_session),
) -> Response:
    """Export transactions in the specified format."""
    try:
        # Get export data
        data = ExportService.get_export_data(
            session=db,
            start_date=request.start_date,
            end_date=request.end_date,
            categories=request.categories,
        )

        if not data:
            raise HTTPException(status_code=404, detail="No transactions found for export")

        # Generate filename
        date_suffix = ""
        if request.start_date and request.end_date:
            date_suffix = f"_{request.start_date}_{request.end_date}"
        elif request.start_date:
            date_suffix = f"_from_{request.start_date}"
        elif request.end_date:
            date_suffix = f"_until_{request.end_date}"

        filename = f"fafycat_transactions{date_suffix}"

        # Export based on format
        if request.format == "csv":
            content = ExportService.export_to_csv(data)
            return Response(
                content=content,
                media_type="text/csv",
                headers={"Content-Disposition": f"attachment; filename={filename}.csv"},
            )

        if request.format == "excel":
            content = ExportService.export_to_excel(data)
            return Response(
                content=content,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f"attachment; filename={filename}.xlsx"},
            )

        if request.format == "json":
            content = ExportService.export_to_json(data)
            return Response(
                content=content,
                media_type="application/json",
                headers={"Content-Disposition": f"attachment; filename={filename}.json"},
            )

        raise HTTPException(status_code=400, detail="Unsupported export format")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}") from e


@router.get("/summary")
async def get_export_summary(
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    categories: list[str] | None = Query(None),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Get summary of data available for export."""
    query = db.query(TransactionORM).options(joinedload(TransactionORM.category))

    # Apply filters
    if start_date:
        query = query.filter(TransactionORM.date >= start_date)
    if end_date:
        query = query.filter(TransactionORM.date <= end_date)
    if categories:
        query = query.join(CategoryORM, TransactionORM.category_id == CategoryORM.id)
        query = query.filter(CategoryORM.name.in_(categories))

    transactions = query.all()

    # Calculate summary statistics
    total_count = len(transactions)
    reviewed_count = sum(1 for t in transactions if t.is_reviewed)
    predicted_count = sum(1 for t in transactions if t.predicted_category_id is not None)

    amount_stats = {
        "total": sum(t.amount for t in transactions),
        "min": min((t.amount for t in transactions), default=0),
        "max": max((t.amount for t in transactions), default=0),
        "avg": sum(t.amount for t in transactions) / total_count if total_count > 0 else 0,
    }

    # Category breakdown
    category_breakdown = {}
    for t in transactions:
        if t.category:
            cat_name = t.category.name
            if cat_name not in category_breakdown:
                category_breakdown[cat_name] = {"count": 0, "total_amount": 0}
            category_breakdown[cat_name]["count"] += 1
            category_breakdown[cat_name]["total_amount"] += t.amount

    # Date range
    date_range = {}
    if transactions:
        dates = [t.date for t in transactions]
        date_range = {
            "earliest": min(dates).isoformat(),
            "latest": max(dates).isoformat(),
        }

    return {
        "total_transactions": total_count,
        "reviewed_transactions": reviewed_count,
        "predicted_transactions": predicted_count,
        "amount_statistics": amount_stats,
        "category_breakdown": category_breakdown,
        "date_range": date_range,
        "filters_applied": {
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "categories": categories,
        },
    }


@router.get("/formats")
async def get_supported_formats() -> dict[str, Any]:
    """Get list of supported export formats and their descriptions."""
    return {
        "formats": {
            "csv": {
                "name": "CSV",
                "description": "Comma-separated values file for spreadsheet applications",
                "extension": "csv",
                "content_type": "text/csv",
            },
            "excel": {
                "name": "Excel",
                "description": "Excel workbook with multiple sheets including summaries",
                "extension": "xlsx",
                "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            },
            "json": {
                "name": "JSON",
                "description": "JavaScript Object Notation for programmatic access",
                "extension": "json",
                "content_type": "application/json",
            },
        }
    }

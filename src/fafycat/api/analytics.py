"""Analytics API endpoints for FafyCat."""

import html
import json
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from fafycat.api.dependencies import get_db_session
from fafycat.api.services import AnalyticsService

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/budget-variance")
async def get_budget_variance(
    session: Session = Depends(get_db_session),
    start_date: date | None = Query(None, description="Start date for analysis"),
    end_date: date | None = Query(None, description="End date for analysis"),
    year: int | None = Query(None, description="Year for analysis (defaults to current year)"),
) -> dict[str, Any]:
    """Get budget vs actual spending variance by category."""
    try:
        # If year is provided, convert to start_date and end_date
        if year and not start_date and not end_date:
            start_date = date(year, 1, 1)
            end_date = date(year, 12, 31)

        result = AnalyticsService.get_budget_variance(session, start_date, end_date)

        # Add date range information for frontend charts
        if start_date and end_date:
            result["start_date"] = start_date.isoformat()
            result["end_date"] = end_date.isoformat()
        if year:
            result["year"] = year

        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/monthly-summary")
async def get_monthly_summary(
    session: Session = Depends(get_db_session),
    year: int | None = Query(None, description="Year for analysis (defaults to current year)"),
    start_date: date | None = Query(None, description="Start date for analysis"),
    end_date: date | None = Query(None, description="End date for analysis"),
) -> dict[str, Any]:
    """Get monthly income/spending/saving breakdown."""
    try:
        # If year is provided, convert to start_date and end_date
        if year and not start_date and not end_date:
            start_date = date(year, 1, 1)
            end_date = date(year, 12, 31)

        result = AnalyticsService.get_monthly_summary(session, year, start_date, end_date)
        # Add date range information for frontend charts
        if year:
            result["year"] = year
        if start_date and end_date:
            result["start_date"] = start_date.isoformat()
            result["end_date"] = end_date.isoformat()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/category-breakdown")
async def get_category_breakdown(
    session: Session = Depends(get_db_session),
    start_date: date | None = Query(None, description="Start date for analysis"),
    end_date: date | None = Query(None, description="End date for analysis"),
    category_type: str | None = Query(None, description="Filter by category type"),
) -> dict[str, Any]:
    """Get category-wise spending analysis."""
    try:
        result = AnalyticsService.get_category_breakdown(session, start_date, end_date, category_type)
        # Add date range information for frontend charts
        if start_date and end_date:
            result["start_date"] = start_date.isoformat()
            result["end_date"] = end_date.isoformat()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/savings-tracking")
async def get_savings_tracking(
    session: Session = Depends(get_db_session),
    year: int | None = Query(None, description="Year for analysis (defaults to current year)"),
    start_date: date | None = Query(None, description="Start date for analysis"),
    end_date: date | None = Query(None, description="End date for analysis"),
) -> dict[str, Any]:
    """Get savings analysis with monthly and cumulative tracking."""
    try:
        # If year is provided, convert to start_date and end_date
        if year and not start_date and not end_date:
            start_date = date(year, 1, 1)
            end_date = date(year, 12, 31)

        result = AnalyticsService.get_savings_tracking(session, year, start_date, end_date)
        # Add date range information for frontend charts
        if year:
            result["year"] = year
        if start_date and end_date:
            result["start_date"] = start_date.isoformat()
            result["end_date"] = end_date.isoformat()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/top-transactions")
async def get_top_transactions(
    session: Session = Depends(get_db_session),
    year: int | None = Query(None, description="Year for analysis (defaults to current year)"),
    month: int | None = Query(None, description="Month for analysis (1-12)"),
    limit: int = Query(5, description="Number of top transactions to return"),
) -> dict[str, Any]:
    """Get top spending transactions by month."""
    try:
        result = AnalyticsService.get_top_transactions_by_month(session, year, month, limit)
        if year:
            result["year"] = year
        if month:
            result["month"] = month
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/year-over-year")
async def get_year_over_year_comparison(
    session: Session = Depends(get_db_session),
    category_type: str | None = Query(None, description="Filter by category type (spending/income/saving)"),
    years: str | None = Query(None, description="Comma-separated list of years to compare"),
) -> dict[str, Any]:
    """Get year-over-year category comparison with totals and monthly averages."""
    try:
        # Parse years if provided
        years_list = None
        if years:
            try:
                years_list = [int(y.strip()) for y in years.split(",")]
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="Invalid years format. Use comma-separated integers."
                ) from None

        result = AnalyticsService.get_year_over_year_comparison(session, category_type, years_list)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/category-cumulative")
async def get_category_cumulative_data(
    session: Session = Depends(get_db_session),
    category_id: int = Query(..., description="Category ID for cumulative data"),
    years: str | None = Query(None, description="Comma-separated list of years"),
) -> dict[str, Any]:
    """Get monthly cumulative data for a specific category across multiple years."""
    try:
        # Parse years if provided
        years_list = None
        if years:
            try:
                years_list = [int(y.strip()) for y in years.split(",")]
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="Invalid years format. Use comma-separated integers."
                ) from None

        result = AnalyticsService.get_category_cumulative_data(session, category_id, years_list)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/categories")
async def get_categories(session: Session = Depends(get_db_session)) -> dict[str, Any]:
    """Get all active categories for selection."""
    try:
        from fafycat.api.services import CategoryService

        categories = CategoryService.get_categories(session)
        return {"categories": categories}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/available-years")
async def get_available_years(session: Session = Depends(get_db_session)) -> dict[str, Any]:
    """Get all years that have transaction data for the year selector."""
    try:
        result = AnalyticsService.get_available_years(session)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


# HTML endpoints for HTMX integration
@router.get("/budget-variance-html", response_class=HTMLResponse)
async def get_budget_variance_html(
    session: Session = Depends(get_db_session),
    start_date: date | None = Query(None, description="Start date for analysis"),
    end_date: date | None = Query(None, description="End date for analysis"),
) -> HTMLResponse:
    """Get budget variance data as HTML table for HTMX."""
    try:
        data = AnalyticsService.get_budget_variance(session, start_date, end_date)

        # Generate HTML table
        table_html = """
        <div class="table-container">
            <table class="min-w-full">
                <thead>
                    <tr>
                        <th>Category</th>
                        <th>Budget</th>
                        <th>Actual</th>
                        <th>Variance</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
        """

        for variance in data["variances"]:
            status_style = "color: var(--color-spending)" if variance["is_overspent"] else "color: var(--color-success)"
            status_text = "Over Budget" if variance["is_overspent"] else "Under Budget"

            table_html += f"""
                    <tr>
                        <td>
                            {html.escape(str(variance["category_name"]))}
                        </td>
                        <td>€{variance["budget"]:.2f}</td>
                        <td>€{variance["actual"]:.2f}</td>
                        <td>
                            €{variance["variance"]:.2f} ({variance["variance_percentage"]:.1f}%)
                        </td>
                        <td style="{status_style}">{status_text}</td>
                    </tr>
            """

        # Add summary row
        summary = data["summary"]
        summary_style = (
            "color: var(--color-spending)" if summary["total_variance"] < 0 else "color: var(--color-success)"
        )

        table_html += f"""
                    <tr class="font-bold" style="background: var(--bg-hover)">
                        <td>TOTAL</td>
                        <td>
                            €{summary["total_budget"]:.2f}
                        </td>
                        <td>
                            €{summary["total_actual"]:.2f}
                        </td>
                        <td style="{summary_style}">
                            €{summary["total_variance"]:.2f} ({summary["total_variance_percentage"]:.1f}%)
                        </td>
                        <td style="{summary_style}">
                            {"Over Budget" if summary["total_variance"] < 0 else "Under Budget"}
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
        <script>
            // Update chart with new data
            updateBudgetVarianceChart({json.dumps(data)});
        </script>
        """

        return HTMLResponse(content=table_html)
    except Exception as e:
        return HTMLResponse(content=f'<div class="alert alert-error">Error: {html.escape(str(e))}</div>')

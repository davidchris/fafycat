"""Analytics API endpoints for FafyCat."""

import json
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from api.dependencies import get_db_session
from api.services import AnalyticsService

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/budget-variance")
async def get_budget_variance(
    session: Session = Depends(get_db_session),
    start_date: date | None = Query(None, description="Start date for analysis"),
    end_date: date | None = Query(None, description="End date for analysis"),
) -> dict[str, Any]:
    """Get budget vs actual spending variance by category."""
    try:
        return AnalyticsService.get_budget_variance(session, start_date, end_date)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/monthly-summary")
async def get_monthly_summary(
    session: Session = Depends(get_db_session),
    year: int | None = Query(None, description="Year for analysis (defaults to current year)"),
) -> dict[str, Any]:
    """Get monthly income/spending/saving breakdown."""
    try:
        return AnalyticsService.get_monthly_summary(session, year)
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
        return AnalyticsService.get_category_breakdown(session, start_date, end_date, category_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/savings-tracking")
async def get_savings_tracking(
    session: Session = Depends(get_db_session),
    year: int | None = Query(None, description="Year for analysis (defaults to current year)"),
) -> dict[str, Any]:
    """Get savings analysis with monthly and cumulative tracking."""
    try:
        return AnalyticsService.get_savings_tracking(session, year)
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
        html = """
        <div class="overflow-x-auto">
            <table class="min-w-full bg-white border border-gray-200">
                <thead class="bg-gray-50">
                    <tr>
                        <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Category</th>
                        <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Budget</th>
                        <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Actual</th>
                        <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Variance</th>
                        <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                    </tr>
                </thead>
                <tbody class="bg-white divide-y divide-gray-200">
        """

        for variance in data["variances"]:
            status_color = "text-red-600" if variance["is_overspent"] else "text-green-600"
            status_text = "Over Budget" if variance["is_overspent"] else "Under Budget"

            html += f"""
                    <tr>
                        <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">{variance["category_name"]}</td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">€{variance["budget"]:.2f}</td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">€{variance["actual"]:.2f}</td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">€{variance["variance"]:.2f} ({variance["variance_percentage"]:.1f}%)</td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm {status_color}">{status_text}</td>
                    </tr>
            """

        # Add summary row
        summary = data["summary"]
        summary_color = "text-red-600" if summary["total_variance"] < 0 else "text-green-600"

        html += f"""
                    <tr class="bg-gray-50 font-bold">
                        <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">TOTAL</td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">€{summary["total_budget"]:.2f}</td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">€{summary["total_actual"]:.2f}</td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm {summary_color}">€{summary["total_variance"]:.2f} ({summary["total_variance_percentage"]:.1f}%)</td>
                        <td class="px-6 py-4 whitespace-nowrap text-sm {summary_color}">
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

        return HTMLResponse(content=html)
    except Exception as e:
        return HTMLResponse(content=f'<div class="text-red-600">Error: {str(e)}</div>')

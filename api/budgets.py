"""Budget management API endpoints for yearly budgets."""

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.dependencies import get_db_session
from api.services import BudgetService

router = APIRouter(prefix="/api/budgets", tags=["budgets"])


@router.get("/years")
async def get_years_with_budgets(session: Session = Depends(get_db_session)) -> dict[str, Any]:
    """Get all years that have budget plans defined."""
    try:
        years = BudgetService.get_years_with_budgets(session)
        current_year = date.today().year

        # Ensure current year is always in the list
        if current_year not in years:
            years.append(current_year)
            years.sort(reverse=True)

        return {"years": years, "current_year": current_year, "total_years": len(years)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{year}")
async def get_budgets_for_year(year: int, session: Session = Depends(get_db_session)) -> dict[str, Any]:
    """Get all budgets for a specific year."""
    try:
        if year < 2020 or year > 2030:
            raise HTTPException(status_code=400, detail="Year must be between 2020 and 2030")

        return BudgetService.get_budgets_for_year(session, year)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.put("/{year}/{category_id}")
async def set_budget_for_category_year(
    year: int,
    category_id: int,
    monthly_budget: float = Query(..., ge=0.0, description="Monthly budget amount"),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Set or update budget for a specific category and year."""
    try:
        if year < 2020 or year > 2030:
            raise HTTPException(status_code=400, detail="Year must be between 2020 and 2030")

        success = BudgetService.set_budget_for_category_year(session, category_id, year, monthly_budget)

        if not success:
            raise HTTPException(status_code=404, detail="Category not found or inactive")

        return {"status": "success", "category_id": category_id, "year": year, "monthly_budget": monthly_budget}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/{year}/{category_id}")
async def delete_budget_for_category_year(
    year: int,
    category_id: int,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Delete budget plan for a specific category and year (falls back to category default)."""
    try:
        success = BudgetService.delete_budget_for_category_year(session, category_id, year)

        if not success:
            raise HTTPException(status_code=404, detail="Budget plan not found")

        return {"status": "success", "message": f"Budget plan deleted for category {category_id} and year {year}"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{target_year}/copy-from/{source_year}")
async def copy_budgets_from_year(
    target_year: int,
    source_year: int,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Copy all budgets from source year to target year."""
    try:
        if target_year < 2020 or target_year > 2030:
            raise HTTPException(status_code=400, detail="Target year must be between 2020 and 2030")

        if source_year < 2020 or source_year > 2030:
            raise HTTPException(status_code=400, detail="Source year must be between 2020 and 2030")

        if target_year == source_year:
            raise HTTPException(status_code=400, detail="Target year cannot be the same as source year")

        result = BudgetService.copy_budgets_from_year(session, source_year, target_year)

        return {"status": "success", **result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{year}/{category_id}")
async def get_budget_for_category_year(
    year: int,
    category_id: int,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """Get budget for a specific category and year."""
    try:
        budget = BudgetService.get_budget_for_category_year(session, category_id, year)

        return {"category_id": category_id, "year": year, "monthly_budget": budget}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

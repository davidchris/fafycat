"""API routes for category operations."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.dependencies import get_db_session
from api.models import CategoryCreate, CategoryResponse, CategoryUpdate
from api.services import CategoryService

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("/", response_model=list[CategoryResponse])
async def get_categories(
    include_inactive: bool = False, db: Session = Depends(get_db_session)
) -> list[CategoryResponse]:
    """Get all categories."""
    return CategoryService.get_categories(session=db, include_inactive=include_inactive)


@router.post("/", response_model=CategoryResponse)
async def create_category(category: CategoryCreate, db: Session = Depends(get_db_session)) -> CategoryResponse:
    """Create a new category."""
    return CategoryService.create_category(session=db, category=category)


@router.put("/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: int, update: CategoryUpdate, db: Session = Depends(get_db_session)
) -> CategoryResponse:
    """Update an existing category."""
    result = CategoryService.update_category(session=db, category_id=category_id, update=update)

    if not result:
        raise HTTPException(status_code=404, detail="Category not found")

    return result


@router.delete("/{category_id}")
async def delete_category(category_id: int, db: Session = Depends(get_db_session)) -> dict:
    """Delete a category."""
    # For now, we'll implement deactivation instead of deletion to preserve data integrity
    update = CategoryUpdate(is_active=False)
    result = CategoryService.update_category(session=db, category_id=category_id, update=update)

    if not result:
        raise HTTPException(status_code=404, detail="Category not found")

    return {"message": "Category deactivated"}


@router.put("/{category_id}/budget")
async def update_category_budget(category_id: int, budget: float, db: Session = Depends(get_db_session)) -> dict:
    """Update category budget."""
    update = CategoryUpdate(budget=budget)
    result = CategoryService.update_category(session=db, category_id=category_id, update=update)

    if not result:
        raise HTTPException(status_code=404, detail="Category not found")

    return {"message": "Budget updated", "budget": budget}


@router.put("/{category_id}/type")
async def update_category_type(category_id: int, type: str, db: Session = Depends(get_db_session)) -> dict:
    """Update category type."""
    if type not in ["spending", "income", "saving"]:
        raise HTTPException(status_code=400, detail="Invalid category type")

    update = CategoryUpdate(type=type)
    result = CategoryService.update_category(session=db, category_id=category_id, update=update)

    if not result:
        raise HTTPException(status_code=404, detail="Category not found")

    return {"message": "Category type updated", "type": type}

"""Service layer for database operations."""

import math
from datetime import date
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from api.models import CategoryCreate, CategoryResponse, CategoryUpdate, TransactionResponse, TransactionUpdate
from src.fafycat.core.database import CategoryORM, TransactionORM
from src.fafycat.core.database import get_categories as db_get_categories
from src.fafycat.core.models import CategoryType


class TransactionService:
    """Service for transaction operations."""

    @staticmethod
    def get_transactions(
        session: Session,
        skip: int = 0,
        limit: int = 100,
        category: str | None = None,
        is_reviewed: bool | None = None,
        confidence_lt: float | None = None,
    ) -> list[TransactionResponse]:
        """Get transactions with filtering."""
        query = session.query(TransactionORM).options(
            joinedload(TransactionORM.category), joinedload(TransactionORM.predicted_category)
        )

        # Apply filters
        if category:
            query = query.join(CategoryORM, TransactionORM.category_id == CategoryORM.id)
            query = query.filter(CategoryORM.name == category)

        if is_reviewed is not None:
            query = query.filter(TransactionORM.is_reviewed == is_reviewed)

        if confidence_lt is not None:
            # Include transactions with null confidence (treat as needing review) OR confidence below threshold
            query = query.filter(
                (TransactionORM.confidence_score.is_(None)) | (TransactionORM.confidence_score < confidence_lt)
            )

        # Apply pagination
        query = query.order_by(TransactionORM.date.desc())
        query = query.offset(skip).limit(limit)

        transactions = query.all()

        # Convert to response models
        return [
            TransactionResponse(
                id=t.id,
                date=t.date,
                description=(f"{t.name} - {t.purpose}".rstrip(" -") if t.purpose else t.name),
                amount=t.amount,
                account="",  # Will be added when we migrate account info
                predicted_category=t.predicted_category.name if t.predicted_category else None,
                actual_category=t.category.name if t.category else None,
                confidence=t.confidence_score,
                is_reviewed=t.is_reviewed,
                created_at=t.imported_at,
                updated_at=t.imported_at,  # Will update when we add updated_at to TransactionORM
            )
            for t in transactions
        ]

    @staticmethod
    def get_pending_transactions(
        session: Session, limit: int = 50, confidence_lt: float | None = None
    ) -> list[TransactionResponse]:
        """Get transactions that need review."""
        return TransactionService.get_transactions(
            session=session, limit=limit, is_reviewed=False, confidence_lt=confidence_lt
        )

    @staticmethod
    def get_transactions_with_pagination(
        session: Session,
        skip: int = 0,
        limit: int = 50,
        is_reviewed: bool | None = None,
        confidence_lt: float | None = None,
        review_priority: str | None = None,
        sort_by: str = "date",
        sort_order: str = "desc",
        search: str = "",
    ) -> dict:
        """Get transactions with pagination and enhanced filtering."""
        # Build base query
        query = session.query(TransactionORM).options(
            joinedload(TransactionORM.category), joinedload(TransactionORM.predicted_category)
        )

        # Apply filters
        if is_reviewed is not None:
            query = query.filter(TransactionORM.is_reviewed == is_reviewed)

        if confidence_lt is not None:
            # Include transactions with null confidence (treat as needing review) OR confidence below threshold
            query = query.filter(
                (TransactionORM.confidence_score.is_(None)) | (TransactionORM.confidence_score < confidence_lt)
            )

        if review_priority is not None:
            if review_priority == "high_priority":
                # Show both high priority and quality check transactions
                query = query.filter(TransactionORM.review_priority.in_(["high", "quality_check"]))
            else:
                query = query.filter(TransactionORM.review_priority == review_priority)

        if search.strip():
            # Search in transaction name, purpose, and description fields
            search_term = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    TransactionORM.name.ilike(search_term),
                    TransactionORM.purpose.ilike(search_term),
                    # Also search in the concatenated description
                    func.concat(TransactionORM.name, " - ", func.coalesce(TransactionORM.purpose, "")).ilike(
                        search_term
                    ),
                )
            )

        # Get total count before applying pagination
        total_count = query.count()

        # Apply sorting
        sort_column = getattr(TransactionORM, sort_by, TransactionORM.date)
        query = query.order_by(sort_column.asc()) if sort_order.lower() == "asc" else query.order_by(sort_column.desc())

        # Apply pagination
        query = query.offset(skip).limit(limit)
        transactions = query.all()

        # Calculate pagination info
        page = (skip // limit) + 1
        total_pages = math.ceil(total_count / limit) if total_count > 0 else 1
        has_prev = page > 1
        has_next = page < total_pages

        # Convert to response models
        transaction_responses = [
            TransactionResponse(
                id=t.id,
                date=t.date,
                description=(f"{t.name} - {t.purpose}".rstrip(" -") if t.purpose else t.name),
                amount=t.amount,
                account="",  # Will be added when we migrate account info
                predicted_category=t.predicted_category.name if t.predicted_category else None,
                actual_category=t.category.name if t.category else None,
                confidence=t.confidence_score,
                is_reviewed=t.is_reviewed,
                created_at=t.imported_at,
                updated_at=t.imported_at,  # Will update when we add updated_at to TransactionORM
            )
            for t in transactions
        ]

        return {
            "transactions": transaction_responses,
            "pagination_info": {
                "page": page,
                "total_pages": total_pages,
                "total_count": total_count,
                "has_prev": has_prev,
                "has_next": has_next,
                "page_size": limit,
            },
        }

    @staticmethod
    def update_transaction_category(
        session: Session, transaction_id: str, update: TransactionUpdate
    ) -> TransactionResponse | None:
        """Update transaction category."""
        transaction = session.query(TransactionORM).filter(TransactionORM.id == transaction_id).first()

        if not transaction:
            return None

        # Find category by name
        category = session.query(CategoryORM).filter(CategoryORM.name == update.actual_category).first()

        if not category:
            return None

        # Update transaction
        transaction.category_id = category.id
        transaction.is_reviewed = update.is_reviewed
        session.commit()

        # Return updated transaction
        return TransactionResponse(
            id=transaction.id,
            date=transaction.date,
            description=(
                f"{transaction.name} - {transaction.purpose}".rstrip(" -") if transaction.purpose else transaction.name
            ),
            amount=transaction.amount,
            account="",
            predicted_category=transaction.predicted_category.name if transaction.predicted_category else None,
            actual_category=category.name,
            confidence=transaction.confidence_score,
            is_reviewed=transaction.is_reviewed,
            created_at=transaction.imported_at,
            updated_at=transaction.imported_at,
        )


class CategoryService:
    """Service for category operations."""

    @staticmethod
    def get_categories(session: Session, include_inactive: bool = False) -> list[CategoryResponse]:
        """Get all categories."""
        categories = db_get_categories(session, active_only=not include_inactive)

        return [
            CategoryResponse(
                id=c.id,
                name=c.name,
                type=c.type,
                is_active=c.is_active,
                budget=c.budget,
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
            for c in categories
        ]

    @staticmethod
    def create_category(session: Session, category: CategoryCreate) -> CategoryResponse:
        """Create a new category."""
        db_category = CategoryORM(name=category.name, type=category.type, budget=category.budget or 0.0)

        session.add(db_category)
        session.commit()
        session.refresh(db_category)

        return CategoryResponse(
            id=db_category.id,
            name=db_category.name,
            type=db_category.type,
            is_active=db_category.is_active,
            budget=db_category.budget,
            created_at=db_category.created_at,
            updated_at=db_category.updated_at,
        )

    @staticmethod
    def update_category(session: Session, category_id: int, update: CategoryUpdate) -> CategoryResponse | None:
        """Update an existing category."""
        category = session.query(CategoryORM).filter(CategoryORM.id == category_id).first()

        if not category:
            return None

        # Update fields if provided
        if update.name is not None:
            category.name = update.name
        if update.type is not None:
            category.type = update.type
        if update.is_active is not None:
            category.is_active = update.is_active
        if update.budget is not None:
            category.budget = update.budget

        session.commit()

        return CategoryResponse(
            id=category.id,
            name=category.name,
            type=category.type,
            is_active=category.is_active,
            budget=category.budget,
            created_at=category.created_at,
            updated_at=category.updated_at,
        )


class AnalyticsService:
    """Service for analytics operations."""

    @staticmethod
    def get_budget_variance(
        session: Session, start_date: date | None = None, end_date: date | None = None
    ) -> dict[str, Any]:
        """Get budget vs actual spending variance by category."""
        # Default to current month if no dates provided
        if not start_date:
            today = date.today()
            start_date = today.replace(day=1)
        if not end_date:
            end_date = date.today()

        # Query spending categories with their budgets and actual spending
        query = (
            session.query(
                CategoryORM.id,
                CategoryORM.name,
                CategoryORM.budget,
                func.coalesce(func.sum(TransactionORM.amount), 0).label("actual_amount"),
            )
            .outerjoin(TransactionORM, CategoryORM.id == TransactionORM.category_id)
            .filter(CategoryORM.type == CategoryType.SPENDING)
            .filter(CategoryORM.is_active)
        )

        # Apply date filters if transactions exist
        if start_date and end_date:
            query = query.filter(
                or_(
                    TransactionORM.date.is_(None),  # Include categories with no transactions
                    TransactionORM.date.between(start_date, end_date),
                )
            )

        query = query.group_by(CategoryORM.id, CategoryORM.name, CategoryORM.budget)

        results = query.all()

        variances = []
        total_budget = 0
        total_actual = 0

        for result in results:
            budget = float(result.budget)
            actual = float(result.actual_amount)
            variance = budget - actual
            variance_pct = (variance / budget * 100) if budget > 0 else 0

            variances.append(
                {
                    "category_id": result.id,
                    "category_name": result.name,
                    "budget": budget,
                    "actual": actual,
                    "variance": variance,
                    "variance_percentage": variance_pct,
                    "is_overspent": variance < 0,
                }
            )

            total_budget += budget
            total_actual += actual

        # Sort by absolute variance (largest deviations first)
        variances.sort(key=lambda x: abs(x["variance"]), reverse=True)

        return {
            "variances": variances,
            "summary": {
                "total_budget": total_budget,
                "total_actual": total_actual,
                "total_variance": total_budget - total_actual,
                "total_variance_percentage": ((total_budget - total_actual) / total_budget * 100)
                if total_budget > 0
                else 0,
            },
            "date_range": {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        }

    @staticmethod
    def get_monthly_summary(session: Session, year: int | None = None) -> dict[str, Any]:
        """Get monthly income/spending/saving breakdown."""
        if not year:
            year = date.today().year

        # Query for monthly aggregations by category type
        query = (
            session.query(
                func.strftime("%m", TransactionORM.date).label("month"),
                CategoryORM.type,
                func.sum(TransactionORM.amount).label("total_amount"),
            )
            .join(CategoryORM, TransactionORM.category_id == CategoryORM.id)
            .filter(func.strftime("%Y", TransactionORM.date) == str(year))
            .group_by(func.strftime("%m", TransactionORM.date), CategoryORM.type)
            .order_by(func.strftime("%m", TransactionORM.date))
        )

        results = query.all()

        # Initialize monthly data structure
        monthly_data = {}
        for month in range(1, 13):
            month_str = f"{month:02d}"
            monthly_data[month_str] = {
                "month": month_str,
                "income": 0.0,
                "spending": 0.0,
                "saving": 0.0,
                "profit_loss": 0.0,  # income - spending (excluding savings)
            }

        # Populate with actual data
        for result in results:
            month = result.month
            category_type = result.type
            amount = float(result.total_amount)

            if month in monthly_data:
                if category_type == CategoryType.INCOME:
                    monthly_data[month]["income"] = amount
                elif category_type == CategoryType.SPENDING:
                    monthly_data[month]["spending"] = amount
                elif category_type == CategoryType.SAVING:
                    monthly_data[month]["saving"] = amount

        # Calculate profit/loss for each month
        for month_data in monthly_data.values():
            month_data["profit_loss"] = month_data["income"] - month_data["spending"]

        # Calculate cumulative profit/loss
        cumulative_profit_loss = 0
        for month_data in monthly_data.values():
            cumulative_profit_loss += month_data["profit_loss"]
            month_data["cumulative_profit_loss"] = cumulative_profit_loss

        return {
            "year": year,
            "monthly_data": list(monthly_data.values()),
            "yearly_totals": {
                "income": sum(m["income"] for m in monthly_data.values()),
                "spending": sum(m["spending"] for m in monthly_data.values()),
                "saving": sum(m["saving"] for m in monthly_data.values()),
                "profit_loss": sum(m["profit_loss"] for m in monthly_data.values()),
            },
        }

    @staticmethod
    def get_category_breakdown(
        session: Session, start_date: date | None = None, end_date: date | None = None, category_type: str | None = None
    ) -> dict[str, Any]:
        """Get category-wise spending analysis."""
        # Default to current month if no dates provided
        if not start_date:
            today = date.today()
            start_date = today.replace(day=1)
        if not end_date:
            end_date = date.today()

        # Build query
        query = (
            session.query(
                CategoryORM.id,
                CategoryORM.name,
                CategoryORM.type,
                CategoryORM.budget,
                func.count(TransactionORM.id).label("transaction_count"),
                func.sum(TransactionORM.amount).label("total_amount"),
            )
            .join(TransactionORM, CategoryORM.id == TransactionORM.category_id)
            .filter(TransactionORM.date.between(start_date, end_date))
            .filter(CategoryORM.is_active)
        )

        # Apply category type filter if provided
        if category_type:
            query = query.filter(CategoryORM.type == category_type)

        query = query.group_by(CategoryORM.id, CategoryORM.name, CategoryORM.type, CategoryORM.budget)
        query = query.order_by(func.sum(TransactionORM.amount).desc())

        results = query.all()

        categories = []
        total_amount = 0

        for result in results:
            amount = float(result.total_amount) if result.total_amount else 0
            budget = float(result.budget)

            categories.append(
                {
                    "category_id": result.id,
                    "category_name": result.name,
                    "category_type": result.type,
                    "budget": budget,
                    "amount": amount,
                    "transaction_count": result.transaction_count,
                    "budget_variance": budget - amount if result.type == CategoryType.SPENDING else None,
                }
            )

            total_amount += amount

        # Calculate percentages
        for category in categories:
            category["percentage"] = (category["amount"] / total_amount * 100) if total_amount > 0 else 0

        return {
            "categories": categories,
            "summary": {"total_amount": total_amount, "total_categories": len(categories)},
            "date_range": {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        }

    @staticmethod
    def get_savings_tracking(session: Session, year: int | None = None) -> dict[str, Any]:
        """Get savings analysis with monthly and cumulative tracking."""
        if not year:
            year = date.today().year

        # Query for monthly savings data
        query = (
            session.query(
                func.strftime("%m", TransactionORM.date).label("month"),
                func.sum(TransactionORM.amount).label("savings_amount"),
            )
            .join(CategoryORM, TransactionORM.category_id == CategoryORM.id)
            .filter(CategoryORM.type == CategoryType.SAVING)
            .filter(func.strftime("%Y", TransactionORM.date) == str(year))
            .group_by(func.strftime("%m", TransactionORM.date))
            .order_by(func.strftime("%m", TransactionORM.date))
        )

        results = query.all()

        # Initialize monthly savings data
        monthly_savings = {}
        for month in range(1, 13):
            month_str = f"{month:02d}"
            monthly_savings[month_str] = {"month": month_str, "amount": 0.0}

        # Populate with actual data
        for result in results:
            month = result.month
            amount = float(result.savings_amount) if result.savings_amount else 0
            monthly_savings[month]["amount"] = amount

        # Calculate cumulative savings
        cumulative_savings = 0
        for month_data in monthly_savings.values():
            cumulative_savings += month_data["amount"]
            month_data["cumulative_amount"] = cumulative_savings

        # Calculate statistics
        amounts = [m["amount"] for m in monthly_savings.values() if m["amount"] > 0]

        stats = {
            "total_savings": cumulative_savings,
            "average_monthly": sum(amounts) / len(amounts) if amounts else 0,
            "median_monthly": sorted(amounts)[len(amounts) // 2] if amounts else 0,
            "months_with_savings": len(amounts),
        }

        return {"year": year, "monthly_savings": list(monthly_savings.values()), "statistics": stats}

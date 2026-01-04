"""Service layer for database operations."""

import math
from datetime import date, datetime
from typing import Any

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, joinedload

from api.models import CategoryCreate, CategoryResponse, CategoryUpdate, TransactionResponse, TransactionUpdate
from src.fafycat.core.database import BudgetPlanORM, CategoryORM, TransactionORM
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
        category: str | None = None,
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

        if category:
            if category == "uncategorized":
                # Filter for transactions with no category (neither actual nor predicted)
                query = query.filter(
                    and_(TransactionORM.category_id.is_(None), TransactionORM.predicted_category_id.is_(None))
                )
            else:
                # Filter by effective/final category: actual_category takes precedence over predicted_category
                # This means: if actual_category exists, use it; otherwise use predicted_category
                query = query.filter(
                    or_(
                        # Case 1: Has actual category and it matches
                        and_(
                            TransactionORM.category_id.is_not(None),
                            TransactionORM.category.has(CategoryORM.name == category),
                        ),
                        # Case 2: No actual category, but predicted category matches
                        and_(
                            TransactionORM.category_id.is_(None),
                            TransactionORM.predicted_category_id.is_not(None),
                            TransactionORM.predicted_category.has(CategoryORM.name == category),
                        ),
                    )
                )

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
        """Get budget vs actual spending variance by category with year-specific budgets."""
        start_date, end_date = AnalyticsService._get_default_dates(start_date, end_date)

        # Get transaction data grouped by category and year
        category_data = AnalyticsService._get_transaction_category_data(session, start_date, end_date)

        # Include categories with budgets but no transactions
        AnalyticsService._add_budgeted_categories_without_transactions(session, category_data, start_date, end_date)

        # Build final variance data
        return AnalyticsService._build_variance_result(category_data, start_date, end_date)

    @staticmethod
    def _get_default_dates(start_date: date | None, end_date: date | None) -> tuple[date, date]:
        """Get default start and end dates if not provided."""
        if not start_date:
            today = date.today()
            start_date = today.replace(day=1)
        if not end_date:
            end_date = date.today()
        return start_date, end_date

    @staticmethod
    def _get_transaction_category_data(session: Session, start_date: date, end_date: date) -> dict[int, dict]:
        """Get transaction data grouped by category and year."""
        # Group transactions by year and category to handle cross-year periods
        query = (
            session.query(
                CategoryORM.id,
                CategoryORM.name,
                CategoryORM.type,
                func.strftime("%Y", TransactionORM.date).label("year"),
                func.coalesce(func.sum(TransactionORM.amount), 0).label("actual_amount"),
            )
            .join(
                CategoryORM,
                CategoryORM.id == func.coalesce(TransactionORM.category_id, TransactionORM.predicted_category_id),
            )
            .filter(CategoryORM.type == CategoryType.SPENDING)
            .filter(CategoryORM.is_active)
            .filter(TransactionORM.date.between(start_date, end_date))
            .filter(or_(TransactionORM.category_id.is_not(None), TransactionORM.predicted_category_id.is_not(None)))
            .group_by(CategoryORM.id, CategoryORM.name, CategoryORM.type, func.strftime("%Y", TransactionORM.date))
        )

        results = query.all()
        category_data = {}

        for result in results:
            category_id = result.id
            category_name = result.name
            year = int(result.year)
            actual_amount = float(result.actual_amount)

            if category_id not in category_data:
                category_data[category_id] = {
                    "category_name": category_name,
                    "yearly_data": {},
                    "total_actual": 0,
                    "total_budget": 0,
                }

            # Get year-specific budget and calculate period budget
            year_budget = BudgetService.get_budget_for_category_year(session, category_id, year)
            year_start = max(start_date, date(year, 1, 1))
            year_end = min(end_date, date(year, 12, 31))
            months_in_year = (year_end.year - year_start.year) * 12 + year_end.month - year_start.month + 1
            period_budget = year_budget * months_in_year

            category_data[category_id]["yearly_data"][year] = {
                "budget": period_budget,
                "actual": actual_amount,
                "months": months_in_year,
            }

            category_data[category_id]["total_actual"] += actual_amount
            category_data[category_id]["total_budget"] += period_budget

        return category_data

    @staticmethod
    def _add_budgeted_categories_without_transactions(
        session: Session, category_data: dict[int, dict], start_date: date, end_date: date
    ) -> None:
        """Add categories with budgets but no transactions to the data."""
        spending_categories = (
            session.query(CategoryORM).filter(CategoryORM.type == CategoryType.SPENDING, CategoryORM.is_active).all()
        )

        for category in spending_categories:
            if category.id not in category_data:
                total_budget = AnalyticsService._calculate_total_budget_for_period(
                    session, category.id, start_date, end_date
                )

                if total_budget > 0:
                    category_data[category.id] = {
                        "category_name": category.name,
                        "yearly_data": {},
                        "total_actual": 0,
                        "total_budget": total_budget,
                    }

    @staticmethod
    def _calculate_total_budget_for_period(
        session: Session, category_id: int, start_date: date, end_date: date
    ) -> float:
        """Calculate total budget for a category across a date range."""
        total_budget = 0
        current_date = start_date

        while current_date <= end_date:
            year = current_date.year
            year_budget = BudgetService.get_budget_for_category_year(session, category_id, year)

            year_start = max(start_date, date(year, 1, 1))
            year_end = min(end_date, date(year, 12, 31))
            months_in_year = (year_end.year - year_start.year) * 12 + year_end.month - year_start.month + 1

            total_budget += year_budget * months_in_year

            current_date = date(year + 1, 1, 1)
            if current_date > end_date:
                break

        return total_budget

    @staticmethod
    def _build_variance_result(category_data: dict[int, dict], start_date: date, end_date: date) -> dict[str, Any]:
        """Build the final variance result from category data."""
        variances = []
        total_budget = 0
        total_actual = 0

        for category_id, data in category_data.items():
            budget = data["total_budget"]
            actual = data["total_actual"]

            # Calculate variance based on spending vs income categories
            if budget > 0 and actual <= 0:  # Spending category
                displayed_actual = abs(actual)
                variance = budget - displayed_actual
                variance_pct = (variance / budget * 100) if budget > 0 else 0
            else:  # Income/saving categories
                displayed_actual = actual
                variance = budget - actual
                variance_pct = (variance / budget * 100) if budget > 0 else 0

            variances.append(
                {
                    "category_id": category_id,
                    "category_name": data["category_name"],
                    "budget": budget,
                    "actual": displayed_actual,
                    "variance": variance,
                    "variance_percentage": variance_pct,
                    "is_overspent": variance < 0,
                    "yearly_breakdown": data["yearly_data"],
                }
            )

            total_budget += budget
            total_actual += actual

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
    def get_monthly_summary(
        session: Session, year: int | None = None, start_date: date | None = None, end_date: date | None = None
    ) -> dict[str, Any]:
        """Get monthly income/spending/saving breakdown."""
        start_date, end_date, year = AnalyticsService._get_monthly_summary_dates(year, start_date, end_date)

        # Query for monthly aggregations by category type
        results = AnalyticsService._query_monthly_transactions(session, start_date, end_date)

        # Initialize and populate monthly data
        monthly_data = AnalyticsService._initialize_monthly_data(start_date, end_date)
        AnalyticsService._populate_monthly_data(monthly_data, results)
        AnalyticsService._calculate_profit_loss_and_cumulative(monthly_data)

        return AnalyticsService._build_monthly_summary_result(monthly_data, year)

    @staticmethod
    def _get_monthly_summary_dates(
        year: int | None, start_date: date | None, end_date: date | None
    ) -> tuple[date, date, int | None]:
        """Get the start and end dates for monthly summary."""
        if not year and not start_date:
            year = date.today().year

        if year and not start_date:
            start_date = date(year, 1, 1)
            end_date = date(year, 12, 31)
        elif not end_date:
            end_date = date.today()

        return start_date, end_date, year

    @staticmethod
    def _query_monthly_transactions(session: Session, start_date: date, end_date: date):
        """Query monthly transaction aggregations by category type."""
        query = (
            session.query(
                func.strftime("%m", TransactionORM.date).label("month"),
                CategoryORM.type,
                func.sum(TransactionORM.amount).label("total_amount"),
            )
            .join(
                CategoryORM,
                CategoryORM.id == func.coalesce(TransactionORM.category_id, TransactionORM.predicted_category_id),
            )
            .filter(TransactionORM.date.between(start_date, end_date))
            .filter(or_(TransactionORM.category_id.is_not(None), TransactionORM.predicted_category_id.is_not(None)))
            .group_by(func.strftime("%m", TransactionORM.date), CategoryORM.type)
            .order_by(func.strftime("%m", TransactionORM.date))
        )
        return query.all()

    @staticmethod
    def _initialize_monthly_data(start_date: date, end_date: date) -> dict[str, dict]:
        """Initialize monthly data structure for the specified date range."""
        monthly_data = {}
        current_date = start_date.replace(day=1)
        end_month = end_date.replace(day=1)

        while current_date <= end_month:
            month_str = f"{current_date.month:02d}"
            monthly_data[month_str] = {
                "month": month_str,
                "income": 0.0,
                "spending": 0.0,
                "saving": 0.0,
                "profit_loss": 0.0,
            }

            # Move to next month
            if current_date.month == 12:
                current_date = current_date.replace(year=current_date.year + 1, month=1)
            else:
                current_date = current_date.replace(month=current_date.month + 1)

        return monthly_data

    @staticmethod
    def _populate_monthly_data(monthly_data: dict[str, dict], results) -> None:
        """Populate monthly data with transaction results."""
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

    @staticmethod
    def _calculate_profit_loss_and_cumulative(monthly_data: dict[str, dict]) -> None:
        """Calculate profit/loss and cumulative profit/loss for each month."""
        cumulative_profit_loss = 0
        for month_data in monthly_data.values():
            month_data["profit_loss"] = month_data["income"] + month_data["spending"]
            cumulative_profit_loss += month_data["profit_loss"]
            month_data["cumulative_profit_loss"] = cumulative_profit_loss

    @staticmethod
    def _build_monthly_summary_result(monthly_data: dict[str, dict], year: int | None) -> dict[str, Any]:
        """Build the final monthly summary result."""
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
        # Use COALESCE to get effective category (actual takes precedence over predicted)
        query = (
            session.query(
                CategoryORM.id,
                CategoryORM.name,
                CategoryORM.type,
                CategoryORM.budget,
                func.count(TransactionORM.id).label("transaction_count"),
                func.sum(TransactionORM.amount).label("total_amount"),
            )
            .join(
                CategoryORM,
                CategoryORM.id == func.coalesce(TransactionORM.category_id, TransactionORM.predicted_category_id),
            )
            .filter(TransactionORM.date.between(start_date, end_date))
            .filter(CategoryORM.is_active)
            .filter(or_(TransactionORM.category_id.is_not(None), TransactionORM.predicted_category_id.is_not(None)))
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
    def get_savings_tracking(
        session: Session, year: int | None = None, start_date: date | None = None, end_date: date | None = None
    ) -> dict[str, Any]:
        """Get savings analysis with monthly and cumulative tracking."""
        if not year and not start_date:
            year = date.today().year

        # If only year is provided, set date range
        if year and not start_date:
            start_date = date(year, 1, 1)
            end_date = date(year, 12, 31)
        elif not end_date:
            end_date = date.today()

        # Query for monthly savings data
        # Use COALESCE to get effective category (actual takes precedence over predicted)
        query = (
            session.query(
                func.strftime("%m", TransactionORM.date).label("month"),
                func.sum(TransactionORM.amount).label("savings_amount"),
            )
            .join(
                CategoryORM,
                CategoryORM.id == func.coalesce(TransactionORM.category_id, TransactionORM.predicted_category_id),
            )
            .filter(CategoryORM.type == CategoryType.SAVING)
            .filter(TransactionORM.date.between(start_date, end_date))
            .filter(or_(TransactionORM.category_id.is_not(None), TransactionORM.predicted_category_id.is_not(None)))
            .group_by(func.strftime("%m", TransactionORM.date))
            .order_by(func.strftime("%m", TransactionORM.date))
        )

        results = query.all()

        # Initialize monthly savings data for the specified date range only
        monthly_savings = {}

        # Generate months only within the specified date range
        current_date = start_date.replace(day=1)  # Start from first day of start month
        end_month = end_date.replace(day=1)

        while current_date <= end_month:
            month_str = f"{current_date.month:02d}"
            monthly_savings[month_str] = {"month": month_str, "amount": 0.0}
            # Move to next month
            if current_date.month == 12:
                current_date = current_date.replace(year=current_date.year + 1, month=1)
            else:
                current_date = current_date.replace(month=current_date.month + 1)

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

    @staticmethod
    def get_top_transactions_by_month(
        session: Session, year: int | None = None, month: int | None = None, limit: int = 5
    ) -> dict[str, Any]:
        """Get top spending transactions by month."""
        if not year:
            year = date.today().year
        if not month:
            month = date.today().month

        # Query for spending transactions in the specified month
        query = (
            session.query(TransactionORM)
            .join(
                CategoryORM,
                CategoryORM.id == func.coalesce(TransactionORM.category_id, TransactionORM.predicted_category_id),
            )
            .filter(CategoryORM.type == CategoryType.SPENDING)
            .filter(func.strftime("%Y", TransactionORM.date) == str(year))
            .filter(func.strftime("%m", TransactionORM.date) == f"{month:02d}")
            .filter(or_(TransactionORM.category_id.is_not(None), TransactionORM.predicted_category_id.is_not(None)))
            .filter(TransactionORM.amount < 0)  # Only negative amounts (spending)
            .order_by(TransactionORM.amount.asc())  # Most negative first (largest spending)
            .limit(limit)
        )

        transactions = query.all()

        # Format transaction data
        top_transactions = []
        for transaction in transactions:
            # Get effective category
            category = transaction.category if transaction.category else transaction.predicted_category

            top_transactions.append(
                {
                    "id": transaction.id,
                    "date": transaction.date.isoformat(),
                    "description": f"{transaction.name} - {transaction.purpose}".rstrip(" -")
                    if transaction.purpose
                    else transaction.name,
                    "amount": abs(float(transaction.amount)),  # Show as positive for display
                    "category": category.name if category else "Unknown",
                    "merchant": transaction.name,
                }
            )

        # Calculate total spending for the month
        total_query = (
            session.query(func.sum(TransactionORM.amount))
            .join(
                CategoryORM,
                CategoryORM.id == func.coalesce(TransactionORM.category_id, TransactionORM.predicted_category_id),
            )
            .filter(CategoryORM.type == CategoryType.SPENDING)
            .filter(func.strftime("%Y", TransactionORM.date) == str(year))
            .filter(func.strftime("%m", TransactionORM.date) == f"{month:02d}")
            .filter(or_(TransactionORM.category_id.is_not(None), TransactionORM.predicted_category_id.is_not(None)))
        )

        total_spending = float(total_query.scalar() or 0)

        # Calculate percentage for each transaction
        for transaction in top_transactions:
            transaction["percentage_of_total"] = (
                (transaction["amount"] / abs(total_spending) * 100) if total_spending != 0 else 0
            )

        return {
            "year": year,
            "month": month,
            "month_name": date(year, month, 1).strftime("%B"),
            "top_transactions": top_transactions,
            "total_spending": abs(total_spending),
            "transactions_count": len(top_transactions),
        }

    @staticmethod
    def get_year_over_year_comparison(
        session: Session, category_type: str | None = None, years: list[int] | None = None
    ) -> dict[str, Any]:
        """Get year-over-year comparison of categories with totals and monthly averages."""
        # Auto-detect years if not provided
        if not years:
            year_query = session.query(func.distinct(func.strftime("%Y", TransactionORM.date))).order_by(
                func.strftime("%Y", TransactionORM.date).desc()
            )
            available_years = [int(y[0]) for y in year_query.all()]
            # Use up to 3 most recent years by default
            years = available_years[:3] if len(available_years) >= 3 else available_years

        if not years:
            return {"categories": [], "summary": {"years": [], "total_by_year": {}}}

        # Determine consistent date period when current year is included
        current_year = date.today().year
        end_date = None
        if current_year in years:
            # Get max date for current year to ensure fair comparison
            max_date_query = session.query(func.max(TransactionORM.date)).filter(
                func.strftime("%Y", TransactionORM.date) == str(current_year)
            )
            max_date_result = max_date_query.scalar()
            if max_date_result:
                end_date = max_date_result

        # Build base query
        query = (
            session.query(
                CategoryORM.id,
                CategoryORM.name,
                CategoryORM.type,
                func.strftime("%Y", TransactionORM.date).label("year"),
                func.count(TransactionORM.id).label("transaction_count"),
                func.sum(TransactionORM.amount).label("total_amount"),
            )
            .join(
                CategoryORM,
                CategoryORM.id == func.coalesce(TransactionORM.category_id, TransactionORM.predicted_category_id),
            )
            .filter(CategoryORM.is_active)
            .filter(or_(TransactionORM.category_id.is_not(None), TransactionORM.predicted_category_id.is_not(None)))
            .filter(func.strftime("%Y", TransactionORM.date).in_([str(y) for y in years]))
        )

        # Apply consistent date filtering when current year is included
        if end_date:
            # For each year, only include data up to the same month/day as the current year's max date
            date_conditions = []
            for year in years:
                year_end_date = date(year, end_date.month, end_date.day)
                date_conditions.append(
                    and_(func.strftime("%Y", TransactionORM.date) == str(year), TransactionORM.date <= year_end_date)
                )
            query = query.filter(or_(*date_conditions))

        # Apply category type filter if provided
        if category_type:
            query = query.filter(CategoryORM.type == category_type)

        query = query.group_by(
            CategoryORM.id, CategoryORM.name, CategoryORM.type, func.strftime("%Y", TransactionORM.date)
        )
        results = query.all()

        # Organize data by category
        category_data = {}
        yearly_totals = {year: 0.0 for year in years}

        for result in results:
            category_id = result.id
            category_name = result.name
            year = int(result.year)
            total_amount = float(result.total_amount) if result.total_amount else 0
            transaction_count = result.transaction_count

            if category_id not in category_data:
                category_data[category_id] = {
                    "name": category_name,
                    "type": result.type,
                    "yearly_data": {},
                    "changes": {},
                }

            # Calculate months with data for accurate monthly average
            months_with_data = AnalyticsService._get_months_with_data(session, category_id, year)
            monthly_avg = total_amount / months_with_data if months_with_data > 0 else 0

            category_data[category_id]["yearly_data"][str(year)] = {
                "total": total_amount,
                "monthly_avg": monthly_avg,
                "transactions": transaction_count,
                "months_with_data": months_with_data,
            }

            yearly_totals[year] += total_amount

        # Calculate year-over-year changes
        for category in category_data.values():
            sorted_years = sorted([int(y) for y in category["yearly_data"]])
            for i in range(1, len(sorted_years)):
                prev_year = sorted_years[i - 1]
                curr_year = sorted_years[i]

                prev_data = category["yearly_data"].get(str(prev_year), {})
                curr_data = category["yearly_data"].get(str(curr_year), {})

                # Calculate changes for both total and monthly average
                prev_total = prev_data.get("total", 0)
                curr_total = curr_data.get("total", 0)
                prev_monthly_avg = prev_data.get("monthly_avg", 0)
                curr_monthly_avg = curr_data.get("monthly_avg", 0)

                # Fixed percentage change calculation: (new/old - 1) * 100
                absolute_change_total = curr_total - prev_total
                percentage_change_total = ((curr_total / prev_total - 1) * 100) if prev_total != 0 else 0

                absolute_change_monthly = curr_monthly_avg - prev_monthly_avg
                percentage_change_monthly = (
                    ((curr_monthly_avg / prev_monthly_avg - 1) * 100) if prev_monthly_avg != 0 else 0
                )

                category["changes"][f"{prev_year}_to_{curr_year}"] = {
                    "absolute_total": absolute_change_total,
                    "percentage_total": percentage_change_total,
                    "absolute_monthly": absolute_change_monthly,
                    "percentage_monthly": percentage_change_monthly,
                }

        # Sort categories by most recent year's total
        most_recent_year = str(max(years))
        categories_list = sorted(
            category_data.values(),
            key=lambda c: abs(c["yearly_data"].get(most_recent_year, {}).get("total", 0)),
            reverse=True,
        )

        return {
            "categories": categories_list,
            "summary": {
                "years": sorted(years),
                "total_by_year": {str(year): total for year, total in yearly_totals.items()},
                "category_type_filter": category_type,
            },
        }

    @staticmethod
    def _get_months_with_data(session: Session, category_id: int, year: int) -> int:
        """Get the number of months with transaction data for a category in a specific year."""
        query = (
            session.query(func.count(func.distinct(func.strftime("%m", TransactionORM.date))))
            .filter(or_(TransactionORM.category_id == category_id, TransactionORM.predicted_category_id == category_id))
            .filter(func.strftime("%Y", TransactionORM.date) == str(year))
        )

        result = query.scalar()
        return result if result else 0

    @staticmethod
    def get_category_cumulative_data(
        session: Session, category_id: int, years: list[int] | None = None
    ) -> dict[str, Any]:
        """Get monthly cumulative data for a specific category across multiple years."""
        if not years:
            year_query = session.query(func.distinct(func.strftime("%Y", TransactionORM.date))).order_by(
                func.strftime("%Y", TransactionORM.date).desc()
            )
            available_years = [int(y[0]) for y in year_query.all()]
            years = available_years[:3] if len(available_years) >= 3 else available_years

        if not years:
            return {"years": [], "monthly_data": {}, "category_name": None}

        # Get category details
        category = session.query(CategoryORM).filter(CategoryORM.id == category_id).first()
        if not category:
            return {"years": [], "monthly_data": {}, "category_name": None}

        # Query monthly transaction data for the category
        query = (
            session.query(
                func.strftime("%Y", TransactionORM.date).label("year"),
                func.strftime("%m", TransactionORM.date).label("month"),
                func.sum(TransactionORM.amount).label("amount"),
            )
            .filter(or_(TransactionORM.category_id == category_id, TransactionORM.predicted_category_id == category_id))
            .filter(func.strftime("%Y", TransactionORM.date).in_([str(y) for y in years]))
            .group_by(func.strftime("%Y", TransactionORM.date), func.strftime("%m", TransactionORM.date))
            .order_by(func.strftime("%Y", TransactionORM.date), func.strftime("%m", TransactionORM.date))
        )

        results = query.all()

        # Organize data by year
        yearly_data = {}
        for year in years:
            yearly_data[str(year)] = {
                "monthly_totals": [0] * 12,  # Jan-Dec
                "cumulative": [0] * 12,
            }

        # Populate monthly data
        for result in results:
            year = result.year
            month = int(result.month) - 1  # Convert to 0-indexed
            amount = float(result.amount) if result.amount else 0

            if year in yearly_data:
                yearly_data[year]["monthly_totals"][month] = amount

        # Calculate cumulative sums
        for year_data in yearly_data.values():
            running_total = 0
            for i in range(12):
                running_total += year_data["monthly_totals"][i]
                year_data["cumulative"][i] = running_total

        return {
            "years": sorted(years),
            "monthly_data": yearly_data,
            "category_name": category.name,
            "category_type": category.type,
        }

    @staticmethod
    def get_available_years(session: Session) -> dict[str, Any]:
        """Get all years that have transaction data for the year selector."""
        # Query for distinct years from transactions
        years_query = (
            session.query(func.strftime("%Y", TransactionORM.date).label("year"))
            .distinct()
            .order_by(func.strftime("%Y", TransactionORM.date).desc())
        )

        years = [int(row.year) for row in years_query.all()]

        # Get current year for default selection
        current_year = date.today().year

        return {"years": years, "current_year": current_year}


class BudgetService:
    """Service for yearly budget operations."""

    @staticmethod
    def get_budget_for_category_year(session: Session, category_id: int, year: int) -> float:
        """Get budget for a specific category and year with fallback logic."""
        # First try to get year-specific budget
        budget_plan = (
            session.query(BudgetPlanORM)
            .filter(BudgetPlanORM.category_id == category_id, BudgetPlanORM.year == year)
            .first()
        )

        if budget_plan:
            return float(budget_plan.monthly_budget)

        # Fallback to category default budget
        category = session.query(CategoryORM).filter(CategoryORM.id == category_id).first()
        if category:
            return float(category.budget)

        return 0.0

    @staticmethod
    def get_budgets_for_year(session: Session, year: int) -> dict[str, Any]:
        """Get all budgets for a specific year."""
        # Get all active categories
        categories = session.query(CategoryORM).filter(CategoryORM.is_active).all()

        budgets = []
        for category in categories:
            # Try to get year-specific budget
            budget_plan = (
                session.query(BudgetPlanORM)
                .filter(BudgetPlanORM.category_id == category.id, BudgetPlanORM.year == year)
                .first()
            )

            if budget_plan:
                budget = float(budget_plan.monthly_budget)
                has_year_specific = True
            else:
                budget = float(category.budget)
                has_year_specific = False

            budgets.append(
                {
                    "category_id": category.id,
                    "category_name": category.name,
                    "category_type": category.type,
                    "monthly_budget": budget,
                    "has_year_specific": has_year_specific,
                    "fallback_budget": float(category.budget),
                }
            )

        return {"year": year, "budgets": budgets, "total_categories": len(categories)}

    @staticmethod
    def set_budget_for_category_year(session: Session, category_id: int, year: int, monthly_budget: float) -> bool:
        """Set or update budget for a specific category and year."""
        # Check if category exists and is active
        category = session.query(CategoryORM).filter(CategoryORM.id == category_id, CategoryORM.is_active).first()

        if not category:
            return False

        # Check if budget plan already exists
        budget_plan = (
            session.query(BudgetPlanORM)
            .filter(BudgetPlanORM.category_id == category_id, BudgetPlanORM.year == year)
            .first()
        )

        if budget_plan:
            # Update existing budget plan
            budget_plan.monthly_budget = monthly_budget
            budget_plan.updated_at = datetime.now()
        else:
            # Create new budget plan
            budget_plan = BudgetPlanORM(category_id=category_id, year=year, monthly_budget=monthly_budget)
            session.add(budget_plan)

        session.commit()
        return True

    @staticmethod
    def copy_budgets_from_year(session: Session, source_year: int, target_year: int) -> dict[str, Any]:
        """Copy all budgets from source year to target year."""
        # Get all budget plans from source year
        source_plans = session.query(BudgetPlanORM).filter(BudgetPlanORM.year == source_year).all()

        if not source_plans:
            # If no specific plans for source year, use category default budgets
            categories = session.query(CategoryORM).filter(CategoryORM.is_active, CategoryORM.budget > 0).all()

            copied_count = 0
            for category in categories:
                # Check if target year budget already exists
                existing = (
                    session.query(BudgetPlanORM)
                    .filter(BudgetPlanORM.category_id == category.id, BudgetPlanORM.year == target_year)
                    .first()
                )

                if not existing:
                    budget_plan = BudgetPlanORM(
                        category_id=category.id, year=target_year, monthly_budget=category.budget
                    )
                    session.add(budget_plan)
                    copied_count += 1

            session.commit()
            return {
                "source_year": source_year,
                "target_year": target_year,
                "copied_count": copied_count,
                "source": "category_defaults",
            }

        # Copy from specific year budget plans
        copied_count = 0
        for source_plan in source_plans:
            # Check if target year budget already exists
            existing = (
                session.query(BudgetPlanORM)
                .filter(BudgetPlanORM.category_id == source_plan.category_id, BudgetPlanORM.year == target_year)
                .first()
            )

            if not existing:
                budget_plan = BudgetPlanORM(
                    category_id=source_plan.category_id, year=target_year, monthly_budget=source_plan.monthly_budget
                )
                session.add(budget_plan)
                copied_count += 1

        session.commit()
        return {
            "source_year": source_year,
            "target_year": target_year,
            "copied_count": copied_count,
            "source": "budget_plans",
        }

    @staticmethod
    def delete_budget_for_category_year(session: Session, category_id: int, year: int) -> bool:
        """Delete budget plan for a specific category and year."""
        budget_plan = (
            session.query(BudgetPlanORM)
            .filter(BudgetPlanORM.category_id == category_id, BudgetPlanORM.year == year)
            .first()
        )

        if budget_plan:
            session.delete(budget_plan)
            session.commit()
            return True

        return False

    @staticmethod
    def get_years_with_budgets(session: Session) -> list[int]:
        """Get all years that have budget plans defined."""
        years = session.query(BudgetPlanORM.year).distinct().order_by(BudgetPlanORM.year.desc()).all()
        return [year[0] for year in years]

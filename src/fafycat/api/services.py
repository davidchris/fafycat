"""Service layer for database operations."""

import math
import statistics
from datetime import date, datetime
from typing import Any, cast

from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import Session, joinedload

from fafycat.api.models import CategoryCreate, CategoryResponse, CategoryUpdate, TransactionResponse, TransactionUpdate
from fafycat.core.audit_trail import ReviewActor, record_review_event
from fafycat.core.database import BudgetPlanORM, CategoryORM, TransactionORM
from fafycat.core.database import get_categories as db_get_categories
from fafycat.core.models import CategoryType, ReviewPriority
from fafycat.ml.merchant_mapper import refresh_rule_for_pattern
from fafycat.ml.prediction_pipeline import get_auto_approve_threshold


def _pattern_of(transaction: TransactionORM | None) -> str:
    """Merchant pattern of a transaction, or empty when it has none."""
    return str(transaction.merchant_pattern) if transaction is not None and transaction.merchant_pattern else ""


def _unreviewed_siblings(session: Session, pattern: str, source_id: str):
    """Query for the unreviewed transactions sharing ``pattern``, excluding the source."""
    return session.query(TransactionORM).filter(
        TransactionORM.merchant_pattern == pattern,
        TransactionORM.id != source_id,
        TransactionORM.is_reviewed == False,  # noqa: E712
    )


def _to_int(value: Any) -> int:
    """Cast an ORM column value to int."""
    return int(value)


def _to_int_or_none(value: Any) -> int | None:
    return None if value is None else int(value)


def _to_str(value: Any) -> str:
    """Cast an ORM column value to str."""
    return str(value)


def _to_float(value: Any) -> float:
    """Cast an ORM column value to float."""
    return float(value)


def _to_bool(value: Any) -> bool:
    """Cast an ORM column value to bool."""
    return bool(value)


def _to_date(value: Any) -> date:
    """Cast an ORM column value to date."""
    return date(value.year, value.month, value.day)


def _to_datetime(value: Any) -> datetime:
    """Cast an ORM column value to datetime."""
    return cast(datetime, value)


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
        start_date: date | None = None,
        end_date: date | None = None,
        review_priority: ReviewPriority | None = None,
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

        if start_date is not None:
            query = query.filter(TransactionORM.date >= start_date)
        if end_date is not None:
            query = query.filter(TransactionORM.date <= end_date)

        if review_priority is not None:
            query = query.filter(TransactionORM.review_priority == review_priority)

        # Apply pagination
        query = query.order_by(TransactionORM.date.desc())
        query = query.offset(skip).limit(limit)

        transactions = query.all()

        # Convert to response models
        return [
            TransactionResponse(
                id=_to_str(t.id),
                date=_to_date(t.date),
                description=(f"{t.name} - {t.purpose}".rstrip(" -") if t.purpose else _to_str(t.name)),
                amount=_to_float(t.amount),
                account="",  # Will be added when we migrate account info
                predicted_category=_to_str(t.predicted_category.name) if t.predicted_category else None,
                actual_category=_to_str(t.category.name) if t.category else None,
                confidence=_to_float(t.confidence_score) if t.confidence_score is not None else None,
                is_reviewed=_to_bool(t.is_reviewed),
                review_priority=_to_str(t.review_priority) if t.review_priority else None,
                created_at=_to_datetime(t.imported_at),
                updated_at=_to_datetime(t.imported_at),  # Will update when we add updated_at to TransactionORM
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
        start_date: date | None = None,
        end_date: date | None = None,
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
            query = query.filter(TransactionORM.review_priority == review_priority)

        if category:
            if category == "uncategorized":
                # Filter for transactions with no category (neither actual nor predicted)
                query = query.filter(
                    and_(TransactionORM.category_id.is_(None), TransactionORM.predicted_category_id.is_(None))
                )
            else:
                # Filter by effective/final category: actual_category takes precedence over predicted_category
                # This ensures reviewed transactions use their assigned category, unreviewed use predicted category
                query = query.filter(
                    or_(
                        # Case 1: Has actual category and it matches (user-assigned, takes precedence)
                        and_(
                            TransactionORM.category_id.is_not(None),
                            TransactionORM.category.has(CategoryORM.name == category),
                        ),
                        # Case 2: No actual category, but predicted category matches (unreviewed)
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

        # Apply date range filters
        if start_date is not None:
            query = query.filter(TransactionORM.date >= start_date)
        if end_date is not None:
            query = query.filter(TransactionORM.date <= end_date)

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
                id=_to_str(t.id),
                date=_to_date(t.date),
                description=(f"{t.name} - {t.purpose}".rstrip(" -") if t.purpose else _to_str(t.name)),
                amount=_to_float(t.amount),
                account="",  # Will be added when we migrate account info
                predicted_category=_to_str(t.predicted_category.name) if t.predicted_category else None,
                actual_category=_to_str(t.category.name) if t.category else None,
                confidence=_to_float(t.confidence_score) if t.confidence_score is not None else None,
                is_reviewed=_to_bool(t.is_reviewed),
                review_priority=_to_str(t.review_priority) if t.review_priority else None,
                created_at=_to_datetime(t.imported_at),
                updated_at=_to_datetime(t.imported_at),  # Will update when we add updated_at to TransactionORM
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
        record_review_event(
            session,
            transaction,
            actor=ReviewActor.USER_REVIEW,
            from_category_id=_to_int_or_none(transaction.category_id),
            to_category_id=_to_int(category.id),
        )
        transaction.category_id = category.id
        transaction.is_reviewed = update.is_reviewed
        session.commit()

        if update.is_reviewed:
            refresh_rule_for_pattern(session, _pattern_of(transaction))

        # Return updated transaction
        return TransactionResponse(
            id=_to_str(transaction.id),
            date=_to_date(transaction.date),
            description=(
                f"{transaction.name} - {transaction.purpose}".rstrip(" -")
                if transaction.purpose
                else _to_str(transaction.name)
            ),
            amount=_to_float(transaction.amount),
            account="",
            predicted_category=_to_str(transaction.predicted_category.name) if transaction.predicted_category else None,
            actual_category=_to_str(category.name),
            confidence=_to_float(transaction.confidence_score) if transaction.confidence_score is not None else None,
            is_reviewed=_to_bool(transaction.is_reviewed),
            review_priority=_to_str(transaction.review_priority) if transaction.review_priority else None,
            created_at=_to_datetime(transaction.imported_at),
            updated_at=_to_datetime(transaction.imported_at),
        )

    @staticmethod
    def count_unreviewed_siblings(session: Session, transaction_id: str) -> tuple[str, int]:
        """Count the unreviewed transactions that share a transaction's merchant pattern.

        Args:
            session: Open database session.
            transaction_id: The transaction whose siblings are counted. It is
                itself excluded from the count.

        Returns:
            A ``(merchant_pattern, count)`` pair. The pattern is empty and the
            count zero when the transaction is unknown or has no pattern.
        """
        transaction = session.query(TransactionORM).filter(TransactionORM.id == transaction_id).first()
        pattern = _pattern_of(transaction)
        if not pattern:
            return "", 0

        return pattern, _unreviewed_siblings(session, pattern, transaction_id).count()

    @staticmethod
    def propagate_category(session: Session, source_id: str, category_name: str) -> dict:
        """Apply a category to every unreviewed transaction sharing the source's merchant pattern.

        Each affected transaction is marked reviewed and gets its own Review
        Event with the ``propagation`` actor, so the Audit Trail names the
        correction it came from. Already reviewed transactions are left alone.
        The pattern's Merchant Rule is recomputed afterwards.

        Args:
            session: Open database session. Committed by this function.
            source_id: The transaction the user corrected.
            category_name: Name of the category to apply.

        Returns:
            A dict with the number of transactions ``applied``, the
            ``pattern``, and the ``category`` name.
        """
        source = session.query(TransactionORM).filter(TransactionORM.id == source_id).first()
        pattern = _pattern_of(source)
        category = session.query(CategoryORM).filter(CategoryORM.name == category_name).first()
        if not pattern or category is None:
            return {"applied": 0, "pattern": pattern, "category": category_name}

        siblings = _unreviewed_siblings(session, pattern, source_id).all()

        for txn in siblings:
            record_review_event(
                session,
                txn,
                actor=ReviewActor.PROPAGATION,
                from_category_id=_to_int_or_none(txn.category_id),
                to_category_id=_to_int(category.id),
                note=f"propagated from {source_id}",
            )
            txn.category_id = category.id
            txn.is_reviewed = True

        session.commit()
        refresh_rule_for_pattern(session, pattern)
        return {"applied": len(siblings), "pattern": pattern, "category": _to_str(category.name)}

    @staticmethod
    def bulk_approve(
        session: Session,
        review_priority: ReviewPriority | None = None,
        min_confidence: float | None = None,
    ) -> dict:
        """Bulk approve unreviewed transactions by trusting their ML predictions.

        Filters by ``review_priority`` and/or ``min_confidence``. With neither
        given, the Auto-approve Threshold is used as the confidence floor so a
        bare call never approves low-confidence guesses.
        """
        if review_priority is None and min_confidence is None:
            min_confidence = get_auto_approve_threshold(session)

        query = session.query(TransactionORM).filter(
            TransactionORM.is_reviewed == False,  # noqa: E712
            TransactionORM.predicted_category_id.is_not(None),
        )
        if review_priority is not None:
            query = query.filter(TransactionORM.review_priority == review_priority)
        if min_confidence is not None:
            query = query.filter(TransactionORM.confidence_score >= min_confidence)

        approved_ids: list[str] = []
        for txn in query.all():
            record_review_event(
                session,
                txn,
                actor=ReviewActor.BULK_APPROVE,
                from_category_id=_to_int_or_none(txn.category_id),
                to_category_id=_to_int(txn.predicted_category_id),
            )
            txn.category_id = txn.predicted_category_id
            txn.is_reviewed = True
            approved_ids.append(_to_str(txn.id))

        session.commit()
        return {"approved": len(approved_ids), "transaction_ids": approved_ids}


class CategoryService:
    """Service for category operations."""

    @staticmethod
    def get_categories(session: Session, include_inactive: bool = False) -> list[CategoryResponse]:
        """Get all categories."""
        categories = db_get_categories(session, active_only=not include_inactive)

        return [
            CategoryResponse(
                id=_to_int(c.id),
                name=_to_str(c.name),
                type=_to_str(c.type),
                is_active=_to_bool(c.is_active),
                budget=_to_float(c.budget) if c.budget is not None else None,
                created_at=_to_datetime(c.created_at),
                updated_at=_to_datetime(c.updated_at),
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
            id=_to_int(db_category.id),
            name=_to_str(db_category.name),
            type=_to_str(db_category.type),
            is_active=_to_bool(db_category.is_active),
            budget=_to_float(db_category.budget) if db_category.budget is not None else None,
            created_at=_to_datetime(db_category.created_at),
            updated_at=_to_datetime(db_category.updated_at),
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
            id=_to_int(category.id),
            name=_to_str(category.name),
            type=_to_str(category.type),
            is_active=_to_bool(category.is_active),
            budget=_to_float(category.budget) if category.budget is not None else None,
            created_at=_to_datetime(category.created_at),
            updated_at=_to_datetime(category.updated_at),
        )


class AnalyticsService:
    """Service for analytics operations."""

    @staticmethod
    def _unreviewed_condition():
        """Return the SQL condition matching unreviewed transactions.

        A transaction counts as unreviewed unless ``is_reviewed`` is explicitly true, so legacy
        rows with a NULL flag are treated as unreviewed too.
        """
        return TransactionORM.is_reviewed.is_not(True)

    @staticmethod
    def _apply_review_filter(query, include_unreviewed: bool):
        """Restrict a transaction query to reviewed rows when unreviewed rows are excluded.

        Args:
            query: SQLAlchemy query selecting from ``TransactionORM``.
            include_unreviewed: When False, keep only rows with ``is_reviewed = 1``.

        Returns:
            The query, filtered when ``include_unreviewed`` is False.
        """
        if include_unreviewed:
            return query
        return query.filter(TransactionORM.is_reviewed.is_(True))

    @staticmethod
    def _unreviewed_amount_sum():
        """Return the aggregate expression summing amounts of unreviewed rows (signed)."""
        return func.coalesce(
            func.sum(case((AnalyticsService._unreviewed_condition(), TransactionORM.amount), else_=0.0)), 0.0
        )

    @staticmethod
    def _unreviewed_row_count():
        """Return the aggregate expression counting unreviewed rows."""
        return func.coalesce(func.sum(case((AnalyticsService._unreviewed_condition(), 1), else_=0)), 0)

    @staticmethod
    def _get_unreviewed_summary(
        session: Session,
        start_date: date,
        end_date: date,
        include_unreviewed: bool = True,
    ) -> dict[str, Any]:
        """Summarize the unreviewed transactions of a date range.

        The summary always describes the range itself, so callers can warn about unreviewed
        transactions even when the aggregation excluded them.

        Args:
            session: Database session.
            start_date: First day of the range (inclusive).
            end_date: Last day of the range (inclusive).
            include_unreviewed: Whether the surrounding aggregation counted these transactions.

        Returns:
            Dict with ``count``, ``amount`` (total absolute value at stake), ``included`` and
            ``date_range``.
        """
        row = (
            session.query(
                func.count(TransactionORM.id).label("count"),
                func.coalesce(func.sum(func.abs(TransactionORM.amount)), 0.0).label("amount"),
            )
            .filter(TransactionORM.date.between(start_date, end_date))
            .filter(AnalyticsService._unreviewed_condition())
            .filter(or_(TransactionORM.category_id.is_not(None), TransactionORM.predicted_category_id.is_not(None)))
            .one()
        )

        return {
            "count": int(row.count or 0),
            "amount": float(row.amount or 0.0),
            "included": include_unreviewed,
            "date_range": {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        }

    @staticmethod
    def get_unreviewed_count(session: Session, start_date: date, end_date: date) -> int:
        """Count unreviewed transactions in a date range.

        Args:
            session: Database session.
            start_date: First day of the range (inclusive).
            end_date: Last day of the range (inclusive).

        Returns:
            Number of unreviewed transactions in the range.
        """
        count = (
            session.query(func.count(TransactionORM.id))
            .filter(TransactionORM.date.between(start_date, end_date))
            .filter(AnalyticsService._unreviewed_condition())
            .scalar()
        )
        return int(count or 0)

    @staticmethod
    def get_budget_variance(
        session: Session,
        start_date: date | None = None,
        end_date: date | None = None,
        include_unreviewed: bool = True,
    ) -> dict[str, Any]:
        """Get budget vs actual spending variance by category with year-specific budgets.

        Args:
            session: Database session.
            start_date: First day of the range; defaults to the start of the current month.
            end_date: Last day of the range; defaults to today.
            include_unreviewed: When False, only reviewed transactions count towards actuals.

        Returns:
            Variance payload with per-category ``unreviewed_amount``/``unreviewed_count`` and a
            top-level ``unreviewed`` summary.
        """
        start_date, end_date = AnalyticsService._get_default_dates(start_date, end_date)

        # Get transaction data grouped by category and year
        category_data = AnalyticsService._get_transaction_category_data(
            session, start_date, end_date, include_unreviewed
        )

        # Include categories with budgets but no transactions
        AnalyticsService._add_budgeted_categories_without_transactions(session, category_data, start_date, end_date)

        # Build final variance data
        result = AnalyticsService._build_variance_result(category_data, start_date, end_date)
        result["unreviewed"] = AnalyticsService._get_unreviewed_summary(
            session, start_date, end_date, include_unreviewed
        )
        return result

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
    def _get_transaction_category_data(
        session: Session, start_date: date, end_date: date, include_unreviewed: bool = True
    ) -> dict[int, dict]:
        """Get transaction data grouped by category and year.

        Args:
            session: Database session.
            start_date: First day of the range (inclusive).
            end_date: Last day of the range (inclusive).
            include_unreviewed: When False, only reviewed transactions are aggregated.

        Returns:
            Mapping of category id to budget/actual data, including unreviewed shares.
        """
        # Group transactions by year and category to handle cross-year periods
        query = (
            session.query(
                CategoryORM.id,
                CategoryORM.name,
                CategoryORM.type,
                func.strftime("%Y", TransactionORM.date).label("year"),
                func.coalesce(func.sum(TransactionORM.amount), 0).label("actual_amount"),
                AnalyticsService._unreviewed_amount_sum().label("unreviewed_amount"),
                AnalyticsService._unreviewed_row_count().label("unreviewed_count"),
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
        query = AnalyticsService._apply_review_filter(query, include_unreviewed)

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
                    "unreviewed_amount": 0.0,
                    "unreviewed_count": 0,
                }

            # Get year-specific budget and calculate period budget
            year_budget = BudgetService.get_budget_for_category_year(session, category_id, year)
            year_start = max(start_date, date(year, 1, 1))
            year_end = min(end_date, date(year, 12, 31))
            months_in_year = (year_end.year - year_start.year) * 12 + year_end.month - year_start.month + 1
            period_budget = year_budget * months_in_year

            unreviewed_amount = float(result.unreviewed_amount or 0.0)
            unreviewed_count = int(result.unreviewed_count or 0)

            category_data[category_id]["yearly_data"][year] = {
                "budget": period_budget,
                "actual": actual_amount,
                "months": months_in_year,
                "unreviewed_amount": unreviewed_amount,
                "unreviewed_count": unreviewed_count,
            }

            category_data[category_id]["total_actual"] += actual_amount
            category_data[category_id]["total_budget"] += period_budget
            category_data[category_id]["unreviewed_amount"] += unreviewed_amount
            category_data[category_id]["unreviewed_count"] += unreviewed_count

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
            cat_id = _to_int(category.id)
            if cat_id not in category_data:
                total_budget = AnalyticsService._calculate_total_budget_for_period(
                    session, cat_id, start_date, end_date
                )

                if total_budget > 0:
                    category_data[cat_id] = {
                        "category_name": _to_str(category.name),
                        "yearly_data": {},
                        "total_actual": 0,
                        "total_budget": total_budget,
                        "unreviewed_amount": 0.0,
                        "unreviewed_count": 0,
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
            unreviewed_amount = data.get("unreviewed_amount", 0.0)

            # Calculate variance based on spending vs income categories
            if budget > 0 and actual <= 0:  # Spending category
                displayed_actual = abs(actual)
                # Mirror the sign convention of the displayed actual so both read the same way.
                unreviewed_amount = abs(unreviewed_amount)
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
                    "unreviewed_amount": unreviewed_amount,
                    "unreviewed_count": data.get("unreviewed_count", 0),
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
        session: Session,
        year: int | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        include_unreviewed: bool = True,
    ) -> dict[str, Any]:
        """Get monthly income/spending/saving breakdown.

        Args:
            session: Database session.
            year: Calendar year to report; ignored when ``start_date`` is given.
            start_date: First day of an explicit range.
            end_date: Last day of an explicit range.
            include_unreviewed: When False, only reviewed transactions are aggregated.

        Returns:
            Monthly payload with per-month ``unreviewed_amount``/``unreviewed_count`` and a
            top-level ``unreviewed`` summary.
        """
        start_date, end_date, year = AnalyticsService._get_monthly_summary_dates(year, start_date, end_date)

        # Query for monthly aggregations by category type
        results = AnalyticsService._query_monthly_transactions(session, start_date, end_date, include_unreviewed)

        # Initialize and populate monthly data
        monthly_data = AnalyticsService._initialize_monthly_data(start_date, end_date)
        AnalyticsService._populate_monthly_data(monthly_data, results)
        AnalyticsService._calculate_profit_loss_and_cumulative(monthly_data)

        result = AnalyticsService._build_monthly_summary_result(monthly_data, year)
        result["unreviewed"] = AnalyticsService._get_unreviewed_summary(
            session, start_date, end_date, include_unreviewed
        )
        return result

    @staticmethod
    def _get_monthly_summary_dates(
        year: int | None, start_date: date | None, end_date: date | None
    ) -> tuple[date, date, int | None]:
        """Get the start and end dates for monthly summary."""
        if not year and not start_date:
            year = date.today().year

        if year and not start_date:
            resolved_start = date(year, 1, 1)
            resolved_end = date(year, 12, 31)
        else:
            resolved_start = start_date if start_date else date.today().replace(day=1)
            resolved_end = end_date if end_date else date.today()

        return resolved_start, resolved_end, year

    @staticmethod
    def _query_monthly_transactions(
        session: Session, start_date: date, end_date: date, include_unreviewed: bool = True
    ):
        """Query monthly transaction aggregations by category type.

        Args:
            session: Database session.
            start_date: First day of the range (inclusive).
            end_date: Last day of the range (inclusive).
            include_unreviewed: When False, only reviewed transactions are aggregated.

        Returns:
            Rows of ``(month, type, total_amount, unreviewed_amount, unreviewed_count)``.
        """
        query = (
            session.query(
                func.strftime("%Y-%m", TransactionORM.date).label("month"),
                CategoryORM.type,
                func.sum(TransactionORM.amount).label("total_amount"),
                AnalyticsService._unreviewed_amount_sum().label("unreviewed_amount"),
                AnalyticsService._unreviewed_row_count().label("unreviewed_count"),
            )
            .join(
                CategoryORM,
                CategoryORM.id == func.coalesce(TransactionORM.category_id, TransactionORM.predicted_category_id),
            )
            .filter(TransactionORM.date.between(start_date, end_date))
            .filter(or_(TransactionORM.category_id.is_not(None), TransactionORM.predicted_category_id.is_not(None)))
            .group_by(func.strftime("%Y-%m", TransactionORM.date), CategoryORM.type)
            .order_by(func.strftime("%Y-%m", TransactionORM.date))
        )
        query = AnalyticsService._apply_review_filter(query, include_unreviewed)
        return query.all()

    @staticmethod
    def _initialize_monthly_data(start_date: date, end_date: date) -> dict[str, dict]:
        """Initialize monthly data structure for the specified date range."""
        monthly_data = {}
        current_date = start_date.replace(day=1)
        end_month = end_date.replace(day=1)

        while current_date <= end_month:
            # Year-qualified key so multi-year ranges don't collapse same-named months
            month_str = f"{current_date.year}-{current_date.month:02d}"
            monthly_data[month_str] = {
                "month": month_str,
                "income": 0.0,
                "spending": 0.0,
                "saving": 0.0,
                "profit_loss": 0.0,
                "unreviewed_amount": 0.0,
                "unreviewed_count": 0,
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

                monthly_data[month]["unreviewed_amount"] += float(getattr(result, "unreviewed_amount", 0.0) or 0.0)
                monthly_data[month]["unreviewed_count"] += int(getattr(result, "unreviewed_count", 0) or 0)

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
        session: Session,
        start_date: date | None = None,
        end_date: date | None = None,
        category_type: str | None = None,
        include_unreviewed: bool = True,
    ) -> dict[str, Any]:
        """Get category-wise spending analysis.

        Args:
            session: Database session.
            start_date: First day of the range; defaults to the start of the current month.
            end_date: Last day of the range; defaults to today.
            category_type: Optional category type filter (spending/income/saving).
            include_unreviewed: When False, only reviewed transactions are aggregated.

        Returns:
            Breakdown payload with per-category ``unreviewed_amount``/``unreviewed_count`` and a
            top-level ``unreviewed`` summary.
        """
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
                AnalyticsService._unreviewed_amount_sum().label("unreviewed_amount"),
                AnalyticsService._unreviewed_row_count().label("unreviewed_count"),
            )
            .join(
                CategoryORM,
                CategoryORM.id == func.coalesce(TransactionORM.category_id, TransactionORM.predicted_category_id),
            )
            .filter(TransactionORM.date.between(start_date, end_date))
            .filter(CategoryORM.is_active)
            .filter(or_(TransactionORM.category_id.is_not(None), TransactionORM.predicted_category_id.is_not(None)))
        )
        query = AnalyticsService._apply_review_filter(query, include_unreviewed)

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
                    "unreviewed_amount": float(result.unreviewed_amount or 0.0),
                    "unreviewed_count": int(result.unreviewed_count or 0),
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
            "unreviewed": AnalyticsService._get_unreviewed_summary(session, start_date, end_date, include_unreviewed),
        }

    @staticmethod
    def get_savings_tracking(
        session: Session,
        year: int | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        include_unreviewed: bool = True,
    ) -> dict[str, Any]:
        """Get savings analysis with monthly and cumulative tracking.

        Args:
            session: Database session.
            year: Calendar year to report; ignored when ``start_date`` is given.
            start_date: First day of an explicit range.
            end_date: Last day of an explicit range.
            include_unreviewed: When False, only reviewed transactions are aggregated.

        Returns:
            Savings payload with per-month ``unreviewed_amount``/``unreviewed_count`` and a
            top-level ``unreviewed`` summary.
        """
        if not year and not start_date:
            year = date.today().year

        # Resolve date range: year-based or explicit start/end
        if year and not start_date:
            resolved_start = date(year, 1, 1)
            resolved_end = date(year, 12, 31)
        else:
            resolved_start = start_date if start_date else date.today().replace(day=1)
            resolved_end = end_date if end_date else date.today()

        # Query for monthly savings data
        # Use COALESCE to get effective category (actual takes precedence over predicted)
        query = (
            session.query(
                func.strftime("%Y-%m", TransactionORM.date).label("month"),
                func.sum(TransactionORM.amount).label("savings_amount"),
                AnalyticsService._unreviewed_amount_sum().label("unreviewed_amount"),
                AnalyticsService._unreviewed_row_count().label("unreviewed_count"),
            )
            .join(
                CategoryORM,
                CategoryORM.id == func.coalesce(TransactionORM.category_id, TransactionORM.predicted_category_id),
            )
            .filter(CategoryORM.type == CategoryType.SAVING)
            .filter(TransactionORM.date.between(resolved_start, resolved_end))
            .filter(or_(TransactionORM.category_id.is_not(None), TransactionORM.predicted_category_id.is_not(None)))
            .group_by(func.strftime("%Y-%m", TransactionORM.date))
            .order_by(func.strftime("%Y-%m", TransactionORM.date))
        )
        query = AnalyticsService._apply_review_filter(query, include_unreviewed)

        results = query.all()

        # Initialize monthly savings data for the specified date range only
        monthly_savings = {}

        # Generate months only within the specified date range
        current_date = resolved_start.replace(day=1)  # Start from first day of start month
        end_month = resolved_end.replace(day=1)

        while current_date <= end_month:
            # Year-qualified key so multi-year ranges don't collapse same-named months
            month_str = f"{current_date.year}-{current_date.month:02d}"
            monthly_savings[month_str] = {
                "month": month_str,
                "amount": 0.0,
                "unreviewed_amount": 0.0,
                "unreviewed_count": 0,
            }
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
            monthly_savings[month]["unreviewed_amount"] = float(result.unreviewed_amount or 0.0)
            monthly_savings[month]["unreviewed_count"] = int(result.unreviewed_count or 0)

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
            "median_monthly": statistics.median(amounts) if amounts else 0,
            "months_with_savings": len(amounts),
        }

        return {
            "year": year,
            "monthly_savings": list(monthly_savings.values()),
            "statistics": stats,
            "unreviewed": AnalyticsService._get_unreviewed_summary(
                session, resolved_start, resolved_end, include_unreviewed
            ),
        }

    @staticmethod
    def get_top_transactions_by_month(
        session: Session,
        year: int | None = None,
        month: int | None = None,
        limit: int = 5,
        include_unreviewed: bool = True,
    ) -> dict[str, Any]:
        """Get top spending transactions by month.

        Args:
            session: Database session.
            year: Calendar year; defaults to the current year.
            month: Calendar month (1-12); defaults to the current month.
            limit: Maximum number of transactions to return.
            include_unreviewed: When False, only reviewed transactions are considered.

        Returns:
            Payload with ``top_transactions`` (each carrying ``is_reviewed``) and a top-level
            ``unreviewed`` summary for the month.
        """
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
        )
        query = AnalyticsService._apply_review_filter(query, include_unreviewed)
        query = query.order_by(TransactionORM.amount.asc()).limit(limit)  # Most negative first (largest spending)

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
                    "amount": abs(_to_float(transaction.amount)),  # Show as positive for display
                    "category": category.name if category else "Unknown",
                    "merchant": transaction.name,
                    "is_reviewed": _to_bool(transaction.is_reviewed),
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
        total_query = AnalyticsService._apply_review_filter(total_query, include_unreviewed)

        total_spending = float(total_query.scalar() or 0)

        # Calculate percentage for each transaction
        for transaction in top_transactions:
            transaction["percentage_of_total"] = (
                (transaction["amount"] / abs(total_spending) * 100) if total_spending != 0 else 0
            )

        month_start = date(year, month, 1)
        month_end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        month_end = date.fromordinal(month_end.toordinal() - 1)

        return {
            "year": year,
            "month": month,
            "month_name": month_start.strftime("%B"),
            "top_transactions": top_transactions,
            "total_spending": abs(total_spending),
            "transactions_count": len(top_transactions),
            "unreviewed": AnalyticsService._get_unreviewed_summary(session, month_start, month_end, include_unreviewed),
        }

    @staticmethod
    def _get_available_years(session: Session, max_years: int = 3) -> list[int]:
        """Get available years with transaction data, most recent first."""
        year_query = session.query(func.distinct(func.strftime("%Y", TransactionORM.date))).order_by(
            func.strftime("%Y", TransactionORM.date).desc()
        )
        available_years = [int(y[0]) for y in year_query.all()]
        return available_years[:max_years] if len(available_years) >= max_years else available_years

    @staticmethod
    def _get_current_year_end_date(session: Session, current_year: int) -> date | None:
        """Get the max transaction date for the current year."""
        max_date_query = session.query(func.max(TransactionORM.date)).filter(
            func.strftime("%Y", TransactionORM.date) == str(current_year)
        )
        return max_date_query.scalar()

    @staticmethod
    def _calculate_yoy_changes(category: dict[str, Any]) -> None:
        """Calculate year-over-year changes for a category (mutates category dict)."""
        sorted_years = sorted([int(y) for y in category["yearly_data"]])
        for i in range(1, len(sorted_years)):
            prev_year = sorted_years[i - 1]
            curr_year = sorted_years[i]

            prev_data = category["yearly_data"].get(str(prev_year), {})
            curr_data = category["yearly_data"].get(str(curr_year), {})

            prev_total = prev_data.get("total", 0)
            curr_total = curr_data.get("total", 0)
            prev_monthly_avg = prev_data.get("monthly_avg", 0)
            curr_monthly_avg = curr_data.get("monthly_avg", 0)

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

    @staticmethod
    def get_year_over_year_comparison(
        session: Session,
        category_type: str | None = None,
        years: list[int] | None = None,
        include_unreviewed: bool = True,
    ) -> dict[str, Any]:
        """Get year-over-year comparison of categories with totals and monthly averages.

        Args:
            session: Database session.
            category_type: Optional category type filter (spending/income/saving).
            years: Years to compare; defaults to the three most recent years with data.
            include_unreviewed: When False, only reviewed transactions are aggregated.

        Returns:
            Comparison payload where each year entry carries ``unreviewed_amount``/
            ``unreviewed_count``, plus a top-level ``unreviewed`` summary spanning the years.
        """
        if not years:
            years = AnalyticsService._get_available_years(session)

        if not years:
            return {
                "categories": [],
                "summary": {"years": [], "total_by_year": {}},
                "unreviewed": {
                    "count": 0,
                    "amount": 0.0,
                    "included": include_unreviewed,
                    "date_range": {"start_date": None, "end_date": None},
                },
            }

        current_year = date.today().year
        latest_transaction_date = (
            AnalyticsService._get_current_year_end_date(session, current_year) if current_year in years else None
        )
        current_year_is_partial = bool(
            latest_transaction_date and (latest_transaction_date.month != 12 or latest_transaction_date.day != 31)
        )
        comparison_basis = "full_year"

        # Build base query
        query = (
            session.query(
                CategoryORM.id,
                CategoryORM.name,
                CategoryORM.type,
                func.strftime("%Y", TransactionORM.date).label("year"),
                func.count(TransactionORM.id).label("transaction_count"),
                func.sum(TransactionORM.amount).label("total_amount"),
                AnalyticsService._unreviewed_amount_sum().label("unreviewed_amount"),
                AnalyticsService._unreviewed_row_count().label("unreviewed_count"),
            )
            .join(
                CategoryORM,
                CategoryORM.id == func.coalesce(TransactionORM.category_id, TransactionORM.predicted_category_id),
            )
            .filter(CategoryORM.is_active)
            .filter(or_(TransactionORM.category_id.is_not(None), TransactionORM.predicted_category_id.is_not(None)))
            .filter(func.strftime("%Y", TransactionORM.date).in_([str(y) for y in years]))
        )
        query = AnalyticsService._apply_review_filter(query, include_unreviewed)

        if latest_transaction_date:
            comparison_basis = "aligned_to_current_year_latest_transaction"
            date_conditions = [
                and_(
                    func.strftime("%Y", TransactionORM.date) == str(year),
                    TransactionORM.date <= date(year, latest_transaction_date.month, latest_transaction_date.day),
                )
                for year in years
            ]
            query = query.filter(or_(*date_conditions))

        if category_type:
            query = query.filter(CategoryORM.type == category_type)

        query = query.group_by(
            CategoryORM.id, CategoryORM.name, CategoryORM.type, func.strftime("%Y", TransactionORM.date)
        )
        results = query.all()

        # Organize data by category
        category_data: dict[int, dict[str, Any]] = {}
        yearly_totals = {year: 0.0 for year in years}

        for result in results:
            category_id = result.id
            year = int(result.year)
            total_amount = float(result.total_amount) if result.total_amount else 0

            if category_id not in category_data:
                category_data[category_id] = {
                    "name": result.name,
                    "type": result.type,
                    "yearly_data": {},
                    "changes": {},
                    "unreviewed_amount": 0.0,
                    "unreviewed_count": 0,
                }

            category_data[category_id]["unreviewed_amount"] += float(result.unreviewed_amount or 0.0)
            category_data[category_id]["unreviewed_count"] += int(result.unreviewed_count or 0)

            # Calculate months with data for accurate monthly average
            query_start_date = date(year, 1, 1) if latest_transaction_date else None
            query_end_date = (
                date(year, latest_transaction_date.month, latest_transaction_date.day)
                if latest_transaction_date
                else None
            )
            months_with_data = AnalyticsService._get_months_with_data(
                session,
                category_id,
                year,
                start_date=query_start_date,
                end_date=query_end_date,
                include_unreviewed=include_unreviewed,
            )

            category_data[category_id]["yearly_data"][str(year)] = {
                "total": total_amount,
                "monthly_avg": total_amount / months_with_data if months_with_data > 0 else 0,
                "transactions": result.transaction_count,
                "months_with_data": months_with_data,
                "unreviewed_amount": float(result.unreviewed_amount or 0.0),
                "unreviewed_count": int(result.unreviewed_count or 0),
            }
            yearly_totals[year] += total_amount

        # Calculate year-over-year changes
        for category in category_data.values():
            AnalyticsService._calculate_yoy_changes(category)

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
                "latest_transaction_date": latest_transaction_date.isoformat() if latest_transaction_date else None,
                "current_year_is_partial": current_year_is_partial,
                "comparison_basis": comparison_basis,
                "comparison_end_date": latest_transaction_date.isoformat() if latest_transaction_date else None,
                "aligned_to_year": current_year if latest_transaction_date else None,
            },
            "unreviewed": AnalyticsService._get_unreviewed_summary_for_years(
                session, years, latest_transaction_date, include_unreviewed
            ),
        }

    @staticmethod
    def _get_unreviewed_summary_for_years(
        session: Session,
        years: list[int],
        cutoff: date | None,
        include_unreviewed: bool,
    ) -> dict[str, Any]:
        """Unreviewed summary over the same per-year windows the comparison used.

        When the comparison is aligned to ``cutoff`` (the current year's latest
        transaction day), every year is counted from 1 January to that day;
        otherwise whole years are counted. ``date_range`` lists exactly those
        windows, one per year, since they are not one contiguous span.
        """
        total_count, total_amount = 0, 0.0
        windows: list[dict[str, str]] = []
        for year in sorted(years):
            start = date(year, 1, 1)
            end = date(year, cutoff.month, cutoff.day) if cutoff else date(year, 12, 31)
            part = AnalyticsService._get_unreviewed_summary(session, start, end, include_unreviewed)
            total_count += part["count"]
            total_amount += part["amount"]
            windows.append({"start_date": start.isoformat(), "end_date": end.isoformat()})
        return {
            "count": total_count,
            "amount": round(total_amount, 2),
            "included": include_unreviewed,
            "date_range": {"windows": windows},
        }

    @staticmethod
    def _get_months_with_data(
        session: Session,
        category_id: int,
        year: int,
        start_date: date | None = None,
        end_date: date | None = None,
        include_unreviewed: bool = True,
    ) -> int:
        """Get the number of months with transaction data for a category in a specific year.

        Args:
            session: Database session
            category_id: The category ID to count months for
            year: The year to filter by
            start_date: Optional start date to limit the count (used for fair comparisons)
            end_date: Optional end date to limit the count (used for fair comparisons)
            include_unreviewed: When False, months with only unreviewed activity do not count,
                matching the totals they divide.

        Returns:
            Number of distinct months with transaction data in the specified year and date range
        """
        query = (
            session.query(func.count(func.distinct(func.strftime("%m", TransactionORM.date))))
            .filter(
                or_(
                    TransactionORM.category_id == category_id,
                    and_(TransactionORM.category_id.is_(None), TransactionORM.predicted_category_id == category_id),
                )
            )
            .filter(func.strftime("%Y", TransactionORM.date) == str(year))
        )
        query = AnalyticsService._apply_review_filter(query, include_unreviewed)

        # Apply date range filters if provided (to match parent query filtering)
        if start_date:
            query = query.filter(TransactionORM.date >= start_date)
        if end_date:
            query = query.filter(TransactionORM.date <= end_date)

        result = query.scalar()
        return result if result else 0

    @staticmethod
    def get_category_cumulative_data(
        session: Session, category_id: int, years: list[int] | None = None, include_unreviewed: bool = True
    ) -> dict[str, Any]:
        """Get monthly cumulative data for a specific category across multiple years.

        Args:
            session: Database session.
            category_id: Category to chart.
            years: Years to include; defaults to the three most recent years with data.
            include_unreviewed: When False, only reviewed transactions are aggregated.

        Returns:
            Cumulative payload plus a top-level ``unreviewed`` summary spanning the years.
        """
        if not years:
            years = AnalyticsService._get_available_years(session)

        if not years:
            return {"years": [], "monthly_data": {}, "category_name": None}

        # Get category details
        category = session.query(CategoryORM).filter(CategoryORM.id == category_id).first()
        if not category:
            return {"years": [], "monthly_data": {}, "category_name": None}

        # Query monthly transaction data for the category
        # Use effective category: actual_category takes precedence over predicted_category
        query = (
            session.query(
                func.strftime("%Y", TransactionORM.date).label("year"),
                func.strftime("%m", TransactionORM.date).label("month"),
                func.sum(TransactionORM.amount).label("amount"),
            )
            .filter(func.coalesce(TransactionORM.category_id, TransactionORM.predicted_category_id) == category_id)
            .filter(func.strftime("%Y", TransactionORM.date).in_([str(y) for y in years]))
            .group_by(func.strftime("%Y", TransactionORM.date), func.strftime("%m", TransactionORM.date))
            .order_by(func.strftime("%Y", TransactionORM.date), func.strftime("%m", TransactionORM.date))
        )
        query = AnalyticsService._apply_review_filter(query, include_unreviewed)

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
            "unreviewed": AnalyticsService._get_unreviewed_summary(
                session, date(min(years), 1, 1), date(max(years), 12, 31), include_unreviewed
            ),
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

        latest_transaction_date = session.query(func.max(TransactionORM.date)).scalar()
        default_year = latest_transaction_date.year if latest_transaction_date else date.today().year

        # Get current year for default selection
        current_year = date.today().year

        return {
            "years": years,
            "current_year": current_year,
            "default_year": default_year,
            "latest_transaction_date": latest_transaction_date.isoformat() if latest_transaction_date else None,
        }


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
            return _to_float(budget_plan.monthly_budget)

        # Fallback to category default budget
        category = session.query(CategoryORM).filter(CategoryORM.id == category_id).first()
        if category:
            return _to_float(category.budget)

        return 0.0

    @staticmethod
    def get_budgets_for_year(session: Session, year: int) -> dict[str, Any]:
        """Get all budgets for a specific year."""
        # Fetch categories and their year-specific budgets in one query (avoids N+1)
        rows = (
            session.query(CategoryORM, BudgetPlanORM)
            .outerjoin(
                BudgetPlanORM,
                and_(BudgetPlanORM.category_id == CategoryORM.id, BudgetPlanORM.year == year),
            )
            .filter(CategoryORM.is_active)
            .all()
        )

        budgets = []
        for category, budget_plan in rows:
            if budget_plan:
                budget = _to_float(budget_plan.monthly_budget)
                has_year_specific = True
            else:
                budget = _to_float(category.budget)
                has_year_specific = False

            budgets.append(
                {
                    "category_id": category.id,
                    "category_name": category.name,
                    "category_type": category.type,
                    "monthly_budget": budget,
                    "has_year_specific": has_year_specific,
                    "fallback_budget": _to_float(category.budget),
                }
            )

        has_year_specific_budgets = any(b["has_year_specific"] for b in budgets)
        return {
            "year": year,
            "budgets": budgets,
            "total_categories": len(budgets),
            "has_year_specific_budgets": has_year_specific_budgets,
        }

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

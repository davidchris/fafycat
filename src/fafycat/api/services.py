"""Service layer for database operations."""

import calendar
import math
import re
import statistics
from datetime import date, datetime, timedelta
from typing import Any, cast

from sqlalchemy import and_, case, func, literal, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased, joinedload
from sqlalchemy.sql import ColumnElement

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


REVIEW_IMPACT_SORT = "review_impact"
"""Sort key: pending siblings times uncertainty, so one review resolves the most.

Measured in experiments/04-queue-ordering: at every reviewer budget this order
labels more of the backlog correctly than least-confident-first, because a
review of a merchant with many pending rows propagates to all of them.
"""


SORT_COLUMNS = {
    "date": TransactionORM.date,
    "confidence_score": TransactionORM.confidence_score,
    "amount": TransactionORM.amount,
    "name": TransactionORM.name,
}
"""Transaction columns the review table may sort by, besides :data:`REVIEW_IMPACT_SORT`."""

SORT_KEYS = (REVIEW_IMPACT_SORT, *SORT_COLUMNS)
"""Every accepted ``sort_by`` value."""


class CategoryNotFoundError(LookupError):
    """No category has the given name."""

    def __init__(self, ref: str) -> None:
        super().__init__(f"Category not found: {ref}")


class AmbiguousCategoryError(LookupError):
    """Several categories share the name; the caller must say which type it means."""

    def __init__(self, ref: str, candidates: list[CategoryORM]) -> None:
        self.candidates = candidates
        options = ", ".join(f"'{qualified_name(c)}'" for c in candidates)
        super().__init__(f"Category name '{ref}' is used by several types; use one of {options}")


class DuplicateCategoryError(ValueError):
    """A category with this name exists already, ignoring case and type."""

    def __init__(self, name: str) -> None:
        super().__init__(f"Category '{name}' already exists")


_QUALIFIED = re.compile(r"^(?P<name>.+) \((?P<type>spending|income|saving)\)$")


def qualified_name(category: Any) -> str:
    """``name (type)``: the label that tells apart categories sharing a name."""
    return f"{category.name} ({category.type})"


def _name_key(name: object) -> str:
    """Comparison key for category names: stripped and case-folded in Python.

    SQLite's ``lower()`` folds ASCII only, so ``Ärzte`` would not match ``ärzte`` in SQL.
    """
    return str(name).strip().casefold()


def find_category(session: Session, ref: str) -> CategoryORM:
    """Resolve a category reference: its name, ignoring case, or ``name (type)``.

    Names are unique for new categories, but databases created with the old
    default set hold ``other`` and ``investment`` twice. Such a name resolves
    to the one active category of that name, else only with the type
    qualifier, so a lookup never guesses.

    Raises:
        CategoryNotFoundError: No category matches.
        AmbiguousCategoryError: Several active categories share the unqualified name.
    """
    ref = ref.strip()
    categories = session.query(CategoryORM).order_by(CategoryORM.id).all()
    found = [c for c in categories if _name_key(c.name) == _name_key(ref)]
    if len(found) > 1:
        active = [c for c in found if c.is_active]
        if len(active) == 1:
            return active[0]
        raise AmbiguousCategoryError(ref, found)
    if found:
        return found[0]
    qualified = _QUALIFIED.match(ref)
    if qualified:
        for category in categories:
            if _name_key(category.name) == _name_key(qualified["name"]) and category.type == qualified["type"]:
                return category
    raise CategoryNotFoundError(ref)


def resolve_category(session: Session, *, name: str | None = None, category_id: int | None = None) -> CategoryORM:
    """Resolve a category by id when given, else by name with :func:`find_category`.

    Raises:
        CategoryNotFoundError: No category matches.
        AmbiguousCategoryError: The name is shared and needs its type.
    """
    if category_id is not None:
        category = session.get(CategoryORM, category_id)
        if category is None:
            raise CategoryNotFoundError(f"id {category_id}")
        return category
    if name is None:
        raise CategoryNotFoundError("(none given)")
    return find_category(session, name)


def _category_ids_for(session: Session, ref: str) -> list[int]:
    """Ids a category filter matches: one for a resolvable reference, every namesake for a shared name."""
    try:
        return [_to_int(find_category(session, ref).id)]
    except AmbiguousCategoryError as e:
        return [_to_int(c.id) for c in e.candidates]
    except CategoryNotFoundError:
        return []


def _apply_sort(query, sort_by: str, sort_order: str):
    """Order a transaction query by one of :data:`SORT_KEYS`, ties broken by id.

    Raises:
        ValueError: ``sort_by`` is not one of :data:`SORT_KEYS`.
    """
    descending = sort_order.lower() != "asc"
    if sort_by == REVIEW_IMPACT_SORT:
        impact = _review_impact_expr()
        return query.order_by(
            impact.desc() if descending else impact.asc(), TransactionORM.date.asc(), TransactionORM.id
        )
    if sort_by not in SORT_COLUMNS:
        raise ValueError(f"sort_by must be one of {', '.join(SORT_KEYS)}")
    sort_column = SORT_COLUMNS[sort_by]
    return query.order_by(sort_column.desc() if descending else sort_column.asc(), TransactionORM.id)


def _name_taken(session: Session, name: str, *, exclude_id: int | None = None) -> bool:
    return any(
        _name_key(other_name) == _name_key(name) and other_id != exclude_id
        for other_id, other_name in session.query(CategoryORM.id, CategoryORM.name)
    )


def _pending_siblings_expr() -> ColumnElement:
    """Correlated count of unreviewed rows sharing the outer row's merchant pattern, itself included.

    Rows without a pattern have nothing to propagate to and count as 1. This
    counts every pending row of the merchant, as the queue-ordering
    experiment did; propagation itself is narrower (see
    :func:`_unreviewed_siblings`), so the count is an upper bound on what one
    review resolves.
    """
    sibling = aliased(TransactionORM)
    count = (
        select(func.count(sibling.id))
        .where(sibling.merchant_pattern == TransactionORM.merchant_pattern, sibling.is_reviewed.is_(False))
        .correlate(TransactionORM)
        .scalar_subquery()
    )
    has_pattern = and_(TransactionORM.merchant_pattern.is_not(None), TransactionORM.merchant_pattern != "")
    return case((has_pattern, count), else_=literal(1))


def _review_impact_expr() -> ColumnElement:
    """``pending_siblings x (1 - confidence)``; a row without a prediction is fully uncertain."""
    return _pending_siblings_expr() * (1.0 - func.coalesce(TransactionORM.confidence_score, 0.0))


def _pending_sibling_counts(session: Session, transactions: list[TransactionORM]) -> dict[str, int]:
    """Unreviewed rows per merchant pattern, for the patterns of ``transactions``."""
    patterns = {str(t.merchant_pattern) for t in transactions if t.merchant_pattern}
    if not patterns:
        return {}
    rows = (
        session.query(TransactionORM.merchant_pattern, func.count(TransactionORM.id))
        .filter(TransactionORM.merchant_pattern.in_(patterns), TransactionORM.is_reviewed.is_(False))
        .group_by(TransactionORM.merchant_pattern)
        .all()
    )
    return {str(pattern): int(count) for pattern, count in rows}


def _pending_siblings_of(transaction: TransactionORM, counts: dict[str, int]) -> int:
    """The row's own pending-sibling count from :func:`_pending_sibling_counts`; 1 without a pattern."""
    if transaction.is_reviewed:
        return 0
    return counts.get(_pattern_of(transaction), 1) if transaction.merchant_pattern else 1


def _unreviewed_siblings(session: Session, source: TransactionORM, category_id: int | None):
    """Query for the unreviewed transactions sharing ``source``'s merchant pattern that the model saw the same way.

    A sibling qualifies when it has no prediction, or its prediction equals
    the source's prediction (a correction reaches every row the model got
    wrong in the same way) or the category being applied (a confirmation
    reaches every row the model already agrees with). Siblings the model
    predicted differently are left for review: the merchant is shared, but
    purpose or amount told the model something else, as with transfers
    between own accounts that serve different purposes.
    """
    predicted = source.predicted_category_id
    same_as_source = (
        TransactionORM.predicted_category_id.is_(None)
        if predicted is None
        else TransactionORM.predicted_category_id == predicted
    )
    seen_the_same_way = [TransactionORM.predicted_category_id.is_(None), same_as_source]
    if category_id is not None:
        seen_the_same_way.append(TransactionORM.predicted_category_id == category_id)
    return session.query(TransactionORM).filter(
        TransactionORM.merchant_pattern == source.merchant_pattern,
        TransactionORM.id != source.id,
        TransactionORM.is_reviewed == False,  # noqa: E712
        or_(*seen_the_same_way),
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
            query = query.filter(TransactionORM.category_id.in_(_category_ids_for(session, category)))

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
                predicted_category_id=_to_int_or_none(t.predicted_category_id),
                actual_category_id=_to_int_or_none(t.category_id),
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
        """Get transactions with pagination and enhanced filtering.

        Raises:
            ValueError: ``sort_by`` is not one of :data:`SORT_KEYS`.
        """
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
                category_ids = _category_ids_for(session, category)
                query = query.filter(
                    or_(
                        TransactionORM.category_id.in_(category_ids),
                        and_(
                            TransactionORM.category_id.is_(None),
                            TransactionORM.predicted_category_id.in_(category_ids),
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

        query = _apply_sort(query, sort_by, sort_order)

        # Apply pagination
        query = query.offset(skip).limit(limit)
        transactions = query.all()
        sibling_counts = _pending_sibling_counts(session, transactions)

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
                predicted_category_id=_to_int_or_none(t.predicted_category_id),
                actual_category_id=_to_int_or_none(t.category_id),
                confidence=_to_float(t.confidence_score) if t.confidence_score is not None else None,
                is_reviewed=_to_bool(t.is_reviewed),
                review_priority=_to_str(t.review_priority) if t.review_priority else None,
                pending_siblings=_pending_siblings_of(t, sibling_counts),
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
        """Set a transaction's category from its id, a name, or a ``name (type)`` reference.

        Returns:
            The updated transaction, or None when the transaction does not exist.

        Raises:
            CategoryNotFoundError: No category matches the reference.
            AmbiguousCategoryError: The name is shared and needs its type.
        """
        transaction = session.query(TransactionORM).filter(TransactionORM.id == transaction_id).first()

        if not transaction:
            return None

        category = resolve_category(session, name=update.actual_category, category_id=update.category_id)

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
            predicted_category_id=_to_int_or_none(transaction.predicted_category_id),
            actual_category_id=_to_int(category.id),
            confidence=_to_float(transaction.confidence_score) if transaction.confidence_score is not None else None,
            is_reviewed=_to_bool(transaction.is_reviewed),
            review_priority=_to_str(transaction.review_priority) if transaction.review_priority else None,
            created_at=_to_datetime(transaction.imported_at),
            updated_at=_to_datetime(transaction.imported_at),
        )

    @staticmethod
    def count_unreviewed_siblings(session: Session, transaction_id: str) -> tuple[str, int]:
        """Count the unreviewed siblings a just-saved category would propagate to.

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
        if transaction is None or not pattern:
            return "", 0

        return pattern, _unreviewed_siblings(session, transaction, _to_int_or_none(transaction.category_id)).count()

    @staticmethod
    def propagate_category(
        session: Session, source_id: str, category_name: str | None = None, category_id: int | None = None
    ) -> dict:
        """Apply a category to the unreviewed siblings the model saw like the source.

        Each affected transaction is marked reviewed and gets its own Review
        Event with the ``propagation`` actor, so the Audit Trail names the
        correction it came from. Already reviewed transactions are left alone.
        The pattern's Merchant Rule is recomputed afterwards.

        Args:
            session: Open database session. Committed by this function.
            source_id: The transaction the user corrected.
            category_name: Name of the category to apply, used when ``category_id`` is not given.
            category_id: Id of the category to apply.

        Returns:
            A dict with the number of transactions ``applied``, the
            ``pattern``, and the ``category`` name.
        """
        source = session.query(TransactionORM).filter(TransactionORM.id == source_id).first()
        pattern = _pattern_of(source)
        try:
            category: CategoryORM | None = resolve_category(session, name=category_name, category_id=category_id)
        except LookupError:
            category = None
        if source is None or not pattern or category is None:
            return {"applied": 0, "pattern": pattern, "category": category_name or category_id}

        siblings = _unreviewed_siblings(session, source, _to_int(category.id)).all()

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


def _commit_category(session: Session, name: str) -> None:
    """Commit a category change; a unique-constraint race becomes a DuplicateCategoryError."""
    try:
        session.commit()
    except IntegrityError as e:
        session.rollback()
        raise DuplicateCategoryError(name) from e


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
        """Create a new category.

        Raises:
            DuplicateCategoryError: The name exists already, ignoring case and type.
        """
        if _name_taken(session, category.name):
            raise DuplicateCategoryError(category.name)
        db_category = CategoryORM(name=category.name, type=category.type, budget=category.budget or 0.0)

        session.add(db_category)
        _commit_category(session, category.name)
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
        """Update an existing category.

        Raises:
            DuplicateCategoryError: The new name belongs to another category, ignoring case.
        """
        category = session.query(CategoryORM).filter(CategoryORM.id == category_id).first()

        if not category:
            return None

        # Update fields if provided
        if update.name is not None:
            if _name_taken(session, update.name, exclude_id=category_id):
                raise DuplicateCategoryError(update.name)
            category.name = update.name
        if update.type is not None:
            category.type = update.type
        if update.is_active is not None:
            category.is_active = update.is_active
        if update.budget is not None:
            category.budget = update.budget

        _commit_category(session, _to_str(category.name))

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
        """Get spending per category, with budgets for every calendar year of the range.

        Amounts are converted to money spent (see ``money_spent``) here, so the rest of the
        variance code only sees positive spending.

        Args:
            session: Database session.
            start_date: First day of the range (inclusive).
            end_date: Last day of the range (inclusive).
            include_unreviewed: When False, only reviewed transactions are aggregated.

        Returns:
            Mapping of category id to budget/spent data, including unreviewed shares.
        """
        # Group transactions by year and category to handle cross-year periods
        query = (
            session.query(
                CategoryORM.id,
                CategoryORM.name,
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
            .group_by(CategoryORM.id, CategoryORM.name, func.strftime("%Y", TransactionORM.date))
        )
        query = AnalyticsService._apply_review_filter(query, include_unreviewed)

        category_data: dict[int, dict] = {}
        for result in query.all():
            category_id = result.id
            if category_id not in category_data:
                category_data[category_id] = AnalyticsService._new_variance_entry(
                    session, category_id, result.name, start_date, end_date
                )
            data = category_data[category_id]
            year_data = data["yearly_data"][int(result.year)]

            spent = money_spent(float(result.actual_amount))
            unreviewed_spent = money_spent(float(result.unreviewed_amount or 0.0))
            unreviewed_count = int(result.unreviewed_count or 0)

            year_data["actual"] += spent
            year_data["unreviewed_amount"] += unreviewed_spent
            year_data["unreviewed_count"] += unreviewed_count
            data["total_actual"] += spent
            data["unreviewed_amount"] += unreviewed_spent
            data["unreviewed_count"] += unreviewed_count

        return category_data

    @staticmethod
    def _new_variance_entry(
        session: Session, category_id: int, category_name: str, start_date: date, end_date: date
    ) -> dict[str, Any]:
        """Return an empty variance entry carrying the category's budget for the range."""
        yearly_budgets = AnalyticsService._yearly_budgets(session, category_id, start_date, end_date)
        return {
            "category_name": category_name,
            "yearly_data": {
                year: {
                    "budget": budget["budget"],
                    "actual": 0.0,
                    "months": budget["months"],
                    "unreviewed_amount": 0.0,
                    "unreviewed_count": 0,
                }
                for year, budget in yearly_budgets.items()
            },
            "total_actual": 0.0,
            "total_budget": sum(budget["budget"] for budget in yearly_budgets.values()),
            "unreviewed_amount": 0.0,
            "unreviewed_count": 0,
        }

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
                entry = AnalyticsService._new_variance_entry(
                    session, cat_id, _to_str(category.name), start_date, end_date
                )
                if entry["total_budget"] > 0:
                    category_data[cat_id] = entry

    @staticmethod
    def _yearly_budgets(
        session: Session, category_id: int, start_date: date, end_date: date
    ) -> dict[int, dict[str, float]]:
        """Return the prorated budget of each calendar year that the range touches.

        Each year uses its own budget plan, falling back to the legacy ``categories.budget``
        (see ``BudgetService.get_budget_for_category_year``). The monthly budget is prorated with
        ``budgeted_months``.

        Returns:
            Mapping of year to ``{"budget": ..., "months": ...}``.
        """
        yearly: dict[int, dict[str, float]] = {}
        for year in range(start_date.year, end_date.year + 1):
            months = budgeted_months(max(start_date, date(year, 1, 1)), min(end_date, date(year, 12, 31)))
            monthly_budget = BudgetService.get_budget_for_category_year(session, category_id, year)
            yearly[year] = {"budget": monthly_budget * months, "months": months}
        return yearly

    @staticmethod
    def _calculate_total_budget_for_period(
        session: Session, category_id: int, start_date: date, end_date: date
    ) -> float:
        """Return a category's prorated budget for a date range, across year boundaries."""
        yearly = AnalyticsService._yearly_budgets(session, category_id, start_date, end_date)
        return sum(budget["budget"] for budget in yearly.values())

    @staticmethod
    def _build_variance_result(category_data: dict[int, dict], start_date: date, end_date: date) -> dict[str, Any]:
        """Build the final variance result from category data.

        ``actual`` is money spent (positive) and ``variance`` is ``budget - actual``: positive
        means under budget, negative means overspent. A category without a budget is overspent
        by everything it spent. ``variance_percentage`` is ``None`` when there is no budget.
        """
        variances = []
        total_budget = 0.0
        total_actual = 0.0

        for category_id, data in category_data.items():
            budget = data["total_budget"]
            spent = data["total_actual"]
            variance = budget - spent

            variances.append(
                {
                    "category_id": category_id,
                    "category_name": data["category_name"],
                    "budget": budget,
                    "actual": spent,
                    "unreviewed_amount": data["unreviewed_amount"],
                    "unreviewed_count": data["unreviewed_count"],
                    "variance": variance,
                    "variance_percentage": _percent_of_budget(variance, budget),
                    "is_overspent": variance < 0,
                    "yearly_breakdown": data["yearly_data"],
                }
            )

            total_budget += budget
            total_actual += spent

        variances.sort(key=lambda x: abs(x["variance"]), reverse=True)
        total_variance = total_budget - total_actual

        return {
            "variances": variances,
            "summary": {
                "total_budget": total_budget,
                "total_actual": total_actual,
                "total_variance": total_variance,
                "total_variance_percentage": _percent_of_budget(total_variance, total_budget),
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

        ``amount`` is the signed sum (spending negative). ``budget`` is the category's prorated
        budget for the range, from the same source as ``get_budget_variance``. ``budget_variance``
        is ``budget - spent`` for spending categories (negative means overspent) and ``None`` for
        income and saving. ``percentage`` is the category's share of the total of its own type.

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

        query = query.group_by(CategoryORM.id, CategoryORM.name, CategoryORM.type)
        query = query.order_by(func.sum(TransactionORM.amount).desc())

        results = query.all()

        categories = []
        total_amount = 0.0
        type_totals: dict[str, float] = {}

        for result in results:
            amount = float(result.total_amount) if result.total_amount else 0.0
            # Same budget source and proration as the variance endpoint.
            budget = AnalyticsService._calculate_total_budget_for_period(session, result.id, start_date, end_date)

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
                    "budget_variance": budget - money_spent(amount) if result.type == CategoryType.SPENDING else None,
                }
            )

            total_amount += amount
            type_totals[result.type] = type_totals.get(result.type, 0.0) + amount

        # Share of the category's own type total (spending of all spending, income of all income).
        # Both amounts carry the same sign, so the ratio is positive for spending too.
        for category in categories:
            type_total = type_totals[category["category_type"]]
            category["percentage"] = (category["amount"] / type_total * 100) if type_total else 0.0

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
                    "date_range": {"windows": []},
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
                    TransactionORM.date <= same_day_in_year(year, latest_transaction_date),
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
            query_end_date = same_day_in_year(year, latest_transaction_date) if latest_transaction_date else None
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
            end = same_day_in_year(year, cutoff) if cutoff else date(year, 12, 31)
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


def money_spent(amount: float) -> float:
    """Convert a signed spending amount into money spent.

    Sign convention: the database stores money leaving the account as a negative ``amount``,
    so the summed amount of a spending category is negative. Budget variance reports money spent
    as a positive ``actual``; category breakdown keeps the signed ``amount`` and uses this
    function only for ``budget_variance``. A net refund gives a negative value.

    Args:
        amount: Signed sum of transaction amounts.

    Returns:
        Money spent, positive for net outflows.
    """
    return -amount


def budgeted_months(start_date: date, end_date: date) -> float:
    """Return how many months of a monthly budget a date range covers.

    Each calendar month counts by the share of its days inside the range: a full month is 1.0,
    1-15 March is 15/31. A full year is exactly 12.

    Args:
        start_date: First day of the range (inclusive).
        end_date: Last day of the range (inclusive).

    Returns:
        Number of budget months, 0.0 for an empty range.
    """
    months = 0.0
    current = start_date
    while current <= end_date:
        days_in_month = calendar.monthrange(current.year, current.month)[1]
        month_end = date(current.year, current.month, days_in_month)
        months += ((min(end_date, month_end) - current).days + 1) / days_in_month
        if month_end >= end_date:
            break
        current = month_end + timedelta(days=1)
    return months


def same_day_in_year(year: int, day: date) -> date:
    """Return the month and day of ``day`` in ``year``; 29 February becomes 28 February.

    Args:
        year: Target year.
        day: Date whose month and day are kept.

    Returns:
        The same calendar day in ``year``, clamped to 28 February in non-leap years.
    """
    if day.month == 2 and day.day == 29 and not calendar.isleap(year):
        return date(year, 2, 28)
    return date(year, day.month, day.day)


def _percent_of_budget(variance: float, budget: float) -> float | None:
    """Return ``variance`` as a percentage of ``budget``, or ``None`` without a budget."""
    return variance / budget * 100 if budget > 0 else None


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

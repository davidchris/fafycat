"""Database operations using SQLAlchemy."""

import logging
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker

from .config import AppConfig

logger = logging.getLogger(__name__)

Base = declarative_base()


def _utc_now() -> datetime:
    return datetime.now(UTC)


class CategoryORM(Base):
    """Category table."""

    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(String, nullable=False)
    name = Column(String(50), nullable=False)
    budget = Column(Float, nullable=False, default=0.0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utc_now)
    updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now)

    __table_args__ = (
        CheckConstraint("type IN ('spending', 'income', 'saving')", name="check_category_type"),
        UniqueConstraint("type", "name", name="uq_category_type_name"),
    )

    transactions = relationship("TransactionORM", foreign_keys="TransactionORM.category_id")
    predictions = relationship("TransactionORM", foreign_keys="TransactionORM.predicted_category_id")
    merchant_mappings = relationship("MerchantMappingORM", back_populates="category")
    budget_plans = relationship("BudgetPlanORM", back_populates="category", cascade="all, delete-orphan")


class BudgetPlanORM(Base):
    """Budget plan table for year-specific budgets."""

    __tablename__ = "budget_plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)
    year = Column(Integer, nullable=False)
    monthly_budget = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, default=_utc_now)
    updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now)

    __table_args__ = (
        UniqueConstraint("category_id", "year", name="uq_budget_plan_category_year"),
        CheckConstraint("year >= 2020 AND year <= 2030", name="check_budget_year_range"),
        CheckConstraint("monthly_budget >= 0", name="check_budget_positive"),
        Index("idx_budget_plans_year", "year"),
        Index("idx_budget_plans_category", "category_id"),
    )

    category = relationship("CategoryORM", back_populates="budget_plans")


class TransactionORM(Base):
    """Transaction table."""

    __tablename__ = "transactions"

    id = Column(String(16), primary_key=True)
    date = Column(Date, nullable=False)
    value_date = Column(Date)
    name = Column(Text, nullable=False)
    purpose = Column(Text)
    amount = Column(Float, nullable=False)
    currency = Column(String(3), default="EUR")
    category_id = Column(Integer, ForeignKey("categories.id"))
    predicted_category_id = Column(Integer, ForeignKey("categories.id"))
    confidence_score = Column(Float)
    is_reviewed = Column(Boolean, default=False)
    review_priority = Column(String(20), default="standard")  # standard, high, quality_check
    # Cleaned merchant name (see MerchantCleaner). Groups the siblings a
    # correction propagates to and keys the Merchant Rule for this row.
    merchant_pattern = Column(String, index=True)
    imported_at = Column(DateTime, default=_utc_now)
    import_batch = Column(String, nullable=False)

    __table_args__ = (
        CheckConstraint("confidence_score >= 0 AND confidence_score <= 1", name="check_confidence_range"),
        Index("idx_transactions_date", "date"),
        Index("idx_transactions_category", "category_id"),
        Index("idx_transactions_predicted_category", "predicted_category_id"),
        Index("idx_transactions_reviewed", "is_reviewed"),
        Index("idx_transactions_confidence", "confidence_score"),
        Index("idx_transactions_amount", "amount"),
        Index("idx_transactions_name", "name"),
        # Compound indexes for common filtering combinations
        Index("idx_transactions_reviewed_date", "is_reviewed", "date"),
        Index("idx_transactions_reviewed_confidence", "is_reviewed", "confidence_score"),
    )

    category = relationship("CategoryORM", foreign_keys=[category_id], overlaps="transactions")
    predicted_category = relationship("CategoryORM", foreign_keys=[predicted_category_id], overlaps="predictions")


class MerchantMappingORM(Base):
    """Merchant mapping table."""

    __tablename__ = "merchant_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_pattern = Column(String, nullable=False, unique=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)
    confidence = Column(Float, default=1.0)
    occurrence_count = Column(Integer, default=1)
    last_seen = Column(Date)
    created_at = Column(DateTime, default=_utc_now)

    __table_args__ = (Index("idx_merchant_mappings_pattern", "merchant_pattern"),)

    category = relationship("CategoryORM", back_populates="merchant_mappings")


class AppSettingsORM(Base):
    """Application settings key-value store."""

    __tablename__ = "app_settings"

    key = Column(String, primary_key=True)
    value = Column(String, nullable=False)
    updated_at = Column(DateTime, default=_utc_now, onupdate=_utc_now)


class ModelMetadataORM(Base):
    """Model metadata table."""

    __tablename__ = "model_metadata"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_version = Column(String, nullable=False)
    training_date = Column(DateTime, default=_utc_now)
    accuracy = Column(Float)
    feature_importance = Column(Text)  # JSON
    parameters = Column(Text)  # JSON
    is_active = Column(Boolean, default=False)


class PredictionEventORM(Base):
    """One Prediction Event: what every model component said in one pipeline run.

    Append-only. Probability columns hold JSON objects keyed by category id.
    """

    __tablename__ = "prediction_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    transaction_id = Column(String(16), ForeignKey("transactions.id"), nullable=False)
    created_at = Column(DateTime, default=_utc_now, nullable=False)
    trigger = Column(String(32), nullable=False)  # import, batch_unpredicted, repredict
    model_id = Column(String(32), nullable=False)  # fingerprint of the model file
    threshold = Column(Float, nullable=False)
    decision = Column(String(20), nullable=False)  # ReviewPriority value
    source = Column(String(20), nullable=False)  # merchant_rule, ensemble, lgbm
    final_category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)
    final_confidence = Column(Float, nullable=False)
    rule_pattern = Column(Text)
    rule_category_id = Column(Integer, ForeignKey("categories.id"))
    rule_confidence = Column(Float)
    lgbm_weight = Column(Float)
    nb_weight = Column(Float)
    rule_weight = Column(Float)
    lgbm_probs = Column(Text)  # JSON {category_id: prob}
    nb_probs = Column(Text)  # JSON
    rule_probs = Column(Text)  # JSON, absent when no Merchant Rule matched
    ensemble_probs = Column(Text)  # JSON
    feature_contributions = Column(Text)  # JSON

    __table_args__ = (Index("idx_prediction_events_transaction", "transaction_id", "created_at"),)


class ReviewEventORM(Base):
    """One Review Event: a category being set on a transaction, by whom.

    Append-only. Together with Prediction Events this is the Audit Trail.
    """

    __tablename__ = "review_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    transaction_id = Column(String(16), ForeignKey("transactions.id"), nullable=False)
    created_at = Column(DateTime, default=_utc_now, nullable=False)
    actor = Column(String(32), nullable=False)  # ReviewActor value
    from_category_id = Column(Integer, ForeignKey("categories.id"))
    to_category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)
    predicted_category_id = Column(Integer, ForeignKey("categories.id"))
    confidence_score = Column(Float)
    note = Column(Text)

    __table_args__ = (Index("idx_review_events_transaction", "transaction_id", "created_at"),)


class DatabaseManager:
    """Database connection and session management."""

    def __init__(self, config: AppConfig):
        self.config = config

        # Configure SQLite connection with timeout for long operations
        connect_args = {}
        if config.database.url.startswith("sqlite"):
            connect_args = {
                "timeout": 300,  # 5 minutes timeout for SQLite operations
                "check_same_thread": False,
            }

        self.engine = create_engine(config.database.url, echo=config.database.echo, connect_args=connect_args)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    def create_tables(self) -> None:
        """Create all database tables and any indexes missing from existing tables.

        ``create_all`` skips tables that already exist, so indexes added to the
        schema after a database was created are built explicitly here.
        """
        Base.metadata.create_all(bind=self.engine)
        with self.engine.connect() as conn:
            for table in Base.metadata.tables.values():
                self._add_missing_columns(conn, table)
            for table in Base.metadata.tables.values():
                for index in table.indexes:
                    index.create(bind=conn, checkfirst=True)
            self._repair_review_flags(conn)
            conn.commit()

    @staticmethod
    def _add_missing_columns(conn, table) -> None:
        """Add columns the ORM declares but an older database lacks (SQLite ``ALTER TABLE ADD COLUMN``).

        Only nullable or defaulted columns can be added this way; that is the
        contract for evolving existing tables in this project.
        """
        existing = {row[1] for row in conn.exec_driver_sql(f'PRAGMA table_info("{table.name}")')}
        if not existing:
            return
        for column in table.columns:
            if column.name in existing:
                continue
            ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {column.type.compile(conn.dialect)}'
            conn.exec_driver_sql(ddl)

    @staticmethod
    def _repair_review_flags(conn) -> tuple[int, int]:
        """Restore the invariant ``is_reviewed = 1`` if and only if ``category_id`` is set.

        A category is a human decision (a labelled import, a review, an
        auto-accept that copied the prediction); the reviewed flag tells the
        queue, training, Merchant Rules and calibration to trust it. Two
        historical bugs broke the pairing in the user's data:

        * Before 2025-06-06 the labelled CSV import wrote the category but not
          the flag, so human labels sat in the review queue and could be
          overwritten by a confident re-predict. Those rows get the flag.
        * Between 2025-06-10 and 2026-07-02 the batch-predict endpoints set the
          flag on auto-accept without copying the predicted category, hiding
          unlabelled rows from the queue and from training. Those rows lose the
          flag and Review Priority, so the next re-predict scores them again:
          confident ones are auto-accepted with a category, the rest surface
          in the queue.

        Idempotent; runs on every ``create_tables``.

        Returns:
            ``(flagged, reset)``: rows that gained the reviewed flag and rows
            that lost it.
        """
        flagged = conn.exec_driver_sql(
            "UPDATE transactions SET is_reviewed = 1 WHERE is_reviewed IS NOT 1 AND category_id IS NOT NULL"
        ).rowcount
        reset = conn.exec_driver_sql(
            "UPDATE transactions SET is_reviewed = 0, review_priority = NULL "
            "WHERE is_reviewed = 1 AND category_id IS NULL"
        ).rowcount
        if flagged:
            logger.warning("Marked %d transactions with a category as reviewed", flagged)
        if reset:
            logger.warning("Reset %d transactions that were marked reviewed without a category", reset)
        return flagged, reset

    def get_session(self) -> Session:
        """Get database session."""
        return self.SessionLocal()

    def init_default_categories(self) -> None:
        """Initialize default categories - DEPRECATED: Use discover_categories_from_data instead."""
        default_categories = [
            ("spending", "groceries", 400.0),
            ("spending", "restaurants", 200.0),
            ("spending", "transportation", 150.0),
            ("spending", "utilities", 200.0),
            ("spending", "rent", 1200.0),
            ("spending", "insurance", 100.0),
            ("spending", "healthcare", 150.0),
            ("spending", "entertainment", 100.0),
            ("spending", "shopping", 200.0),
            ("spending", "other", 0.0),
            ("income", "salary", 0.0),
            ("income", "freelance", 0.0),
            ("income", "investment", 0.0),
            ("income", "other", 0.0),
            ("saving", "emergency_fund", 300.0),
            ("saving", "investment", 500.0),
            ("saving", "vacation", 200.0),
        ]

        with self.get_session() as session:
            existing = session.query(CategoryORM).count()
            if existing == 0:
                for cat_type, name, budget in default_categories:
                    category = CategoryORM(type=cat_type, name=name, budget=budget)
                    session.add(category)
                session.commit()

    def discover_categories_from_data(self, categories: set[str]) -> int:
        """Discover and create categories from imported labeled data (without budgets).

        Args:
            categories: Set of category names found in labeled data

        Returns:
            Number of new categories created
        """
        if not categories:
            return 0

        created_count = 0

        with self.get_session() as session:
            for category_name in sorted(categories):
                # Normalize category name to match Pydantic model behavior
                normalized_name = category_name.strip().lower()

                # Check if category already exists (using normalized name)
                existing = session.query(CategoryORM).filter(CategoryORM.name == normalized_name).first()

                if not existing:
                    # Infer category type based on common patterns
                    category_type = self._infer_category_type(category_name)

                    # Create category without budget (0.0) - use normalized name
                    new_category = CategoryORM(
                        type=category_type,
                        name=normalized_name,
                        budget=0.0,  # No budget initially
                        is_active=True,
                    )
                    session.add(new_category)
                    created_count += 1

            session.commit()

        return created_count

    def _infer_category_type(self, category_name: str) -> str:
        """Infer category type from category name patterns."""
        name_lower = category_name.lower()

        # Income patterns - expanded list
        income_keywords = [
            "salary",
            "income",
            "freelance",
            "dividend",
            "interest",
            "bonus",
            "wage",
            "pay",
            "paycheck",
            "earnings",
            "revenue",
            "profit",
            "refund",
            "tax_refund",
            "gift",
            "prize",
            "winnings",
            "commission",
            "royalties",
            "cashback",
        ]
        if any(keyword in name_lower for keyword in income_keywords):
            return "income"

        # Saving patterns - expanded list
        saving_keywords = [
            "saving",
            "investment",
            "fund",
            "pension",
            "retirement",
            "401k",
            "ira",
            "emergency",
            "vacation_fund",
            "house_fund",
            "stocks",
            "bonds",
            "mutual",
            "etf",
            "crypto",
            "bitcoin",
            "savings_account",
            "cd",
            "certificate",
        ]
        if any(keyword in name_lower for keyword in saving_keywords):
            return "saving"

        # Default to spending for all other categories
        return "spending"


def get_categories(session: Session, active_only: bool = True) -> list[CategoryORM]:
    """Get all categories."""
    query = session.query(CategoryORM)
    if active_only:
        query = query.filter(CategoryORM.is_active)
    return query.all()


def get_transactions(session: Session, limit: int | None = None, unreviewed_only: bool = False) -> list[TransactionORM]:
    """Get transactions with optional filtering."""
    query = session.query(TransactionORM)
    if unreviewed_only:
        query = query.filter(~TransactionORM.is_reviewed)
    query = query.order_by(TransactionORM.date.desc())
    if limit:
        query = query.limit(limit)
    return query.all()


def get_merchant_mapping(session: Session, merchant_pattern: str) -> MerchantMappingORM | None:
    """Get merchant mapping by pattern."""
    return session.query(MerchantMappingORM).filter(MerchantMappingORM.merchant_pattern == merchant_pattern).first()

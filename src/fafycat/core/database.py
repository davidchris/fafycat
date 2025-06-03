"""Database operations using SQLAlchemy."""

from datetime import datetime

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
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, relationship, sessionmaker

from .config import AppConfig

Base = declarative_base()


class CategoryORM(Base):
    """Category table."""

    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(String, nullable=False)
    name = Column(String(50), nullable=False)
    budget = Column(Float, nullable=False, default=0.0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("type IN ('spending', 'income', 'saving')", name="check_category_type"),
        UniqueConstraint("type", "name", name="uq_category_type_name"),
    )

    transactions = relationship("TransactionORM", foreign_keys="TransactionORM.category_id")
    predictions = relationship("TransactionORM", foreign_keys="TransactionORM.predicted_category_id")
    merchant_mappings = relationship("MerchantMappingORM", back_populates="category")


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
    imported_at = Column(DateTime, default=datetime.utcnow)
    import_batch = Column(String, nullable=False)

    __table_args__ = (
        CheckConstraint("confidence_score >= 0 AND confidence_score <= 1", name="check_confidence_range"),
        Index("idx_transactions_date", "date"),
        Index("idx_transactions_category", "category_id"),
        Index("idx_transactions_reviewed", "is_reviewed"),
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
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("idx_merchant_mappings_pattern", "merchant_pattern"),)

    category = relationship("CategoryORM", back_populates="merchant_mappings")


class ModelMetadataORM(Base):
    """Model metadata table."""

    __tablename__ = "model_metadata"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_version = Column(String, nullable=False)
    training_date = Column(DateTime, default=datetime.utcnow)
    accuracy = Column(Float)
    feature_importance = Column(Text)  # JSON
    parameters = Column(Text)  # JSON
    is_active = Column(Boolean, default=False)


class DatabaseManager:
    """Database connection and session management."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.engine = create_engine(config.database.url, echo=config.database.echo)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    def create_tables(self) -> None:
        """Create all database tables."""
        Base.metadata.create_all(bind=self.engine)

    def get_session(self) -> Session:
        """Get database session."""
        return self.SessionLocal()

    def init_default_categories(self) -> None:
        """Initialize default categories."""
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

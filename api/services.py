"""Service layer for database operations."""

from typing import List, Optional
from sqlalchemy.orm import Session

from src.fafycat.core.database import (
    CategoryORM, 
    TransactionORM, 
    MerchantMappingORM,
    get_categories as db_get_categories,
    get_transactions as db_get_transactions
)
from api.models import (
    TransactionResponse, 
    CategoryResponse, 
    TransactionUpdate,
    CategoryCreate,
    CategoryUpdate
)


class TransactionService:
    """Service for transaction operations."""
    
    @staticmethod
    def get_transactions(
        session: Session,
        skip: int = 0,
        limit: int = 100,
        category: Optional[str] = None,
        is_reviewed: Optional[bool] = None,
        confidence_lt: Optional[float] = None
    ) -> List[TransactionResponse]:
        """Get transactions with filtering."""
        query = session.query(TransactionORM)
        
        # Apply filters
        if category:
            query = query.join(CategoryORM, TransactionORM.category_id == CategoryORM.id)
            query = query.filter(CategoryORM.name == category)
        
        if is_reviewed is not None:
            query = query.filter(TransactionORM.is_reviewed == is_reviewed)
            
        if confidence_lt is not None:
            query = query.filter(TransactionORM.confidence_score < confidence_lt)
        
        # Apply pagination
        query = query.order_by(TransactionORM.date.desc())
        query = query.offset(skip).limit(limit)
        
        transactions = query.all()
        
        # Convert to response models
        return [
            TransactionResponse(
                id=t.id,
                date=t.date,
                description=f"{t.name} - {t.purpose or ''}".strip(" - "),
                amount=t.amount,
                account="", # Will be added when we migrate account info
                predicted_category=t.predicted_category.name if t.predicted_category else None,
                actual_category=t.category.name if t.category else None,
                confidence=t.confidence_score,
                is_reviewed=t.is_reviewed,
                created_at=t.imported_at,
                updated_at=t.imported_at  # Will update when we add updated_at to TransactionORM
            )
            for t in transactions
        ]
    
    @staticmethod
    def get_pending_transactions(session: Session, limit: int = 50) -> List[TransactionResponse]:
        """Get transactions that need review."""
        return TransactionService.get_transactions(
            session=session,
            limit=limit,
            is_reviewed=False
        )
    
    @staticmethod
    def update_transaction_category(
        session: Session,
        transaction_id: str,
        update: TransactionUpdate
    ) -> Optional[TransactionResponse]:
        """Update transaction category."""
        transaction = session.query(TransactionORM).filter(
            TransactionORM.id == transaction_id
        ).first()
        
        if not transaction:
            return None
        
        # Find category by name
        category = session.query(CategoryORM).filter(
            CategoryORM.name == update.actual_category
        ).first()
        
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
            description=f"{transaction.name} - {transaction.purpose or ''}".strip(" - "),
            amount=transaction.amount,
            account="",
            predicted_category=transaction.predicted_category.name if transaction.predicted_category else None,
            actual_category=category.name,
            confidence=transaction.confidence_score,
            is_reviewed=transaction.is_reviewed,
            created_at=transaction.imported_at,
            updated_at=transaction.imported_at
        )


class CategoryService:
    """Service for category operations."""
    
    @staticmethod
    def get_categories(session: Session, include_inactive: bool = False) -> List[CategoryResponse]:
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
                updated_at=c.updated_at
            )
            for c in categories
        ]
    
    @staticmethod
    def create_category(session: Session, category: CategoryCreate) -> CategoryResponse:
        """Create a new category."""
        db_category = CategoryORM(
            name=category.name,
            type=category.type,
            budget=category.budget or 0.0
        )
        
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
            updated_at=db_category.updated_at
        )
    
    @staticmethod
    def update_category(
        session: Session,
        category_id: int,
        update: CategoryUpdate
    ) -> Optional[CategoryResponse]:
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
            updated_at=category.updated_at
        )
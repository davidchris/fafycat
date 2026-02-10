"""Rule-based merchant mapping system."""

from datetime import date, datetime
from typing import cast

from sqlalchemy.orm import Session

from ..core.database import CategoryORM, MerchantMappingORM, TransactionORM
from ..core.models import MerchantMapping
from .feature_extractor import MerchantCleaner


class MerchantMapper:
    """High-confidence merchant to category mapping."""

    def __init__(self, session: Session):
        self.session = session
        self.merchant_cleaner = MerchantCleaner()
        self._cache = {}
        self._load_mappings()

    def _load_mappings(self) -> None:
        """Load merchant mappings from database into cache."""
        mappings = self.session.query(MerchantMappingORM).all()
        self._cache = {
            mapping.merchant_pattern: {"category_id": mapping.category_id, "confidence": mapping.confidence}
            for mapping in mappings
        }

    def get_category(self, merchant_name: str) -> MerchantMapping | None:
        """Get category mapping for merchant."""
        clean_merchant = self.merchant_cleaner.clean(merchant_name)

        if not clean_merchant:
            return None

        # Exact match first
        if clean_merchant in self._cache:
            mapping_data = self._cache[clean_merchant]
            return MerchantMapping(
                merchant_pattern=clean_merchant,
                category_id=cast(int, mapping_data["category_id"]),
                confidence=cast(float, mapping_data["confidence"]),
            )

        # Partial matches for common merchants
        for pattern, mapping_data in self._cache.items():
            if self._is_partial_match(clean_merchant, str(pattern)):
                return MerchantMapping(
                    merchant_pattern=str(pattern),
                    category_id=cast(int, mapping_data["category_id"]),
                    confidence=cast(float, mapping_data["confidence"]) * 0.9,  # Slightly lower confidence
                )

        return None

    def _is_partial_match(self, merchant: str, pattern: str) -> bool:
        """Check if merchant partially matches pattern."""
        # For short patterns, require exact match
        if len(pattern) < 5:
            return False

        # Check if pattern is contained in merchant or vice versa
        merchant_words = set(merchant.split())
        pattern_words = set(pattern.split())

        # If pattern has only one word, check if it's in merchant
        if len(pattern_words) == 1:
            return any(word.startswith(list(pattern_words)[0][:4]) for word in merchant_words)

        # For multi-word patterns, check overlap
        overlap = len(merchant_words & pattern_words)
        return overlap >= min(2, len(pattern_words))

    def add_mapping(self, merchant_pattern: str, category_id: int, confidence: float = 1.0) -> None:
        """Add new merchant mapping."""
        clean_pattern = self.merchant_cleaner.clean(merchant_pattern)

        # Check if mapping already exists
        existing = (
            self.session.query(MerchantMappingORM).filter(MerchantMappingORM.merchant_pattern == clean_pattern).first()
        )

        if existing:
            # Update existing mapping
            existing.category_id = category_id
            existing.confidence = confidence
            existing.occurrence_count += 1
            existing.last_seen = date.today()
        else:
            # Create new mapping
            mapping = MerchantMappingORM(
                merchant_pattern=clean_pattern, category_id=category_id, confidence=confidence, last_seen=date.today()
            )
            self.session.add(mapping)

        self.session.commit()

        # Update cache
        self._cache[clean_pattern] = {"category_id": category_id, "confidence": confidence}

    def update_from_transactions(self, min_occurrences: int = 3) -> None:
        """Update merchant mappings from confirmed transactions."""
        from sqlalchemy import text

        # Find merchants with consistent categorization
        query = text("""
        SELECT
            t.name,
            t.category_id,
            COUNT(*) as occurrence_count,
            MAX(t.date) as last_seen
        FROM transactions t
        WHERE t.category_id IS NOT NULL
          AND t.is_reviewed = true
        GROUP BY t.name, t.category_id
        HAVING COUNT(*) >= :min_occurrences
        """)

        result = self.session.execute(query, {"min_occurrences": min_occurrences})

        for row in result:
            merchant_name, category_id, count, last_seen = row
            clean_merchant = self.merchant_cleaner.clean(merchant_name)

            if not clean_merchant:
                continue

            # Calculate confidence based on consistency
            total_for_merchant = (
                self.session.query(TransactionORM)
                .filter(TransactionORM.name == merchant_name, TransactionORM.category_id.isnot(None))
                .count()
            )

            confidence = min(0.95, count / total_for_merchant)

            # Only add high-confidence mappings
            if confidence >= 0.8:
                self.add_mapping(clean_merchant, category_id, confidence)

    def get_mapping_suggestions(self, merchant_name: str) -> list[dict]:
        """Get category suggestions for a merchant based on similar merchants."""
        clean_merchant = self.merchant_cleaner.clean(merchant_name)
        suggestions = []

        # Find similar merchants in existing mappings
        for pattern, mapping_data in self._cache.items():
            similarity = self._calculate_similarity(clean_merchant, str(pattern))
            if similarity > 0.7:
                # Get category name
                category = self.session.query(CategoryORM).filter(CategoryORM.id == mapping_data["category_id"]).first()

                if category:
                    suggestions.append(
                        {
                            "category_id": mapping_data["category_id"],
                            "category_name": category.name,
                            "similarity": similarity,
                            "confidence": mapping_data["confidence"] * similarity,
                        }
                    )

        # Sort by confidence
        suggestions.sort(key=lambda x: x["confidence"], reverse=True)
        return suggestions[:3]  # Return top 3 suggestions

    def _calculate_similarity(self, merchant1: str, merchant2: str) -> float:
        """Calculate similarity between two merchant names."""
        if not merchant1 or not merchant2:
            return 0.0

        words1 = set(merchant1.split())
        words2 = set(merchant2.split())

        if not words1 or not words2:
            return 0.0

        # Jaccard similarity
        intersection = len(words1 & words2)
        union = len(words1 | words2)

        return intersection / union if union > 0 else 0.0

    def get_all_mappings(self) -> list[MerchantMapping]:
        """Get all merchant mappings."""
        mappings = self.session.query(MerchantMappingORM).all()
        return [
            MerchantMapping(
                id=cast(int | None, mapping.id),
                merchant_pattern=cast(str, mapping.merchant_pattern),
                category_id=cast(int, mapping.category_id),
                confidence=cast(float, mapping.confidence),
                occurrence_count=cast(int, mapping.occurrence_count),
                last_seen=cast(date | None, mapping.last_seen),
                created_at=cast(datetime | None, mapping.created_at),
            )
            for mapping in mappings
        ]

    def delete_mapping(self, mapping_id: int) -> bool:
        """Delete a merchant mapping."""
        mapping = self.session.query(MerchantMappingORM).filter(MerchantMappingORM.id == mapping_id).first()

        if mapping:
            # Remove from cache
            if mapping.merchant_pattern in self._cache:
                del self._cache[mapping.merchant_pattern]

            # Delete from database
            self.session.delete(mapping)
            self.session.commit()
            return True

        return False

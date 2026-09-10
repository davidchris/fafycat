"""Rule-based merchant mapping system.

A Merchant Rule maps a cleaned merchant name to a category. Rules are derived
data: rebuilt from reviewed transactions on every training run, never edited
by hand. A rule only decides a prediction when it matches exactly and its
confidence reaches ``RULE_OVERRIDE_CONFIDENCE``.
"""

from collections import Counter, defaultdict
from datetime import date, datetime
from typing import cast

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core.database import CategoryORM, MerchantMappingORM, TransactionORM
from ..core.models import MerchantMapping
from .feature_extractor import MerchantCleaner

RULE_OVERRIDE_CONFIDENCE = 0.95
"""Minimum rule confidence for a Merchant Rule to decide a prediction."""

RULE_MIN_SHARE = 0.8
"""Minimum share of one category among a merchant's reviews to form a rule."""

RULE_MAX_CONFIDENCE = 0.98
"""Rules never claim certainty; leaves room for the reviewer to disagree."""

RULE_MIN_REVIEWS = 3
"""Reviews a merchant pattern needs before it can form a rule."""


def refresh_rule_for_pattern(session: Session, pattern: str, min_occurrences: int = RULE_MIN_REVIEWS) -> bool:
    """Recompute the Merchant Rule for a single merchant pattern and commit.

    Applies the same bar as a full rebuild (``min_occurrences`` reviews and a
    ``RULE_MIN_SHARE`` majority category), so a rule appears as soon as the
    reviews support it and disappears again once they diverge. Reads the
    stored ``merchant_pattern`` column rather than re-cleaning names, which
    keeps the work to one indexed lookup.

    Args:
        session: Open database session. Committed by this function.
        pattern: Cleaned merchant name to recompute. Empty patterns are ignored.
        min_occurrences: Minimum number of reviews required to form a rule.

    Returns:
        True if a rule exists for the pattern afterwards, False otherwise.
    """
    if not pattern:
        return False

    rows = (
        session.query(TransactionORM.category_id, func.count(TransactionORM.id), func.max(TransactionORM.date))
        .filter(
            TransactionORM.merchant_pattern == pattern,
            TransactionORM.category_id.isnot(None),
            TransactionORM.is_reviewed.is_(True),
        )
        .group_by(TransactionORM.category_id)
        .all()
    )

    counts: Counter[int] = Counter()
    last_seen: date | None = None
    for category_id, count, seen in rows:
        counts[int(category_id)] += int(count)
        seen_date = seen if isinstance(seen, date) else date.fromisoformat(str(seen)[:10])
        last_seen = seen_date if last_seen is None else max(last_seen, seen_date)

    existing = session.query(MerchantMappingORM).filter(MerchantMappingORM.merchant_pattern == pattern).first()

    total = sum(counts.values())
    category_id, top = counts.most_common(1)[0] if counts else (None, 0)
    qualifies = bool(counts) and total >= min_occurrences and top >= total * RULE_MIN_SHARE

    if not qualifies:
        if existing is not None:
            session.delete(existing)
            session.commit()
        return False

    mapping = existing or MerchantMappingORM(merchant_pattern=pattern)
    if existing is None:
        session.add(mapping)
    mapping.category_id = category_id
    mapping.confidence = min(RULE_MAX_CONFIDENCE, top / total)
    mapping.occurrence_count = total
    mapping.last_seen = last_seen
    session.commit()
    return True


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

    def reload(self) -> None:
        """Re-read the rule cache from the database.

        The categorizer is a long-lived singleton, so rules written by a
        review or a propagation are invisible to it until it reloads.
        """
        self._load_mappings()

    def refresh_pattern(self, pattern: str, min_occurrences: int = RULE_MIN_REVIEWS) -> bool:
        """Recompute the Merchant Rule for one pattern and refresh the cache.

        Args:
            pattern: Cleaned merchant name to recompute.
            min_occurrences: Minimum number of reviews required to form a rule.

        Returns:
            True if a rule exists for the pattern afterwards, False otherwise.
        """
        exists = refresh_rule_for_pattern(self.session, pattern, min_occurrences)
        self._load_mappings()
        return exists

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

    def update_from_transactions(self, min_occurrences: int = 3) -> None:
        """Rebuild all Merchant Rules from reviewed transactions.

        Groups reviews by cleaned merchant pattern. A pattern becomes a rule
        when it has at least ``min_occurrences`` reviews and one category
        holds at least ``RULE_MIN_SHARE`` of them. Rules that no longer meet
        the bar are deleted, so a fixed cleaner or changed reviews never
        leave stale rules behind.
        """
        desired = self._derive_rules(min_occurrences)

        existing = {str(m.merchant_pattern): m for m in self.session.query(MerchantMappingORM).all()}
        for pattern, mapping in existing.items():
            if pattern not in desired:
                self.session.delete(mapping)
        for pattern, (category_id, confidence, total, seen) in desired.items():
            mapping = existing.get(pattern)
            if mapping is None:
                mapping = MerchantMappingORM(merchant_pattern=pattern)
                self.session.add(mapping)
            mapping.category_id = category_id
            mapping.confidence = confidence
            mapping.occurrence_count = total
            mapping.last_seen = seen

        self.session.commit()
        self._load_mappings()

    def _derive_rules(self, min_occurrences: int) -> dict[str, tuple[int, float, int, date]]:
        """Compute the rule set: pattern -> (category_id, confidence, reviews, last_seen)."""
        rows = (
            self.session.query(
                TransactionORM.name,
                TransactionORM.category_id,
                func.count(TransactionORM.id),
                func.max(TransactionORM.date),
            )
            .filter(TransactionORM.category_id.isnot(None), TransactionORM.is_reviewed.is_(True))
            .group_by(TransactionORM.name, TransactionORM.category_id)
            .all()
        )

        per_pattern: dict[str, Counter[int]] = defaultdict(Counter)
        last_seen: dict[str, date] = {}
        for raw_name, category_id, count, seen in rows:
            pattern = self.merchant_cleaner.clean(str(raw_name))
            if not pattern:
                continue
            per_pattern[pattern][int(category_id)] += int(count)
            seen_date = seen if isinstance(seen, date) else date.fromisoformat(str(seen)[:10])
            last_seen[pattern] = max(seen_date, last_seen.get(pattern, seen_date))

        desired: dict[str, tuple[int, float, int, date]] = {}
        for pattern, counts in per_pattern.items():
            total = sum(counts.values())
            category_id, top = counts.most_common(1)[0]
            share = top / total
            if total >= min_occurrences and share >= RULE_MIN_SHARE:
                desired[pattern] = (category_id, min(RULE_MAX_CONFIDENCE, share), total, last_seen[pattern])
        return desired

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

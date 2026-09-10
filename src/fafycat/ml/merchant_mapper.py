"""Rule-based merchant mapping system.

A Merchant Rule maps a cleaned merchant name to a category. Rules are derived
data: rebuilt from reviewed transactions on every training run, never edited
by hand. In the ensemble a rule is a third weighted voter beside LightGBM and
Naive Bayes. The single-model Categorizer, the non-default fallback, still
lets a rule decide on its own at ``RULE_OVERRIDE_CONFIDENCE``.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import date, datetime
from typing import NamedTuple, cast

from sqlalchemy.orm import Session

from ..core.database import CategoryORM, MerchantMappingORM, TransactionORM
from ..core.models import MerchantMapping
from .feature_extractor import MerchantCleaner

RULE_OVERRIDE_CONFIDENCE = 0.95
"""Confidence at which a rule decides alone in the single-model Categorizer.

The ensemble ignores this bar: there a rule is a weighted voter, so every
match adds its confidence to the blend instead of replacing it.
"""

RULE_MIN_SHARE = 0.8
"""Minimum share of one category among a merchant's reviews to form a rule."""

RULE_MAX_CONFIDENCE = 0.98
"""Rules never claim certainty; leaves room for the reviewer to disagree."""

PARTIAL_MATCH_PENALTY = 0.9
"""A rule matched on shared words, not exactly, speaks with less confidence."""


class DerivedRule(NamedTuple):
    """One Merchant Rule as computed from reviewed transactions."""

    category_id: int
    confidence: float
    review_count: int
    last_seen: date


def derive_rules(reviews: Iterable[tuple[str, int, date]], min_occurrences: int = 3) -> dict[str, DerivedRule]:
    """Compute Merchant Rules from reviewed transactions.

    Pure, so the same logic serves the rebuild from the database and the
    leakage-free rule set the ensemble derives from a training split while it
    optimises weights.

    Args:
        reviews: One ``(merchant_name, category_id, date)`` per reviewed transaction.
        min_occurrences: Reviews a merchant needs before it can form a rule.

    Returns:
        Cleaned merchant pattern mapped to its rule. A pattern forms a rule only
        when it has enough reviews and one category holds at least
        ``RULE_MIN_SHARE`` of them.
    """
    cleaner = MerchantCleaner()
    per_pattern: dict[str, Counter[int]] = defaultdict(Counter)
    last_seen: dict[str, date] = {}
    for raw_name, category_id, seen in reviews:
        pattern = cleaner.clean(str(raw_name))
        if not pattern:
            continue
        per_pattern[pattern][int(category_id)] += 1
        seen_date = seen if isinstance(seen, date) else date.fromisoformat(str(seen)[:10])
        last_seen[pattern] = max(seen_date, last_seen.get(pattern, seen_date))

    rules: dict[str, DerivedRule] = {}
    for pattern, counts in per_pattern.items():
        total = sum(counts.values())
        category_id, top = counts.most_common(1)[0]
        share = top / total
        if total >= min_occurrences and share >= RULE_MIN_SHARE:
            rules[pattern] = DerivedRule(category_id, min(RULE_MAX_CONFIDENCE, share), total, last_seen[pattern])
    return rules


class MerchantRuleSet:
    """Merchant Rules held in memory, matched against raw merchant names.

    Kept apart from the database so a rule set derived from a training split
    matches merchants exactly like the stored one does.
    """

    def __init__(self, rules: dict[str, tuple[int, float]]) -> None:
        self.rules = rules
        self._cleaner = MerchantCleaner()

    @classmethod
    def from_derived(cls, derived: dict[str, DerivedRule]) -> "MerchantRuleSet":
        """Build a rule set from the output of :func:`derive_rules`."""
        return cls({pattern: (rule.category_id, rule.confidence) for pattern, rule in derived.items()})

    def get_category(self, merchant_name: str) -> MerchantMapping | None:
        """Find the rule for a merchant: exact match first, then partial.

        Args:
            merchant_name: Raw merchant name as imported.

        Returns:
            The matching rule, or None. A partial match reports its confidence
            reduced by ``PARTIAL_MATCH_PENALTY``.
        """
        clean_merchant = self._cleaner.clean(merchant_name)
        if not clean_merchant:
            return None

        exact = self.rules.get(clean_merchant)
        if exact is not None:
            return MerchantMapping(merchant_pattern=clean_merchant, category_id=exact[0], confidence=exact[1])

        for pattern, (category_id, confidence) in self.rules.items():
            if self._is_partial_match(clean_merchant, pattern):
                return MerchantMapping(
                    merchant_pattern=pattern,
                    category_id=category_id,
                    confidence=confidence * PARTIAL_MATCH_PENALTY,
                )

        return None

    @staticmethod
    def _is_partial_match(merchant: str, pattern: str) -> bool:
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


class MerchantMapper:
    """The Merchant Rules stored in the database, rebuilt from reviews."""

    def __init__(self, session: Session):
        self.session = session
        self.merchant_cleaner = MerchantCleaner()
        self.rule_set = MerchantRuleSet({})
        self._load_mappings()

    def _load_mappings(self) -> None:
        """Load the stored Merchant Rules into memory."""
        self.rule_set = MerchantRuleSet(
            {
                str(mapping.merchant_pattern): (cast(int, mapping.category_id), cast(float, mapping.confidence))
                for mapping in self.session.query(MerchantMappingORM).all()
            }
        )

    def get_category(self, merchant_name: str) -> MerchantMapping | None:
        """Get the Merchant Rule matching this merchant, if any."""
        return self.rule_set.get_category(merchant_name)

    def update_from_transactions(self, min_occurrences: int = 3) -> None:
        """Rebuild all Merchant Rules from reviewed transactions.

        Groups reviews by cleaned merchant pattern. A pattern becomes a rule
        when it has at least ``min_occurrences`` reviews and one category
        holds at least ``RULE_MIN_SHARE`` of them. Rules that no longer meet
        the bar are deleted, so a fixed cleaner or changed reviews never
        leave stale rules behind.
        """
        desired = derive_rules(self.reviewed_transactions(), min_occurrences)

        existing = {str(m.merchant_pattern): m for m in self.session.query(MerchantMappingORM).all()}
        for pattern, mapping in existing.items():
            if pattern not in desired:
                self.session.delete(mapping)
        for pattern, rule in desired.items():
            mapping = existing.get(pattern)
            if mapping is None:
                mapping = MerchantMappingORM(merchant_pattern=pattern)
                self.session.add(mapping)
            mapping.category_id = rule.category_id
            mapping.confidence = rule.confidence
            mapping.occurrence_count = rule.review_count
            mapping.last_seen = rule.last_seen

        self.session.commit()
        self._load_mappings()

    def reviewed_transactions(self) -> list[tuple[str, int, date]]:
        """Every reviewed transaction as ``(merchant_name, category_id, date)``, ready for :func:`derive_rules`."""
        rows = (
            self.session.query(TransactionORM.name, TransactionORM.category_id, TransactionORM.date)
            .filter(TransactionORM.category_id.isnot(None), TransactionORM.is_reviewed.is_(True))
            .all()
        )
        return [(str(name), int(cast(int, category_id)), cast(date, seen)) for name, category_id, seen in rows]

    def get_mapping_suggestions(self, merchant_name: str) -> list[dict]:
        """Get category suggestions for a merchant based on similar merchants."""
        clean_merchant = self.merchant_cleaner.clean(merchant_name)
        suggestions = []

        # Find similar merchants in existing mappings
        for pattern, (category_id, confidence) in self.rule_set.rules.items():
            similarity = self._calculate_similarity(clean_merchant, pattern)
            if similarity > 0.7:
                # Get category name
                category = self.session.query(CategoryORM).filter(CategoryORM.id == category_id).first()

                if category:
                    suggestions.append(
                        {
                            "category_id": category_id,
                            "category_name": category.name,
                            "similarity": similarity,
                            "confidence": confidence * similarity,
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
            self.rule_set.rules.pop(str(mapping.merchant_pattern), None)

            # Delete from database
            self.session.delete(mapping)
            self.session.commit()
            return True

        return False

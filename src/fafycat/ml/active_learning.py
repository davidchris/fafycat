"""Active learning for efficient human feedback."""

import random
from typing import Any, cast

from sqlalchemy.orm import Session

from ..core.database import TransactionORM
from ..core.models import TransactionPrediction


class ActiveLearningSelector:
    """Select transactions for review based on uncertainty and diversity."""

    def __init__(self, session: Session):
        self.session = session

    def select_for_review(
        self, predictions: list[TransactionPrediction], max_items: int = 20, strategy: str = "uncertainty"
    ) -> list[str]:
        """Select transaction IDs that need review.

        Args:
            predictions: List of transaction predictions
            max_items: Maximum number of items to select
            strategy: Selection strategy ('uncertainty', 'diversity', 'mixed')
        """
        if strategy == "uncertainty":
            return self._uncertainty_sampling(predictions, max_items)
        if strategy == "diversity":
            return self._diversity_sampling(predictions, max_items)
        if strategy == "mixed":
            return self._mixed_sampling(predictions, max_items)
        raise ValueError(f"Unknown strategy: {strategy}")

    def _uncertainty_sampling(self, predictions: list[TransactionPrediction], max_items: int) -> list[str]:
        """Select based on prediction uncertainty (low confidence)."""
        # Sort by confidence (ascending - lowest confidence first)
        sorted_predictions = sorted(predictions, key=lambda p: p.confidence_score)

        # Also include some high-confidence items for validation
        review_ids = []

        # 70% low confidence (uncertainty)
        n_uncertain = int(max_items * 0.7)
        review_ids.extend([p.transaction_id for p in sorted_predictions[:n_uncertain]])

        # 20% medium confidence (0.7-0.9)
        medium_conf = [p for p in predictions if 0.7 <= p.confidence_score <= 0.9]
        n_medium = int(max_items * 0.2)
        if medium_conf:
            sample_size = min(n_medium, len(medium_conf))
            review_ids.extend([p.transaction_id for p in random.sample(medium_conf, sample_size)])

        # 10% high confidence for quality check
        high_conf = [p for p in predictions if p.confidence_score > 0.9]
        n_high = max_items - len(review_ids)
        if high_conf and n_high > 0:
            sample_size = min(n_high, len(high_conf))
            review_ids.extend([p.transaction_id for p in random.sample(high_conf, sample_size)])

        return review_ids[:max_items]

    def _diversity_sampling(self, predictions: list[TransactionPrediction], max_items: int) -> list[str]:
        """Select diverse examples across different categories and features."""
        # Group by predicted category
        by_category = {}
        for pred in predictions:
            if pred.predicted_category_id not in by_category:
                by_category[pred.predicted_category_id] = []
            by_category[pred.predicted_category_id].append(pred)

        # Select diverse examples from each category
        review_ids = []
        categories = list(by_category.keys())
        items_per_category = max(1, max_items // len(categories))

        for category_id in categories:
            category_predictions = by_category[category_id]

            # Sort by confidence to get a mix
            category_predictions.sort(key=lambda p: p.confidence_score)

            # Take from different confidence levels
            n_to_take = min(items_per_category, len(category_predictions))
            step = max(1, len(category_predictions) // n_to_take)

            selected = category_predictions[::step][:n_to_take]
            review_ids.extend([p.transaction_id for p in selected])

        # Fill remaining slots with random selections
        remaining = max_items - len(review_ids)
        if remaining > 0:
            remaining_predictions = [p for p in predictions if p.transaction_id not in review_ids]
            if remaining_predictions:
                additional = random.sample(remaining_predictions, min(remaining, len(remaining_predictions)))
                review_ids.extend([p.transaction_id for p in additional])

        return review_ids[:max_items]

    def _mixed_sampling(self, predictions: list[TransactionPrediction], max_items: int) -> list[str]:
        """Mixed strategy combining uncertainty and diversity."""
        # 60% uncertainty sampling
        n_uncertainty = int(max_items * 0.6)
        uncertainty_ids = self._uncertainty_sampling(predictions, n_uncertainty)

        # 40% diversity sampling from remaining
        remaining_predictions = [p for p in predictions if p.transaction_id not in uncertainty_ids]
        n_diversity = max_items - len(uncertainty_ids)
        diversity_ids = self._diversity_sampling(remaining_predictions, n_diversity)

        return uncertainty_ids + diversity_ids

    def get_review_priority_score(self, prediction: TransactionPrediction) -> float:
        """Calculate priority score for review."""
        # Base score from uncertainty (1 - confidence)
        uncertainty_score = 1 - prediction.confidence_score

        # Get transaction details for additional scoring
        transaction = self.session.query(TransactionORM).filter(TransactionORM.id == prediction.transaction_id).first()

        if not transaction:
            return uncertainty_score

        # Boost score for high-value transactions
        amount_score = min(1.0, abs(cast(float, transaction.amount)) / 1000.0)

        # Boost score for new merchants
        merchant_novelty_score = self._get_merchant_novelty_score(str(transaction.name))

        # Combine scores
        priority_score = uncertainty_score * 0.6 + amount_score * 0.2 + merchant_novelty_score * 0.2

        return min(1.0, priority_score)

    def _get_merchant_novelty_score(self, merchant_name: str) -> float:
        """Calculate novelty score for merchant (higher for new/rare merchants)."""
        # Count how many transactions we have from this merchant
        count = self.session.query(TransactionORM).filter(TransactionORM.name.like(f"%{merchant_name[:10]}%")).count()

        # Novelty decreases with frequency
        if count == 0:
            return 1.0  # Completely new
        if count <= 2:
            return 0.8  # Very rare
        if count <= 5:
            return 0.6  # Rare
        if count <= 10:
            return 0.4  # Occasional
        return 0.2  # Common

    def update_selection_strategy(self, feedback_history: list[dict[str, Any]]) -> str:
        """Adapt selection strategy based on feedback history."""
        if len(feedback_history) < 10:
            return "uncertainty"  # Start with uncertainty sampling

        # Analyze recent feedback
        recent_feedback = feedback_history[-20:]  # Last 20 reviews

        # Calculate correction rate by confidence level
        high_conf_corrections = sum(
            1 for f in recent_feedback if f.get("original_confidence", 0) > 0.9 and f.get("was_corrected", False)
        )

        total_high_conf = sum(1 for f in recent_feedback if f.get("original_confidence", 0) > 0.9)

        # If high-confidence predictions are often wrong, use more uncertainty sampling
        if total_high_conf > 0 and (high_conf_corrections / total_high_conf) > 0.2:
            return "uncertainty"

        # If we're getting good accuracy, switch to diversity for better coverage
        overall_correction_rate = sum(1 for f in recent_feedback if f.get("was_corrected", False)) / len(
            recent_feedback
        )

        if overall_correction_rate < 0.15:  # Less than 15% corrections
            return "diversity"

        return "mixed"

    def get_batch_statistics(self, predictions: list[TransactionPrediction]) -> dict[str, Any]:
        """Get statistics about a batch of predictions for review planning."""
        if not predictions:
            return {}

        confidences = [p.confidence_score for p in predictions]

        # Confidence distribution
        high_conf = sum(1 for c in confidences if c > 0.9)
        medium_conf = sum(1 for c in confidences if 0.7 <= c <= 0.9)
        low_conf = sum(1 for c in confidences if c < 0.7)

        # Category distribution
        category_counts = {}
        for pred in predictions:
            cat_id = pred.predicted_category_id
            category_counts[cat_id] = category_counts.get(cat_id, 0) + 1

        return {
            "total_predictions": len(predictions),
            "confidence_distribution": {"high": high_conf, "medium": medium_conf, "low": low_conf},
            "average_confidence": sum(confidences) / len(confidences),
            "category_distribution": category_counts,
            "recommended_review_count": min(20, low_conf + medium_conf // 2),
        }

"""Fuzzy duplicate detection for card-settlement vs. account-direct transaction pairs.

Some banks export the same card purchase twice: once as the direct account
booking (with the real purchase date) and again as a delayed card-settlement
line (e.g. "VISA <merchant>" with a settlement date several days later). The
two rows differ in date, name, and purpose, so the exact-hash dedup in
``TransactionInput.generate_id()`` never catches them.

This module implements a fuzzy pre-insert check: a candidate is considered a
duplicate of an existing transaction when the amount and currency are
identical, the dates are within a small window, exactly one of the two rows
looks like a card settlement, and the normalized merchant tokens overlap
strongly. Requiring exactly one settlement-like side means neither two direct
bookings nor two settlement lines (each a real purchase) are ever collapsed.
"""

import re
from datetime import timedelta

from sqlalchemy.orm import Session

from ..core.database import TransactionORM
from ..core.models import TransactionInput

DATE_WINDOW_DAYS = 10
OVERLAP_THRESHOLD = 0.6
_AMOUNT_TOLERANCE = 0.005

# Tokens that carry no merchant identity: booking boilerplate, card metadata,
# currency/date fragments.
_NOISE_TOKENS = {
    "kaufumsatz",
    "datum",
    "visa",
    "card",
    "eur",
    "nr",
    "arn",
    "de",
    "girocard",
    "lastschrift",
}

# Card-settlement fingerprints: masked card number ("Nr xxxx 1022" / "Nr. xxxx 1022")
# or a back-reference to the purchase day+month ("Kaufumsatz 01.04" — but not a full
# date like "Kaufumsatz 01.04.2026", which direct bookings may carry).
_MASKED_CARD_RE = re.compile(r"\bnr\.?\s+x{2,}\s*\d{4}\b", re.IGNORECASE)
_SETTLEMENT_REF_RE = re.compile(r"\bkaufumsatz\s+\d{2}\.\d{2}(?!\.?\d)", re.IGNORECASE)

_TOKEN_RE = re.compile(r"[a-zäöüß]+", re.IGNORECASE)


def normalize_merchant_tokens(name: str, purpose: str = "") -> frozenset[str]:
    """Extract normalized merchant identity tokens from a transaction.

    Uses the name field primarily; falls back to the purpose field when the
    name yields no usable tokens. Strips card/booking boilerplate, masked-card
    ``xxxx`` fragments, numbers, and short fragments.
    """
    for source in (name, purpose):
        tokens = {
            token.lower()
            for token in _TOKEN_RE.findall(source)
            if len(token) >= 3 and token.lower() not in _NOISE_TOKENS and set(token.lower()) != {"x"}
        }
        if tokens:
            return frozenset(tokens)
    return frozenset()


def is_settlement_like(name: str, purpose: str) -> bool:
    """Check whether a row looks like a delayed card-settlement booking."""
    if name.lower().startswith("visa "):
        return True
    return bool(_MASKED_CARD_RE.search(purpose) or _SETTLEMENT_REF_RE.search(purpose))


def _token_overlap(a: frozenset[str], b: frozenset[str]) -> float:
    """Overlap coefficient: |a ∩ b| / min(|a|, |b|).

    Preferred over Jaccard here because the settlement row's merchant tokens
    are typically a subset of the direct row's (e.g. "VISA IKEA" vs.
    "IKEA Berlin"), which Jaccard under-scores.
    """
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def find_fuzzy_duplicate(session: Session, txn: TransactionInput) -> TransactionORM | None:
    """Find an existing transaction that is a settlement-vs-direct duplicate of ``txn``.

    Returns the matching row, or None. Besides an exact content match, only
    pairs where exactly one side is settlement-like are considered, so
    repeated legitimate purchases at the same merchant within the date window
    are not collapsed.
    """
    window_start = txn.date - timedelta(days=DATE_WINDOW_DAYS)
    window_end = txn.date + timedelta(days=DATE_WINDOW_DAYS)

    candidates = (
        session.query(TransactionORM)
        .filter(
            TransactionORM.amount >= txn.amount - _AMOUNT_TOLERANCE,
            TransactionORM.amount <= txn.amount + _AMOUNT_TOLERANCE,
            TransactionORM.currency == txn.currency,
            TransactionORM.date >= window_start,
            TransactionORM.date <= window_end,
        )
        .all()
    )
    if not candidates:
        return None

    txn_tokens = normalize_merchant_tokens(txn.name, txn.purpose)
    txn_settlement = is_settlement_like(txn.name, txn.purpose)

    for candidate in candidates:
        candidate_name = str(candidate.name)
        candidate_purpose = str(candidate.purpose or "")
        # Exact content match: catches re-imports of a direct row whose stored
        # duplicate was field-upgraded (its id still hashes the old settlement
        # fields, so the exact-id check upstream misses it).
        if candidate.date == txn.date and candidate_name == txn.name and candidate_purpose == txn.purpose:
            return candidate
        if is_settlement_like(candidate_name, candidate_purpose) == txn_settlement:
            continue
        candidate_tokens = normalize_merchant_tokens(candidate_name, candidate_purpose)
        if _token_overlap(txn_tokens, candidate_tokens) > OVERLAP_THRESHOLD:
            return candidate
    return None


def keep_preferred_fields(existing: TransactionORM, txn: TransactionInput) -> None:
    """Adopt the account-direct row's fields when it arrives after its settlement line.

    The direct booking carries the real purchase date and clean merchant name.
    When the settlement row was imported first (e.g. card CSV before account
    CSV), upgrade the stored row's descriptive fields in place; id, category,
    and review state are preserved.
    """
    if is_settlement_like(txn.name, txn.purpose):
        return
    if not is_settlement_like(str(existing.name), str(existing.purpose or "")):
        return
    existing.date = txn.date
    existing.value_date = txn.value_date
    existing.name = txn.name
    existing.purpose = txn.purpose


def sort_direct_rows_first(transactions: list[TransactionInput]) -> list[TransactionInput]:
    """Sort a batch so account-direct rows are inserted before settlement rows.

    Stable sort: CSV order is preserved within each group.
    """
    return sorted(transactions, key=lambda t: is_settlement_like(t.name, t.purpose))

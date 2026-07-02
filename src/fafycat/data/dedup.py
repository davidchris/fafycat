"""Fuzzy duplicate detection for card-settlement vs. account-direct transaction pairs.

Some banks export the same card purchase twice: once as the direct account
booking (with the real purchase date) and again as a delayed card-settlement
line (e.g. "VISA <merchant>" with a settlement date several days later). The
two rows differ in date, name, and purpose, so the exact-hash dedup in
``TransactionInput.generate_id()`` never catches them.

This module implements a fuzzy pre-insert check: a candidate is considered a
duplicate of an existing transaction when the amount is identical, the dates
are within a small window, at least one of the two rows looks like a card
settlement, and the normalized merchant token sets overlap strongly.
"""

import re
from datetime import date, timedelta

from sqlalchemy.orm import Session

from ..core.database import TransactionORM
from ..core.models import TransactionInput

DATE_WINDOW_DAYS = 10
JACCARD_THRESHOLD = 0.6
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

# Card-settlement fingerprints: masked card number ("Nr xxxx 1022") or a
# back-reference to the purchase date ("Kaufumsatz 01.04").
_MASKED_CARD_RE = re.compile(r"\bnr\s+x{2,}\s*\d{4}\b", re.IGNORECASE)
_SETTLEMENT_REF_RE = re.compile(r"\bkaufumsatz\s+\d{2}\.\d{2}\b", re.IGNORECASE)

_TOKEN_RE = re.compile(r"[a-zäöüß]+", re.IGNORECASE)


def normalize_merchant_tokens(name: str, purpose: str = "") -> frozenset[str]:
    """Extract normalized merchant identity tokens from a transaction.

    Uses the name field primarily; falls back to the purpose field when the
    name yields no usable tokens. Strips card/booking boilerplate, numbers,
    and short fragments.
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


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def find_fuzzy_duplicate(session: Session, txn: TransactionInput) -> TransactionORM | None:
    """Find an existing transaction that is a settlement-vs-direct duplicate of ``txn``.

    Returns the matching row, or None. Only pairs where at least one side is
    settlement-like are considered, so two legitimate identical purchases at
    the same merchant within the date window are not collapsed.
    """
    window_start = txn.date - timedelta(days=DATE_WINDOW_DAYS)
    window_end = txn.date + timedelta(days=DATE_WINDOW_DAYS)

    candidates = (
        session.query(TransactionORM)
        .filter(
            TransactionORM.amount >= txn.amount - _AMOUNT_TOLERANCE,
            TransactionORM.amount <= txn.amount + _AMOUNT_TOLERANCE,
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
        if not txn_settlement and not is_settlement_like(candidate_name, candidate_purpose):
            continue
        candidate_tokens = normalize_merchant_tokens(candidate_name, candidate_purpose)
        if _jaccard(txn_tokens, candidate_tokens) > JACCARD_THRESHOLD:
            return candidate
    return None


def _sort_key(txn: TransactionInput) -> tuple[date, int]:
    """Order transactions so account-direct rows are inserted before settlements.

    The direct booking carries the real purchase date (earlier); among
    same-date rows, non-settlement rows come first.
    """
    return (txn.date, 1 if is_settlement_like(txn.name, txn.purpose) else 0)


def sort_direct_rows_first(transactions: list[TransactionInput]) -> list[TransactionInput]:
    """Sort a batch so the preferred (account-direct, earlier) row of each pair wins dedup."""
    return sorted(transactions, key=_sort_key)

"""Backfill of the ``merchant_pattern`` column on transactions.

``merchant_pattern`` holds the cleaned merchant name (see
:class:`~fafycat.ml.feature_extractor.MerchantCleaner`). New transactions get
it at import time; databases created before the column existed need it filled
in once. This module lives outside ``core`` because ``core`` must not import
from ``ml``.
"""

from sqlalchemy import update
from sqlalchemy.orm import Session

from ..core.database import TransactionORM
from ..ml.feature_extractor import MerchantCleaner

BATCH_SIZE = 1000
"""Rows updated per flush; keeps the statement list bounded on large imports."""


def backfill_merchant_patterns(session: Session, batch_size: int = BATCH_SIZE) -> int:
    """Fill ``merchant_pattern`` on every transaction that lacks one.

    Only rows where the column is NULL are touched, so repeated calls are
    idempotent and cost one indexed scan once the backfill is done. A name
    that cleans to nothing is stored as an empty string rather than left NULL,
    which keeps it out of later passes.

    Args:
        session: Open database session. Committed by this function.
        batch_size: Number of rows to update per flush.

    Returns:
        The number of rows that were given a pattern.
    """
    cleaner = MerchantCleaner()
    updated = 0

    while True:
        rows = (
            session.query(TransactionORM.id, TransactionORM.name)
            .filter(TransactionORM.merchant_pattern.is_(None))
            .limit(batch_size)
            .all()
        )
        if not rows:
            break

        session.execute(
            update(TransactionORM),
            [{"id": row_id, "merchant_pattern": cleaner.clean(str(name or ""))} for row_id, name in rows],
        )
        session.commit()
        updated += len(rows)
        if len(rows) < batch_size:
            break

    return updated

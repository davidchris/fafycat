"""Confidence cell of a transaction row: zero is a low score, a missing score is N/A."""

import re
from datetime import date, datetime

import pytest

from fafycat.api.models import TransactionResponse
from fafycat.web.components.transaction_table import render_row


def _confidence_cell(confidence: float | None) -> tuple[str, str]:
    tx = TransactionResponse(
        id="t1",
        date=date(2024, 1, 1),
        description="Shop",
        amount=-1.0,
        account="",
        confidence=confidence,
        created_at=datetime(2024, 1, 1),
        updated_at=datetime(2024, 1, 1),
    )
    cells = re.findall(r'<td class="([^"]*)">([^<]*)</td>', render_row(tx, []))
    classes, text = cells[-1]
    return classes.split()[0], text


@pytest.mark.parametrize(
    ("confidence", "expected"),
    [
        (None, ("text-secondary", "N/A")),
        (0.0, ("text-spending", "0.0%")),
        (0.45, ("text-spending", "45.0%")),
        (0.75, ("text-income", "75.0%")),
        (0.95, ("text-success", "95.0%")),
    ],
)
def test_confidence_cell(confidence, expected):
    assert _confidence_cell(confidence) == expected

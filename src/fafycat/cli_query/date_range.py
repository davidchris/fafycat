"""Pure date-range resolution for CLI query commands.

Resolves the user-provided combination of explicit ``--start``/``--end`` and
sugar flags (``--month``, ``--year``, ``--this-month``, ``--last-month``,
``--ytd``, ``--last-n-months``) into a concrete ``(start, end)`` date pair.

Pure function: no DB, no filesystem, no clock unless ``today`` is omitted.
"""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date
from typing import Any

from dateutil.relativedelta import relativedelta

_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def resolve_date_range(args: Any, today: date | None = None) -> tuple[date, date]:
    """Return the ``(start, end)`` date pair implied by ``args``.

    Args:
        args: Object with optional attributes ``start``, ``end``, ``month``,
            ``year``, ``this_month``, ``last_month``, ``ytd``, ``last_n_months``.
        today: Override for "current date". Defaults to ``date.today()``.

    Raises:
        ValueError: If inputs are missing, mutually exclusive flags collide,
            or values are malformed.
    """
    today = today or date.today()

    start = getattr(args, "start", None)
    end = getattr(args, "end", None)
    active = _collect_sugar(args)

    if active and (start is not None or end is not None):
        raise ValueError("date sugar flags are mutually exclusive with --start/--end")
    if len(active) > 1:
        names = ", ".join(name for name, _ in active)
        raise ValueError(f"only one date-range flag allowed; got: {names}")

    if start is not None or end is not None:
        return _resolve_explicit(start, end)
    if not active:
        raise ValueError("a date range is required")

    name, value = active[0]
    return _DISPATCH[name](value, today)


def _collect_sugar(args: Any) -> list[tuple[str, Any]]:
    sugar: list[tuple[str, Any]] = []
    if (m := getattr(args, "month", None)) is not None:
        sugar.append(("month", m))
    if (y := getattr(args, "year", None)) is not None:
        sugar.append(("year", y))
    if getattr(args, "this_month", False):
        sugar.append(("this-month", True))
    if getattr(args, "last_month", False):
        sugar.append(("last-month", True))
    if getattr(args, "ytd", False):
        sugar.append(("ytd", True))
    if (n := getattr(args, "last_n_months", None)) is not None:
        sugar.append(("last-n-months", n))
    return sugar


def _resolve_explicit(start: date | None, end: date | None) -> tuple[date, date]:
    if start is None or end is None:
        raise ValueError("--start and --end must be supplied together")
    if start > end:
        raise ValueError(f"--start ({start}) is after --end ({end})")
    return start, end


def _resolve_last_n_months(value: Any, today: date) -> tuple[date, date]:
    n = int(value)
    if n <= 0:
        raise ValueError("--last-n-months must be a positive integer")
    return today - relativedelta(months=n), today


_DISPATCH: dict[str, Any] = {
    "month": lambda v, _today: _resolve_month(v),
    "year": lambda v, _today: _resolve_year(int(v)),
    "this-month": lambda _v, today: _resolve_month_of(today),
    "last-month": lambda _v, today: _resolve_month_of(today - relativedelta(months=1)),
    "ytd": lambda _v, today: (date(today.year, 1, 1), today),
    "last-n-months": _resolve_last_n_months,
}


def _resolve_month(value: str) -> tuple[date, date]:
    match = _MONTH_RE.match(value)
    if not match:
        raise ValueError(f"--month must be YYYY-MM; got: {value!r}")
    year = int(match.group(1))
    month = int(match.group(2))
    if not 1 <= month <= 12:
        raise ValueError(f"--month has invalid month number: {value!r}")
    return _resolve_month_of(date(year, month, 1))


def _resolve_month_of(d: date) -> tuple[date, date]:
    last_day = monthrange(d.year, d.month)[1]
    return date(d.year, d.month, 1), date(d.year, d.month, last_day)


def _resolve_year(year: int) -> tuple[date, date]:
    return date(year, 1, 1), date(year, 12, 31)

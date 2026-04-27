"""Tests for the CLI date-range resolver (pure function)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from fafycat.cli_query.date_range import resolve_date_range


def _ns(**kwargs) -> SimpleNamespace:
    """Build a default args-like namespace; override by kwargs."""
    defaults = {
        "start": None,
        "end": None,
        "month": None,
        "year": None,
        "this_month": False,
        "last_month": False,
        "ytd": False,
        "last_n_months": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestExplicitStartEnd:
    def test_explicit_start_end(self) -> None:
        args = _ns(start=date(2024, 3, 1), end=date(2024, 3, 31))
        assert resolve_date_range(args) == (date(2024, 3, 1), date(2024, 3, 31))

    def test_only_start_raises(self) -> None:
        with pytest.raises(ValueError, match="--start and --end"):
            resolve_date_range(_ns(start=date(2024, 1, 1)))

    def test_only_end_raises(self) -> None:
        with pytest.raises(ValueError, match="--start and --end"):
            resolve_date_range(_ns(end=date(2024, 1, 1)))

    def test_start_after_end_raises(self) -> None:
        with pytest.raises(ValueError, match="after"):
            resolve_date_range(_ns(start=date(2024, 6, 1), end=date(2024, 1, 1)))


class TestMonthSugar:
    def test_month_basic(self) -> None:
        args = _ns(month="2024-03")
        assert resolve_date_range(args) == (date(2024, 3, 1), date(2024, 3, 31))

    def test_month_february_leap(self) -> None:
        args = _ns(month="2024-02")
        assert resolve_date_range(args) == (date(2024, 2, 1), date(2024, 2, 29))

    def test_month_february_non_leap(self) -> None:
        args = _ns(month="2023-02")
        assert resolve_date_range(args) == (date(2023, 2, 1), date(2023, 2, 28))

    def test_month_december(self) -> None:
        args = _ns(month="2024-12")
        assert resolve_date_range(args) == (date(2024, 12, 1), date(2024, 12, 31))

    def test_month_invalid_format(self) -> None:
        with pytest.raises(ValueError, match="YYYY-MM"):
            resolve_date_range(_ns(month="2024/03"))

    def test_month_invalid_month_number(self) -> None:
        with pytest.raises(ValueError):
            resolve_date_range(_ns(month="2024-13"))


class TestYearSugar:
    def test_year_basic(self) -> None:
        args = _ns(year=2024)
        assert resolve_date_range(args) == (date(2024, 1, 1), date(2024, 12, 31))

    def test_year_leap_unaffected(self) -> None:
        args = _ns(year=2020)
        assert resolve_date_range(args) == (date(2020, 1, 1), date(2020, 12, 31))


class TestThisMonth:
    def test_this_month_mid(self) -> None:
        args = _ns(this_month=True)
        result = resolve_date_range(args, today=date(2026, 4, 27))
        assert result == (date(2026, 4, 1), date(2026, 4, 30))

    def test_this_month_first_day(self) -> None:
        args = _ns(this_month=True)
        result = resolve_date_range(args, today=date(2026, 1, 1))
        assert result == (date(2026, 1, 1), date(2026, 1, 31))

    def test_this_month_last_day(self) -> None:
        args = _ns(this_month=True)
        result = resolve_date_range(args, today=date(2024, 2, 29))
        assert result == (date(2024, 2, 1), date(2024, 2, 29))


class TestLastMonth:
    def test_last_month_mid_year(self) -> None:
        args = _ns(last_month=True)
        result = resolve_date_range(args, today=date(2026, 4, 27))
        assert result == (date(2026, 3, 1), date(2026, 3, 31))

    def test_last_month_january_crosses_year(self) -> None:
        args = _ns(last_month=True)
        result = resolve_date_range(args, today=date(2026, 1, 15))
        assert result == (date(2025, 12, 1), date(2025, 12, 31))

    def test_last_month_after_march_to_february_leap(self) -> None:
        args = _ns(last_month=True)
        result = resolve_date_range(args, today=date(2024, 3, 10))
        assert result == (date(2024, 2, 1), date(2024, 2, 29))


class TestYtd:
    def test_ytd_basic(self) -> None:
        args = _ns(ytd=True)
        result = resolve_date_range(args, today=date(2026, 4, 27))
        assert result == (date(2026, 1, 1), date(2026, 4, 27))

    def test_ytd_jan_first(self) -> None:
        args = _ns(ytd=True)
        result = resolve_date_range(args, today=date(2026, 1, 1))
        assert result == (date(2026, 1, 1), date(2026, 1, 1))


class TestLastNMonths:
    def test_last_n_months_three(self) -> None:
        args = _ns(last_n_months=3)
        result = resolve_date_range(args, today=date(2026, 4, 27))
        assert result == (date(2026, 1, 27), date(2026, 4, 27))

    def test_last_n_months_crosses_year_boundary(self) -> None:
        args = _ns(last_n_months=6)
        result = resolve_date_range(args, today=date(2026, 3, 15))
        assert result == (date(2025, 9, 15), date(2026, 3, 15))

    def test_last_n_months_one(self) -> None:
        args = _ns(last_n_months=1)
        result = resolve_date_range(args, today=date(2026, 4, 27))
        assert result == (date(2026, 3, 27), date(2026, 4, 27))

    def test_last_n_months_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            resolve_date_range(_ns(last_n_months=0))

    def test_last_n_months_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            resolve_date_range(_ns(last_n_months=-1))


class TestMutualExclusion:
    def test_sugar_with_start_end_raises(self) -> None:
        args = _ns(this_month=True, start=date(2024, 1, 1), end=date(2024, 1, 31))
        with pytest.raises(ValueError, match="mutually exclusive"):
            resolve_date_range(args)

    def test_two_sugars_raise(self) -> None:
        args = _ns(this_month=True, last_month=True)
        with pytest.raises(ValueError, match="only one"):
            resolve_date_range(args)

    def test_month_and_year_raise(self) -> None:
        args = _ns(month="2024-03", year=2024)
        with pytest.raises(ValueError, match="only one"):
            resolve_date_range(args)


class TestNoInput:
    def test_no_flags_raises(self) -> None:
        with pytest.raises(ValueError, match="required"):
            resolve_date_range(_ns())

from __future__ import annotations

from datetime import date, datetime

import polars as pl
import pytest

from aht_pipeline import periods


def utc(*stamps: str) -> pl.Series:
    return pl.Series(list(stamps)).str.to_datetime(time_zone="UTC")


def test_days_and_hours_are_cut_in_cdmx_time():
    s = utc("2026-08-14T05:59:00Z", "2026-08-14T06:00:00Z", "2026-08-15T05:30:00Z")
    out = pl.select(
        periods.business_date(pl.lit(s)).alias("day"),
        periods.business_hour(pl.lit(s)).alias("hour"),
    )
    # CDMX is UTC-6: 23:59 on the 13th, 00:00 on the 14th, 23:30 on the 14th
    assert out["day"].to_list() == [
        date(2026, 8, 13),
        date(2026, 8, 14),
        date(2026, 8, 14),
    ]
    assert out["hour"].to_list() == [23, 0, 23]


def test_a_naive_datetime_is_rejected():
    naive = pl.Series([datetime(2026, 8, 14, 3)])
    with pytest.raises(TypeError, match="UTC Datetime"):
        pl.select(periods.business_date(pl.lit(naive)))


def test_windows_mid_month():
    w = periods.windows(date(2026, 8, 14))
    assert (w["today"].start, w["today"].end) == (date(2026, 8, 14),) * 2
    assert (w["yesterday"].start, w["yesterday"].end) == (date(2026, 8, 13),) * 2
    assert (w["mtd"].start, w["mtd"].end) == (date(2026, 8, 1), date(2026, 8, 14))
    assert (w["before_today"].start, w["before_today"].end) == (
        date(2026, 8, 1),
        date(2026, 8, 13),
    )


def test_on_the_first_yesterday_is_last_month_and_before_today_is_empty():
    w = periods.windows(date(2026, 9, 1))
    assert w["yesterday"].start == date(2026, 8, 31)
    assert (w["mtd"].start, w["mtd"].end) == (date(2026, 9, 1),) * 2
    days = pl.Series([date(2026, 8, 31), date(2026, 9, 1)])
    inside = pl.select(periods.in_window(pl.lit(days), w["before_today"])).to_series()
    assert not inside.any()

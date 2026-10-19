from __future__ import annotations

from datetime import date, datetime

import polars as pl
import pytest

from nps_pipeline import periods


def test_business_date_cuts_days_in_cdmx_time():
    utc = pl.Series(
        ["2026-08-14T05:59:00Z", "2026-08-14T06:00:00Z", "2026-08-15T05:30:00Z"]
    ).str.to_datetime(time_zone="UTC")
    days = pl.select(periods.business_date(pl.lit(utc))).to_series().to_list()
    # CDMX is UTC-6: 23:59 on the 13th, 00:00 on the 14th, 23:30 on the 14th
    assert days == [date(2026, 8, 13), date(2026, 8, 14), date(2026, 8, 14)]


def test_business_date_rejects_a_naive_datetime():
    naive = pl.Series([datetime(2026, 8, 14, 3)])
    with pytest.raises(TypeError, match="UTC Datetime"):
        pl.select(periods.business_date(pl.lit(naive)))


def test_windows_for_the_demo_day():
    w = periods.windows(date(2026, 8, 14))  # Friday
    assert (w["today"].start, w["today"].end) == (date(2026, 8, 14), date(2026, 8, 14))
    assert (w["yesterday"].start, w["yesterday"].end) == (date(2026, 8, 13),) * 2
    assert (w["wtd"].start, w["wtd"].end) == (date(2026, 8, 10), date(2026, 8, 14))
    assert (w["mtd"].start, w["mtd"].end) == (date(2026, 8, 1), date(2026, 8, 14))


def test_prior_wtd_is_the_same_days_of_the_week_before():
    w = periods.windows(date(2026, 8, 14))
    assert (w["prior_wtd"].start, w["prior_wtd"].end) == (
        date(2026, 8, 3),
        date(2026, 8, 7),
    )


def test_week_to_date_on_the_week_start_is_one_day():
    w = periods.windows(date(2026, 8, 10))  # Monday
    assert w["wtd"].start == w["wtd"].end == date(2026, 8, 10)


@pytest.mark.parametrize(
    ("as_of", "wtd_start", "mtd_start"),
    [
        (date(2026, 8, 16), date(2026, 8, 10), date(2026, 8, 1)),  # Sunday
        (date(2026, 9, 1), date(2026, 8, 31), date(2026, 9, 1)),  # month turns
        (date(2027, 1, 1), date(2026, 12, 28), date(2027, 1, 1)),  # year turns
    ],
)
def test_week_and_month_starts(as_of, wtd_start, mtd_start):
    w = periods.windows(as_of)
    assert (w["wtd"].start, w["wtd"].end) == (wtd_start, as_of)
    assert (w["mtd"].start, w["mtd"].end) == (mtd_start, as_of)


def test_in_window_is_inclusive():
    days = pl.Series(
        [date(2026, 8, 9), date(2026, 8, 10), date(2026, 8, 14), date(2026, 8, 15)]
    )
    w = periods.windows(date(2026, 8, 14))["wtd"]
    mask = pl.select(periods.in_window(pl.lit(days), w)).to_series().to_list()
    assert mask == [False, True, True, False]

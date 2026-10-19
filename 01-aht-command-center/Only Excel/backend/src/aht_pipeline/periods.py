"""Business days, hours and the windows AHT is shown for.

Timestamps are stored in UTC; a call's day and hour are cut in the business
timezone, the same rule as use case 2.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import polars as pl

from . import settings


@dataclass(frozen=True)
class Window:
    name: str
    start: date  # inclusive
    end: date  # inclusive; before `start` when the window is empty


def _local(s: pl.Series) -> pl.Series:
    """Anything but a UTC Datetime raises: polars would read a naive one as UTC."""
    if not (isinstance(s.dtype, pl.Datetime) and s.dtype.time_zone == "UTC"):
        raise TypeError(f"{s.name} must be a UTC Datetime, got {s.dtype}")
    return s.dt.convert_time_zone(settings.BUSINESS_TIMEZONE)


def business_date(started_at: pl.Expr) -> pl.Expr:
    return started_at.map_batches(
        lambda s: _local(s).dt.date(), return_dtype=pl.Date, is_elementwise=True
    )


def business_hour(started_at: pl.Expr) -> pl.Expr:
    """0-23, the hour of the business day a call started in."""
    return started_at.map_batches(
        lambda s: _local(s).dt.hour(), return_dtype=pl.Int8, is_elementwise=True
    )


def windows(as_of: date) -> dict[str, Window]:
    """Today, yesterday and month to date, as of a business day.

    `before_today` is the month to date without today, the base a flagged agent's
    day is compared with. It is empty on the 1st, and yesterday is then last month.
    """
    yesterday = as_of - timedelta(days=1)
    month_start = as_of.replace(day=1)
    return {
        w.name: w
        for w in (
            Window("today", as_of, as_of),
            Window("yesterday", yesterday, yesterday),
            Window("mtd", month_start, as_of),
            Window("before_today", month_start, yesterday),
        )
    }


def in_window(day: pl.Expr, window: Window) -> pl.Expr:
    return day.is_between(window.start, window.end, closed="both")

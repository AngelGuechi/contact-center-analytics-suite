"""Business days and the time windows NPS is shown for.

Timestamps are stored in UTC; a survey's day is cut in the business timezone.
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
    end: date  # inclusive


def business_date(completed_at: pl.Expr) -> pl.Expr:
    """A UTC Datetime column -> the date in the business timezone.

    Anything else raises: polars would read a naive Datetime as UTC and shift the day.
    """

    def to_day(s: pl.Series) -> pl.Series:
        if not (isinstance(s.dtype, pl.Datetime) and s.dtype.time_zone == "UTC"):
            raise TypeError(f"{s.name} must be a UTC Datetime, got {s.dtype}")
        return s.dt.convert_time_zone(settings.BUSINESS_TIMEZONE).dt.date()

    return completed_at.map_batches(to_day, return_dtype=pl.Date, is_elementwise=True)


def windows(as_of: date) -> dict[str, Window]:
    """Today, yesterday, week to date and month to date, as of a business day.

    `prior_wtd` is the same days of the week before: the base a week in progress is
    compared with, never a full week.
    """
    week_start = as_of - timedelta(days=(as_of.isoweekday() - settings.WEEK_START) % 7)
    yesterday = as_of - timedelta(days=1)
    week_ago = timedelta(days=7)
    return {
        w.name: w
        for w in (
            Window("today", as_of, as_of),
            Window("yesterday", yesterday, yesterday),
            Window("wtd", week_start, as_of),
            Window("prior_wtd", week_start - week_ago, as_of - week_ago),
            Window("mtd", as_of.replace(day=1), as_of),
        )
    }


def in_window(day: pl.Expr, window: Window) -> pl.Expr:
    return day.is_between(window.start, window.end, closed="both")

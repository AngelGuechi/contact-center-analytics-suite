"""AHT, weighted by calls (README "Calculation rules").

AHT = (talk + hold + wrap seconds) ÷ calls. Every figure is summed from call rows: a
rollup (supervisor, manager, site) sums the seconds and calls underneath it and
divides again; it never averages lower-level AHT. Talk, hold and wrap per call add up
to AHT.

Input is a call frame: one row per call, unique `transaction_id`, `call_started_at`
(UTC), whole `talk_seconds` / `hold_seconds` / `wrap_seconds`, and whatever columns
the caller groups by (`login_id`, `supervisor`, `manager`, `site`, `call_type`).
The dashboard's filters (call type, supervisor, manager) narrow the frame first.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import polars as pl

from . import periods, settings

PARTS = ("talk", "hold", "wrap")
WINDOWS = ("today", "yesterday", "mtd")
ALERT_KINDS = ("pattern", "spike", "no history")


def _check(calls: pl.DataFrame) -> None:
    """Weighting is only exact if each call is counted once with whole seconds."""
    dupes = calls.filter(pl.col("transaction_id").is_duplicated())["transaction_id"]
    if len(dupes):
        raise ValueError(f"transaction_id repeated: {', '.join(dupes.unique().sort())}")
    for col in (f"{p}_seconds" for p in PARTS):
        if not calls.schema[col].is_integer():
            raise ValueError(f"{col} must be whole seconds, got {calls.schema[col]}")
        bad = calls.filter(pl.col(col).is_null() | (pl.col(col) < 0))
        if len(bad):
            raise ValueError(f"{col} missing or negative on {bad.height} calls")


def alert_threshold() -> pl.Expr:
    """Each call's alert threshold in seconds: its call type's, else the flat one."""
    flat = pl.lit(settings.ALERT_SECONDS, dtype=pl.Float64)
    if not settings.ALERT_SECONDS_BY_CALL_TYPE:
        return flat
    return pl.col("call_type").replace_strict(
        settings.ALERT_SECONDS_BY_CALL_TYPE, default=flat, return_dtype=pl.Float64
    )


def _aht(frame: pl.DataFrame, by: list[str]) -> pl.DataFrame:
    """Sums the `_threshold`-carrying frame per group, then divides by calls."""
    sums = [
        pl.len().cast(pl.Int64).alias("calls"),
        *(pl.col(f"{p}_seconds").sum().alias(f"{p}_seconds") for p in PARTS),
        pl.col("_threshold").mean().alias("alert_seconds"),
    ]
    out = (
        frame.group_by(by).agg(sums).sort(by, nulls_last=True)
        if by
        else frame.select(sums)
    )

    def per_call(seconds: pl.Expr) -> pl.Expr:
        return pl.when(pl.col("calls") > 0).then(seconds / pl.col("calls"))

    handle = pl.sum_horizontal(f"{p}_seconds" for p in PARTS)
    return out.with_columns(handle.alias("handle_seconds")).with_columns(
        per_call(pl.col("handle_seconds")).alias("aht"),
        *(per_call(pl.col(f"{p}_seconds")).alias(f"aht_{p}") for p in PARTS),
        (per_call(pl.col("handle_seconds")) - pl.col("alert_seconds")).alias(
            "gap_to_alert"
        ),
        (per_call(pl.col("handle_seconds")) > pl.col("alert_seconds"))
        .fill_null(False)
        .alias("above_alert"),
    )


def aht_by(calls: pl.DataFrame, by: Sequence[str] = ()) -> pl.DataFrame:
    """One row per group (one row overall when `by` is empty): calls; summed talk,
    hold, wrap and handle seconds; AHT and its talk / hold / wrap parts per call; and
    the alert. Figures are exact (not rounded) and null when a group has no calls.

    `alert_seconds` is the mean of each call's threshold: 640 while the alert is
    flat, and with per-call-type thresholds the threshold for the group's own call
    mix. `above_alert` is AHT strictly above it.
    """
    _check(calls)
    return _aht(calls.with_columns(alert_threshold().alias("_threshold")), list(by))


def board(calls: pl.DataFrame, as_of: date, by: Sequence[str] = ()) -> pl.DataFrame:
    """The dashboard's table, one row per group (one overall when `by` is empty):
    today, yesterday and month to date side by side, worst gap to alert first.

    Per window (suffix `_today`, `_yesterday`, `_mtd`): calls, aht, aht_talk,
    aht_hold, aht_wrap. Then today's `alert_seconds`, `gap_to_alert`, `above_alert`,
    and `alert_kind` for a group above alert, judged against its own month before
    today:
      "pattern"     its AHT earlier this month is above its alert too
      "spike"       it is not
      "no history"  it has no calls earlier this month
    `vs_yesterday` and `vs_mtd` are today's AHT minus the other: positive is longer,
    so worse.

    A group appears when it has calls yesterday or this month. A window without its
    calls shows 0 calls and null AHT, and a group without calls today is never above
    alert.
    """
    _check(calls)
    keys = list(by) or ["_all"]
    w = periods.windows(as_of)
    frame = calls.with_columns(
        periods.business_date(pl.col("call_started_at")).alias("_day"),
        alert_threshold().alias("_threshold"),
        pl.lit(True).alias("_all"),
    )
    day = pl.col("_day")
    if by:
        seen = periods.in_window(day, w["yesterday"]) | periods.in_window(day, w["mtd"])
        out = frame.filter(seen).select(keys).unique()
    else:
        out = pl.DataFrame({"_all": [True]})

    shown = ["calls", "aht", *(f"aht_{p}" for p in PARTS)]
    for name, cols in (
        ("today", [*shown, "alert_seconds", "gap_to_alert", "above_alert"]),
        ("yesterday", shown),
        ("mtd", shown),
        ("before_today", ["calls", "aht", "alert_seconds"]),
    ):
        stats = _aht(frame.filter(periods.in_window(day, w[name])), keys)
        plain = (
            ("alert_seconds", "gap_to_alert", "above_alert") if name == "today" else ()
        )
        stats = stats.select(
            *keys, *(pl.col(c).alias(c if c in plain else f"{c}_{name}") for c in cols)
        )
        out = out.join(stats, on=keys, how="left", nulls_equal=True)

    above = pl.col("above_alert").fill_null(False)
    kind = (
        pl.when(~above)
        .then(None)
        .when(pl.col("calls_before_today").fill_null(0) == 0)
        .then(pl.lit("no history"))
        .when(pl.col("aht_before_today") > pl.col("alert_seconds_before_today"))
        .then(pl.lit("pattern"))
        .otherwise(pl.lit("spike"))
    )
    out = out.with_columns(
        *(pl.col(f"calls_{n}").fill_null(0) for n in WINDOWS),
        above.alias("above_alert"),
        kind.alias("alert_kind"),
        (pl.col("aht_today") - pl.col("aht_yesterday")).alias("vs_yesterday"),
        (pl.col("aht_today") - pl.col("aht_mtd")).alias("vs_mtd"),
    )
    order = [
        *by,
        *(f"{c}_today" for c in shown),
        "alert_seconds",
        "gap_to_alert",
        "above_alert",
        "alert_kind",
        "vs_yesterday",
        "vs_mtd",
        *(f"{c}_{n}" for n in ("yesterday", "mtd") for c in shown),
    ]
    return out.select(order).sort(
        ["gap_to_alert", *by],
        descending=[True, *[False] * len(by)],
        nulls_last=True,
    )


def intraday(calls: pl.DataFrame, as_of: date, by: Sequence[str] = ()) -> pl.DataFrame:
    """AHT by business hour, today and yesterday side by side: one row per group and
    `hour` (0-23, the hour a call started) with calls on either day.

    For the site, leave `by` empty; for one agent, filter the calls first.
    """
    _check(calls)
    keys = [*by, "hour"]
    w = periods.windows(as_of)
    frame = calls.with_columns(
        periods.business_date(pl.col("call_started_at")).alias("_day"),
        periods.business_hour(pl.col("call_started_at")).alias("hour"),
        alert_threshold().alias("_threshold"),
    )
    today, yesterday = (
        _aht(frame.filter(periods.in_window(pl.col("_day"), w[name])), keys).select(
            *keys,
            pl.col("calls").alias(f"calls_{name}"),
            pl.col("aht").alias(f"aht_{name}"),
        )
        for name in ("today", "yesterday")
    )
    return (
        today.join(yesterday, on=keys, how="full", coalesce=True, nulls_equal=True)
        .with_columns(pl.col("calls_today", "calls_yesterday").fill_null(0))
        .sort(keys, nulls_last=True)
    )

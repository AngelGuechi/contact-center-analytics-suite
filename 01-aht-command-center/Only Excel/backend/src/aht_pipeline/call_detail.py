"""A call-detail export (.xlsx; the shared sample is .ods), one row per call, in our
names (`headers.FIELDS`).

The traps are the ones use case 2 handles (its data contract §2): key on
`login_id`, drop login `U0` and count it, handle time is talk + hold + wrap (never
`Call Duration`), and `Start Date Time` is naive, in the business timezone.

The client's cell formats are not confirmed either, so every column is read as text
and parsed here: Excel would otherwise turn a stray "N/A" into a blank without a word.
A duration is whole seconds, `h:mm:ss`, `mm:ss` or an Excel time cell; a start time
is an Excel date cell or ISO text. Anything else is rejected with its values, never
guessed: a decimal like 21.57 could be minutes, and 0.0058 a fraction of a day.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from . import headers, paths, settings

UNKNOWN_LOGIN = "U0"
SECONDS = ("talk_seconds", "hold_seconds", "wrap_seconds")
SHOWN = 5  # unreadable values quoted in an error


@dataclass(frozen=True)
class CallDetail:
    calls: pl.DataFrame
    excluded_unknown_login: int  # calls with login U0, reported, never used


def read_raw(path: Path = paths.CALL_DETAIL) -> pl.DataFrame:
    """Our columns only, as text, renamed to our names."""
    with warnings.catch_warnings():  # polars' own from_arrow deprecation, not ours
        warnings.filterwarnings("ignore", "from_arrow", FutureWarning)
        found = pl.read_excel(path, read_options={"n_rows": 0}).columns
        names = headers.match(found)
        raw = pl.read_excel(
            path, columns=list(names), read_options={"dtypes": "string"}
        )
    return raw.rename(names)


def seconds(text: pl.Expr) -> pl.Expr:
    """Whole seconds from `502`, `502.0`, `8:22`, `0:08:22` or an Excel time cell
    (`1899-12-31 00:08:22`); null for anything else."""
    whole = text.str.extract(r"^(\d+)(?:\.0+)?$", 1).cast(pl.Int64, strict=False)
    hms = text.str.extract_groups(r"^(?:(\d+):)?(\d+):(\d{2})$")
    clock = (
        hms.struct.field("1").cast(pl.Int64, strict=False).fill_null(0) * 3600
        + hms.struct.field("2").cast(pl.Int64, strict=False) * 60
        + hms.struct.field("3").cast(pl.Int64, strict=False)
    )
    excel_time = (
        text.str.extract(r"^1899-12-3[01][ T](\d{2}:\d{2}:\d{2}(?:\.\d+)?)$", 1)
        .str.to_time("%H:%M:%S%.f", strict=False)
        .cast(pl.Int64)  # nanoseconds since midnight
        .truediv(1e9)
        .round()
        .cast(pl.Int64)
    )
    return pl.coalesce(whole, clock, excel_time)


def started_at(text: pl.Expr) -> pl.Expr:
    """A naive start time in the business timezone -> UTC; null if unreadable."""
    return (
        text.str.replace("T", " ", literal=True)
        .str.to_datetime("%Y-%m-%d %H:%M:%S%.f", time_unit="us", strict=False)
        .dt.replace_time_zone(settings.BUSINESS_TIMEZONE)
        .dt.convert_time_zone("UTC")
    )


def clean(raw: pl.DataFrame) -> CallDetail:
    """One row per call with a known agent, or this raises: a blank cell, a value it
    can't read, or a repeated call. Text columns are trimmed; a blank is null.
    """
    trimmed = (pl.col(c).cast(pl.String).str.strip_chars() for c in headers.FIELDS)
    text = raw.select(
        pl.when(t != "").then(t).alias(t.meta.output_name()) for t in trimmed
    )
    if text["login_id"].null_count():
        raise ValueError(f"{text['login_id'].null_count()} calls have a blank login_id")
    known = text.filter(pl.col("login_id") != UNKNOWN_LOGIN)
    blanks = [f"{c} ({n})" for c in known.columns if (n := known[c].null_count())]
    if blanks:
        raise ValueError(f"blank cells in {', '.join(blanks)}")

    calls = known.with_columns(
        started_at(pl.col("call_started_at")),
        *(seconds(pl.col(c)) for c in SECONDS),
    )
    bad = [
        f"{c} ({len(vals)}: {', '.join(vals.unique(maintain_order=True).head(SHOWN))})"
        for c in ("call_started_at", *SECONDS)
        if len(vals := known.filter(calls[c].is_null())[c])
    ]
    if bad:
        raise ValueError(
            f"unreadable values in {'; '.join(bad)}. Durations must be whole seconds, "
            "h:mm:ss or mm:ss; start times a date and time like 2026-08-14 09:30:00"
        )
    dupes = calls.filter(pl.col("transaction_id").is_duplicated())["transaction_id"]
    if len(dupes):
        raise ValueError(f"transaction_id repeated: {', '.join(dupes.unique().sort())}")
    return CallDetail(calls, text.height - known.height)


def read_call_detail(path: Path = paths.CALL_DETAIL) -> CallDetail:
    return clean(read_raw(path))

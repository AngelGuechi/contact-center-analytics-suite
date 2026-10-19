"""The shared call-detail sample, read only (data contract §2).

Traps are in `shared/call-detail.md`: key on `Login ID`, drop login `U0` and count
it, handle time is talk + hold + wrap (never `Call Duration`), and `Start Date Time`
is naive, in the business timezone.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from . import paths, settings

UNKNOWN_LOGIN = "U0"
LANGUAGES = {"EN": "English", "ES": "Spanish"}
SOURCE_COLUMNS = (
    "Transaction ID",
    "Login ID",
    "Agent Name",
    "Start Date Time",
    "Talk Time",
    "Hold Time",
    "Wrap Time",
    "Transfer Flag",
    "Skill",
)


@dataclass(frozen=True)
class CallDetail:
    calls: pl.DataFrame
    excluded_unknown_login: int  # calls with login U0, reported, never used


def read_raw(path: Path = paths.CALL_DETAIL) -> pl.DataFrame:
    with warnings.catch_warnings():  # polars' own from_arrow deprecation, not ours
        warnings.filterwarnings("ignore", "from_arrow", FutureWarning)
        return pl.read_excel(path, columns=list(SOURCE_COLUMNS))


def clean(raw: pl.DataFrame) -> CallDetail:
    """One row per call, in the contract's names. Raises on anything it can't trust:
    a blank cell (only a U0 call may lack a name), a repeated call, negative seconds,
    or a flag or skill outside its values.

    `call_started_at` is UTC; `agent_name` has its whitespace collapsed, for building
    the roster only (displayed names come from the roster).
    """
    if raw["Login ID"].null_count():
        raise ValueError(f"{raw['Login ID'].null_count()} calls have a blank Login ID")
    known = raw.filter(pl.col("Login ID") != UNKNOWN_LOGIN)
    blanks = [c for c in SOURCE_COLUMNS if known[c].null_count()]
    if blanks:
        raise ValueError(f"blank cells in {', '.join(blanks)}")
    dupes = known.filter(pl.col("Transaction ID").is_duplicated())["Transaction ID"]
    if len(dupes):
        raise ValueError(f"Transaction ID repeated: {', '.join(dupes.unique().sort())}")
    parts = pl.col("Talk Time", "Hold Time", "Wrap Time")
    if known.filter(pl.any_horizontal(parts < 0)).height:
        raise ValueError("Talk, Hold and Wrap Time must be non-negative seconds")
    if not known["Transfer Flag"].is_in(["Y", "N"]).all():
        raise ValueError("Transfer Flag must be Y or N")
    if not known["Skill"].is_in(list(LANGUAGES)).all():
        raise ValueError(f"Skill must be one of {', '.join(LANGUAGES)}")

    calls = known.select(
        pl.col("Transaction ID").alias("transaction_id"),
        pl.col("Login ID").alias("login_id"),
        pl.col("Agent Name")
        .str.strip_chars()
        .str.replace_all(r"\s+", " ")
        .alias("agent_name"),
        pl.col("Start Date Time")
        .dt.replace_time_zone(settings.BUSINESS_TIMEZONE)
        .dt.convert_time_zone("UTC")
        .alias("call_started_at"),
        (pl.col("Talk Time") + pl.col("Hold Time") + pl.col("Wrap Time"))
        .cast(pl.Int64)
        .alias("handle_seconds"),
        pl.col("Hold Time").cast(pl.Int64).alias("hold_seconds"),
        pl.col("Transfer Flag").alias("transferred"),
        pl.col("Skill").replace_strict(LANGUAGES).alias("call_language"),
    )
    return CallDetail(calls, raw.height - known.height)


def read_call_detail(path: Path = paths.CALL_DETAIL) -> CallDetail:
    return clean(read_raw(path))

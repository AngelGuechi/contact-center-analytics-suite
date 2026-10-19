"""The calls the engine reads: call detail + call type + roster, one row per call.

The roster and the call types are use case 2's files for now (see `paths`), read and
never written. Rollups and displayed names come from the roster, never from the call
detail, whose `Supervisor`, `Team` and `Site` change from call to call.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from . import paths
from .call_detail import read_call_detail

ROSTER_HEADERS = {  # the roster file keeps Excel-style headers, as use case 2 writes it
    "Login ID": "login_id",
    "Agent Name": "agent_name",
    "Supervisor": "supervisor",
    "Manager": "manager",
    "Delivery Manager": "delivery_manager",
    "Site": "site",
    "Status": "status",
}


def read_roster(path: Path = paths.ROSTER) -> pl.DataFrame:
    roster = pl.read_csv(path, schema={k: pl.String for k in ROSTER_HEADERS})
    roster = roster.rename(ROSTER_HEADERS)
    if roster.null_count().sum_horizontal().item():
        raise ValueError("roster has blank cells")
    if roster["login_id"].is_duplicated().any():
        raise ValueError("roster repeats a Login ID")
    return roster


def read_call_types(path: Path = paths.CALL_CONTEXT) -> pl.DataFrame:
    """transaction_id -> call_type, from use case 2's call context sidecar."""
    types = pl.read_csv(
        path, columns=["transaction_id", "call_type"], infer_schema=False
    )
    if types["transaction_id"].is_duplicated().any():
        raise ValueError("call types repeat a transaction_id")
    return types


def join_calls(
    calls: pl.DataFrame, call_types: pl.DataFrame, roster: pl.DataFrame
) -> pl.DataFrame:
    """Every call gets its call type and its agent's roster row, or this raises."""
    no_type = calls.join(call_types, on="transaction_id", how="anti")
    no_roster = calls.join(roster, on="login_id", how="anti")["login_id"].unique()
    problems = [
        f"{no_type.height} calls have no call type" if no_type.height else "",
        f"logins missing from the roster: {', '.join(no_roster.sort())}"
        if len(no_roster)
        else "",
    ]
    if any(problems):
        raise ValueError("; ".join(p for p in problems if p))
    return (
        calls.join(call_types, on="transaction_id")
        .join(roster.drop("status"), on="login_id")
        .sort("transaction_id")
    )


def load_calls(path: Path = paths.CALL_DETAIL) -> tuple[pl.DataFrame, int]:
    """The joined calls, and how many calls were excluded for login U0."""
    detail = read_call_detail(path)
    calls = join_calls(detail.calls, read_call_types(), read_roster())
    return calls, detail.excluded_unknown_login

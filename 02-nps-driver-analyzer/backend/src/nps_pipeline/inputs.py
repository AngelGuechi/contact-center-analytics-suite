"""The call side of every survey: call detail + sidecar + roster, one row per call.

From `backend/`, `PYTHONPATH=src uv run python -m nps_pipeline.inputs` (re)writes the
roster and the sidecar from the shared call detail. Both are deterministic, so
rerunning changes nothing.
"""

from __future__ import annotations

import polars as pl

from .call_context import build_call_context, read_call_context, write_call_context
from .call_detail import read_call_detail
from .roster import build_roster, read_roster, write_roster


def join_calls(
    calls: pl.DataFrame, context: pl.DataFrame, roster: pl.DataFrame
) -> pl.DataFrame:
    """Every call gets its context and its agent's roster row, or this raises.

    The call detail's own `agent_name` is dropped: displayed names come from the
    roster.
    """
    no_context = calls.join(context, on="transaction_id", how="anti")
    extra_context = context.join(calls, on="transaction_id", how="anti")
    no_roster = calls.join(roster, on="login_id", how="anti")["login_id"].unique()
    problems = [
        f"{no_context.height} calls have no call context" if no_context.height else "",
        f"{extra_context.height} context rows match no call"
        if extra_context.height
        else "",
        f"logins missing from the roster: {', '.join(no_roster.sort())}"
        if len(no_roster)
        else "",
    ]
    if any(problems):
        raise ValueError("; ".join(p for p in problems if p))
    return (
        calls.drop("agent_name")
        .join(context, on="transaction_id")
        .join(roster.drop("status"), on="login_id")
        .sort("transaction_id")
    )


def load_calls() -> tuple[pl.DataFrame, int]:
    """The joined calls, and how many calls were excluded for login U0."""
    detail = read_call_detail()
    calls = join_calls(detail.calls, read_call_context(), read_roster())
    return calls, detail.excluded_unknown_login


def main() -> None:
    detail = read_call_detail()
    roster = build_roster(detail.calls.select("login_id", "agent_name"))
    context = build_call_context(detail.calls["transaction_id"].to_list())
    join_calls(detail.calls, context, roster)  # fail before writing anything
    write_roster(roster)
    write_call_context(context)
    print(
        f"{detail.calls.height} calls ({detail.excluded_unknown_login} with login U0 "
        f"excluded), {roster.height} agents in the roster"
    )


if __name__ == "__main__":
    main()

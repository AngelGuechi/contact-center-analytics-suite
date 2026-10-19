"""Joining call detail, sidecar and roster: every call or an error, never a gap."""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl
import pytest

from nps_pipeline import call_context, call_detail, inputs, paths, roster


def calls() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "transaction_id": ["TXN1", "TXN2"],
            "login_id": ["U1", "U2"],
            "agent_name": ["Raw  Name", "Other"],
            "call_started_at": [datetime(2026, 8, 14, 15, tzinfo=UTC)] * 2,
            "handle_seconds": [600, 700],
        }
    )


def context_rows(ids=("TXN1", "TXN2")) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "transaction_id": list(ids),
            "call_type": "Credit",
            "ivr_seconds": 60,
            "virtual_assistant_used": "N",
        }
    )


def roster_rows(logins=("U1", "U2")) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "login_id": list(logins),
            "agent_name": [f"Roster {x}" for x in logins],
            "supervisor": "S",
            "manager": "M",
            "delivery_manager": "D",
            "site": "MTY",
            "status": "Active",
        }
    )


def test_names_come_from_the_roster():
    joined = inputs.join_calls(calls(), context_rows(), roster_rows())
    assert joined.height == 2
    assert joined["agent_name"].to_list() == ["Roster U1", "Roster U2"]
    assert {"call_type", "supervisor", "site"} <= set(joined.columns)


@pytest.mark.parametrize(
    ("ctx", "ros", "message"),
    [
        (context_rows(["TXN1"]), roster_rows(), "1 calls have no call context"),
        (
            context_rows(["TXN1", "TXN2", "TXN9"]),
            roster_rows(),
            "1 context rows match no call",
        ),
        (context_rows(), roster_rows(["U1"]), "missing from the roster: U2"),
    ],
)
def test_gaps_raise(ctx, ros, message):
    with pytest.raises(ValueError, match=message):
        inputs.join_calls(calls(), ctx, ros)


WRITTEN = paths.ROSTER.exists() and paths.CALL_CONTEXT.exists()


@pytest.mark.skipif(not WRITTEN, reason="run nps_pipeline.inputs first")
def test_the_written_inputs_cover_every_call():
    joined, excluded = inputs.load_calls()
    assert (joined.height, excluded) == (12_426, 74)
    assert joined.null_count().sum_horizontal().item() == 0


@pytest.mark.skipif(not WRITTEN, reason="run nps_pipeline.inputs first")
def test_the_written_inputs_match_a_rebuild():
    detail = call_detail.read_call_detail()
    rebuilt = roster.build_roster(detail.calls.select("login_id", "agent_name"))
    assert roster.read_roster().equals(rebuilt)
    ids = detail.calls["transaction_id"].to_list()
    assert call_context.read_call_context().equals(call_context.build_call_context(ids))

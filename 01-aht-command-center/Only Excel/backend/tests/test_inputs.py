"""Joining calls to call types and the roster, and the engine on the shared sample."""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from aht_pipeline import aht, inputs, paths


def calls() -> pl.DataFrame:
    return pl.DataFrame({"transaction_id": ["TXN1", "TXN2"], "login_id": ["U1", "U2"]})


def call_types() -> pl.DataFrame:
    return pl.DataFrame(
        {"transaction_id": ["TXN1", "TXN2"], "call_type": ["Credit", "NEM"]}
    )


def roster() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "login_id": ["U1", "U2"],
            "agent_name": ["Elena Cruz", "Omar Garcia"],
            "supervisor": ["S1", "S2"],
            "manager": ["M1", "M1"],
            "delivery_manager": ["D1", "D1"],
            "site": ["MTY", "GDL"],
            "status": ["Active", "Active"],
        }
    )


def test_every_call_gets_its_call_type_and_roster_row():
    joined = inputs.join_calls(calls(), call_types(), roster())
    assert joined["call_type"].to_list() == ["Credit", "NEM"]
    assert joined["supervisor"].to_list() == ["S1", "S2"]
    assert "status" not in joined.columns


def test_a_call_without_a_call_type_or_roster_row_is_rejected():
    with pytest.raises(ValueError, match="1 calls have no call type"):
        inputs.join_calls(calls(), call_types().head(1), roster())
    with pytest.raises(ValueError, match="logins missing from the roster: U2"):
        inputs.join_calls(calls(), call_types(), roster().head(1))


def test_the_shared_sample_joins_completely():
    joined, excluded = inputs.load_calls()
    assert (joined.height, excluded) == (12426, 74)
    assert joined["login_id"].n_unique() == 42
    assert joined.select(pl.all().null_count()).sum_horizontal().item() == 0


@pytest.mark.filterwarnings("ignore:from_arrow:FutureWarning")  # polars' own
def test_site_aht_on_the_sample_matches_a_direct_count():
    """The whole path (text parsing, CDMX -> UTC -> CDMX day) against a plain sum."""
    columns = ["Login ID", "Start Date Time", "Talk Time", "Hold Time", "Wrap Time"]
    raw = pl.read_excel(paths.CALL_DETAIL, columns=columns)
    day = raw.filter(
        (pl.col("Login ID") != "U0")
        & (pl.col("Start Date Time").dt.date() == date(2026, 8, 14))
    )
    handle = (day["Talk Time"] + day["Hold Time"] + day["Wrap Time"]).sum()
    joined, _ = inputs.load_calls()
    site = aht.board(joined, date(2026, 8, 14)).row(0, named=True)
    assert site["calls_today"] == day.height
    assert site["aht_today"] == pytest.approx(handle / day.height)

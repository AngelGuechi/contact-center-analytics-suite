"""Call detail cleaning, on hand-made rows and on the shared sample."""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl
import pytest

from nps_pipeline import call_detail


def raw(**overrides) -> pl.DataFrame:
    """Two calls and one U0 call, in the export's own column names."""
    base = {
        "Transaction ID": ["TXN1", "TXN2", "TXN3"],
        "Login ID": ["U200001", "U200002", "U0"],
        "Agent Name": ["  Elena  Cruz ", "Omar Garcia", None],
        "Start Date Time": [datetime(2026, 8, 14, 23, 30)] * 3,
        "Talk Time": [502, 0, 10],
        "Hold Time": [10, 48, 0],
        "Wrap Time": [153, 175, 0],
        "Transfer Flag": ["N", "Y", "N"],
        "Skill": ["EN", "ES", "EN"],
    }
    base.update(overrides)
    return pl.DataFrame(base)


def test_handle_time_is_talk_plus_hold_plus_wrap():
    calls = call_detail.clean(raw()).calls
    assert calls["handle_seconds"].to_list() == [665, 223]
    assert calls["hold_seconds"].to_list() == [10, 48]


def test_u0_is_excluded_and_counted():
    detail = call_detail.clean(raw())
    assert detail.calls["login_id"].to_list() == ["U200001", "U200002"]
    assert detail.excluded_unknown_login == 1


def test_naive_start_is_business_time_stored_in_utc():
    started = call_detail.clean(raw()).calls["call_started_at"][0]
    # 23:30 CDMX on the 14th is 05:30 UTC on the 15th
    assert started == datetime(2026, 8, 15, 5, 30, tzinfo=UTC)


def test_names_collapse_whitespace_and_skill_becomes_language():
    calls = call_detail.clean(raw()).calls
    assert calls["agent_name"].to_list() == ["Elena Cruz", "Omar Garcia"]
    assert calls["call_language"].to_list() == ["English", "Spanish"]
    assert calls["transferred"].to_list() == ["N", "Y"]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"Transaction ID": ["TXN1", "TXN1", "TXN3"]}, "Transaction ID repeated"),
        ({"Wrap Time": [153, -1, 0]}, "non-negative"),
        ({"Transfer Flag": ["N", "y", "N"]}, "Transfer Flag must be"),
        ({"Skill": ["EN", "FR", "EN"]}, "Skill must be"),
    ],
)
def test_untrustworthy_rows_raise(overrides, message):
    with pytest.raises(ValueError, match=message):
        call_detail.clean(raw(**overrides))


@pytest.mark.parametrize(
    "column",
    [
        "Transaction ID",
        "Agent Name",
        "Start Date Time",
        "Hold Time",
        "Transfer Flag",
        "Skill",
    ],
)
def test_a_blank_cell_on_a_known_login_raises(column):
    values = raw()[column].to_list()
    values[1] = None
    with pytest.raises(ValueError, match=f"blank cells in {column}"):
        call_detail.clean(raw(**{column: values}))


def test_a_blank_login_is_not_counted_as_u0():
    with pytest.raises(ValueError, match="1 calls have a blank Login ID"):
        call_detail.clean(raw(**{"Login ID": ["U200001", None, "U0"]}))


def test_the_shared_sample():
    detail = call_detail.read_call_detail()
    calls = detail.calls
    assert (calls.height, detail.excluded_unknown_login) == (12_426, 74)
    assert calls["login_id"].n_unique() == calls["agent_name"].n_unique() == 42
    first = calls.filter(pl.col("transaction_id") == "TXN500000").row(0, named=True)
    # 502 talk + 10 hold + 153 wrap; 19:47:40 CDMX on Aug 11 is 01:47:40 UTC Aug 12
    assert first["handle_seconds"] == 665
    assert first["call_started_at"] == datetime(2026, 8, 12, 1, 47, 40, tzinfo=UTC)

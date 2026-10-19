from __future__ import annotations

import pytest

from aht_pipeline import headers

SAMPLE = [  # the shared sample's headers around ours, in its own order
    "Transaction ID",
    "Site",
    "Agent Name",
    "Login ID",
    "Start Date Time",
    "Call Duration",
    "Hold Time",
    "Talk Time",
    "Wrap Time",
    "Queue",
]


def test_every_field_is_found_in_the_sample_headers():
    assert headers.match(SAMPLE) == {
        "Transaction ID": "transaction_id",
        "Login ID": "login_id",
        "Start Date Time": "call_started_at",
        "Talk Time": "talk_seconds",
        "Hold Time": "hold_seconds",
        "Wrap Time": "wrap_seconds",
    }


def test_matching_ignores_case_and_extra_spaces():
    found = headers.match(
        [
            "transaction id",
            "LOGIN ID",
            " Start  Date Time ",
            "talk time",
            "Hold Time",
            "Wrap Time",
        ]
    )
    assert found[" Start  Date Time "] == "call_started_at"
    assert found["LOGIN ID"] == "login_id"


def test_a_missing_field_names_it_and_lists_the_file_headers():
    with pytest.raises(ValueError) as err:
        headers.match([h for h in SAMPLE if h != "Wrap Time"])
    assert "no column for wrap_seconds (Wrap Time)" in str(err.value)
    assert "The file has: Transaction ID, Site, Agent Name" in str(err.value)


def test_two_columns_for_one_field_is_rejected():
    with pytest.raises(ValueError, match=r"more than one column for talk_seconds"):
        headers.match([*SAMPLE, "TALK TIME"])


def test_another_accepted_header_is_one_edit_away(monkeypatch):
    monkeypatch.setitem(headers.FIELDS, "wrap_seconds", ("Wrap Time", "ACW"))
    renamed = [h if h != "Wrap Time" else "ACW" for h in SAMPLE]
    assert headers.match(renamed)["ACW"] == "wrap_seconds"

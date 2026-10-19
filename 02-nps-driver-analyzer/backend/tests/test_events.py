"""The Survey Event's own rules (data contract §1)."""

from __future__ import annotations

import pytest

from nps_pipeline import events


def event(**changes) -> dict:
    e = {
        "event_type": "survey.completed",
        "survey_id": "ACS-2026-004817",
        "transaction_id": "TXN503311",
        "agent_login_id": "U200006",
        "survey_channel": "IVR",
        "completed_at": "2026-08-14T21:07:00Z",
        "q1_ltr": 2,
        "q2_agent_sat": 3,
        "q3_explained_clearly": 1,
        "q4_ease": 4,
        "q5_issue_resolved": "Partially",
        "q5a_why_not_resolved": "They could not lower my bill.",
        "q6_main_reason": "My bill amount",
        "comment": "My bill doubled this month.",
        "callback_consent": "Yes",
        "escalated": "Y",
    }
    e.update(changes)
    return e


def test_the_contract_example_is_valid():
    events.validate_event(event())


def test_an_abandoned_survey_is_valid():
    abandoned = {k: None for k in events.NULLABLE}
    events.validate_event(event(**abandoned, escalated="N"))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"q1_ltr": 11}, "q1_ltr must be an integer 0-10"),
        ({"q1_ltr": True}, "q1_ltr must be an integer 0-10"),
        ({"q1_ltr": None}, "q1_ltr is missing"),
        ({"q2_agent_sat": "3"}, "q2_agent_sat must be an integer 0-10"),
        ({"survey_id": "4817"}, "survey_id must be ACS-YYYY-NNNNNN"),
        ({"completed_at": "2026-08-14 21:07"}, "completed_at must be UTC ISO"),
        ({"survey_channel": "Web"}, "survey_channel must be one of"),
        ({"q6_main_reason": "Price"}, "q6 is not a listed reason"),
        ({"comment": "  "}, "comment is blank"),
        ({"q5_issue_resolved": "Yes"}, "q5a is only asked when Q5 is No or Partially"),
        ({"q1_ltr": 7}, "only a detractor can be escalated"),
        ({"callback_consent": "Y"}, "callback_consent must be Yes or No"),
    ],
)
def test_broken_rules_raise(changes, message):
    with pytest.raises(events.InvalidEvent, match=message):
        events.validate_event(event(**changes))


def test_keys_must_follow_the_contract():
    e = event()
    del e["comment"]
    with pytest.raises(events.InvalidEvent, match="keys must be exactly"):
        events.validate_event(e)


def test_extra_keys_are_rejected():
    with pytest.raises(events.InvalidEvent, match="keys must be exactly"):
        events.validate_event(event(unexpected="value"))


@pytest.mark.parametrize(
    "key", ["transaction_id", "agent_login_id", "comment", "q5a_why_not_resolved"]
)
@pytest.mark.parametrize("value", [42, False, [], {"text": "a comment"}])
def test_text_fields_reject_non_strings(key, value):
    with pytest.raises(events.InvalidEvent, match=f"{key} must be a string"):
        events.validate_event(event(**{key: value}))


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-02-30T12:00:00Z",
        "2026-02-29T12:00:00Z",
        "2026-99-99T88:77:66Z",
        "2026-08-14T24:00:00Z",
        "2026-08-14T21:60:00Z",
        "2026-08-14T21:07:60Z",
    ],
)
def test_impossible_timestamps_are_rejected(timestamp):
    with pytest.raises(events.InvalidEvent, match="completed_at must be UTC ISO"):
        events.validate_event(event(completed_at=timestamp))


def test_a_valid_leap_day_is_accepted():
    e = event(completed_at="2024-02-29T12:00:00Z")
    events.validate_event(e)
    assert events.events_frame([e])["completed_at"].item().isoformat() == (
        "2024-02-29T12:00:00+00:00"
    )


@pytest.mark.parametrize("reverse_keys", [False, True])
def test_a_round_trip_keeps_every_field(tmp_path, reverse_keys):
    path = tmp_path / "survey_events_2026-08-14.jsonl"
    e = event()
    if reverse_keys:
        e = dict(reversed(list(e.items())))
    events.write_events([e], path)
    assert events.read_events(path) == [event()]
    frame = events.events_frame(events.read_events(path))
    assert frame["completed_at"].dtype.time_zone == "UTC"
    assert frame["q1_ltr"].to_list() == [2]


@pytest.mark.parametrize(
    "changes",
    [{"comment": 123}, {"completed_at": "2026-02-30T12:00:00Z"}],
)
def test_invalid_events_do_not_overwrite_an_existing_feed(tmp_path, changes):
    path = tmp_path / "survey_events.jsonl"
    events.write_events([event()], path)
    original = path.read_bytes()
    with pytest.raises(events.InvalidEvent):
        events.write_events([event(), event(**changes)], path)
    assert path.read_bytes() == original

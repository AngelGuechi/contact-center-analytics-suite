"""Personal data redaction (data contract §11, Planted Pattern F8).

The Answer Key records every piece of fake PII the generator planted; here the
redactor must find each one at its exact position, and touch nothing else.
"""

from __future__ import annotations

import json

import pytest

from nps_pipeline import events, paths
from nps_pipeline.redact import PLACEHOLDERS, find_pii, redact, redact_event

WRITTEN = any(paths.SURVEY_EVENTS.glob("survey_events_*.jsonl"))
needs_data = pytest.mark.skipif(not WRITTEN, reason="run nps_pipeline.synthetic first")


@pytest.fixture(scope="module")
def written() -> dict[str, dict]:
    files = sorted(paths.SURVEY_EVENTS.glob("survey_events_*.jsonl"))
    return {e["survey_id"]: e for f in files for e in events.read_events(f)}


@pytest.fixture(scope="module")
def planted() -> dict[str, dict]:
    text = (paths.ANSWER_KEY / "pii_planted.jsonl").read_text()
    rows = [json.loads(line) for line in text.splitlines()]
    return {r["survey_id"]: r for r in rows}


@needs_data
def test_every_planted_pii_is_found_where_it_was_planted(written, planted):
    assert planted
    for survey_id, pii in planted.items():
        found = find_pii(written[survey_id][pii["field"]])
        assert [(p.type, p.text, p.start, p.end) for p in found] == [
            (pii["type"], pii["text"], pii["start"], pii["end"])
        ], survey_id


@needs_data
def test_redacted_comments_keep_no_planted_pii(written, planted):
    for survey_id, pii in planted.items():
        redacted = redact(written[survey_id][pii["field"]])
        assert pii["text"] not in redacted
        assert PLACEHOLDERS[pii["type"]] in redacted


@needs_data
def test_verbatims_without_planted_pii_stay_unchanged(written, planted):
    for survey_id, event in written.items():
        for field in ("comment", "q5a_why_not_resolved"):
            text = event.get(field)
            has_pii = planted.get(survey_id, {}).get("field") == field
            if text and not has_pii:
                assert redact(text) == text, survey_id


@pytest.mark.parametrize(
    ("text", "redacted"),
    [
        ("Call me back at 555-0197.", "Call me back at [PHONE]."),
        ("Call (812) 555-0197 today", "Call [PHONE] today"),
        ("Mi celular es +52 81 5555 0197", "Mi celular es [PHONE]"),
        ("or 8125550197 please", "or [PHONE] please"),
        ("My account number is 8758 3479 92.", "My account number is [ACCOUNT]."),
        ("Account 1234-5678-9012 is overdue", "Account [ACCOUNT] is overdue"),
        ("Email me at ana.gomez@example.com.", "Email me at [EMAIL]."),
        ("I live at 457 Maple Avenue. Fix it.", "I live at [ADDRESS]. Fix it."),
        ("Vivo en Calle Hidalgo 123.", "Vivo en [ADDRESS]."),
        ("This is Miguel Morales. Bad call.", "This is [NAME]. Bad call."),
        ("Me llamo Ana Gómez y nadie me ayudó", "Me llamo [NAME] y nadie me ayudó"),
    ],
)
def test_personal_data_becomes_its_placeholder(text, redacted):
    assert redact(text) == redacted


@pytest.mark.parametrize(
    "text",
    [
        "My bill was $1,250.00 this month, up from $300.50.",
        "On 2026-08-14 at 10:30 I waited 45 minutes.",
        "Due 08-14-2026 and I used 12345 kWh.",
        "Since 2019 I've had 2 outages.",
        "This is ridiculous. This is The worst service.",
        "Maria was great and solved my bill on Oak Street questions.",
    ],
)
def test_text_without_personal_data_stays(text):
    assert redact(text) == text


def test_empty_verbatims_stay_empty():
    assert redact(None) is None
    assert redact("") == ""


def test_redact_event_touches_only_the_verbatim_and_copies():
    event = {
        "survey_id": "ACS-2026-000001",
        "agent_login_id": "U200006",
        "comment": "Call me back at 555-0197.",
        "q5a_why_not_resolved": None,
    }
    out = redact_event(event)
    assert out == {**event, "comment": "Call me back at [PHONE]."}
    assert event["comment"] == "Call me back at 555-0197."


@pytest.mark.parametrize(
    "name", ["Maria Gomez", "MARIA GOMEZ", "maria gomez", "mArIa GoMeZ", "ANA GÓMEZ"]
)
@pytest.mark.parametrize("field", ["comment", "q5a_why_not_resolved"])
def test_customer_names_are_redacted_in_both_fields_regardless_of_case(name, field):
    event = {field: f"My name is {name}. The bill is wrong."}
    assert redact_event(event)[field] == "My name is [NAME]. The bill is wrong."
    assert event[field] == f"My name is {name}. The bill is wrong."


@pytest.mark.parametrize(
    "text",
    [
        "This is Unacceptable service.",
        "This is Terrible.",
        "This is Billing, not customer service.",
        "Maria Gomez was the agent who helped me.",
    ],
)
def test_non_customer_names_and_complaints_are_preserved(text):
    assert redact(text) == text


@pytest.mark.parametrize("number", ["1234567890", "1234 5678 90", "1234-5678-90"])
@pytest.mark.parametrize("cue", ["My account number is ", "Account: ", "ACCOUNT #"])
def test_explicit_accounts_keep_their_type_regardless_of_grouping(number, cue):
    text = f"{cue}{number}. Call 2125550197; my bill is $340."
    assert redact(text) == f"{cue}[ACCOUNT]. Call [PHONE]; my bill is $340."
    account = find_pii(text)[0]
    assert (account.type, account.text, account.start, account.end) == (
        "account",
        number,
        len(cue),
        len(cue) + len(number),
    )

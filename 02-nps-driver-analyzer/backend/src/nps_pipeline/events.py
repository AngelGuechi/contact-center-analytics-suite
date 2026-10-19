"""The Survey Event (data contract §1): one answered survey, as a survey platform
sends it, before any call context is joined.

`validate_event` holds every rule the contract gives a single event; the generator
checks what it writes with it, and ingestion checks what it reads.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

import polars as pl

from . import settings

EVENT_TYPE = "survey.completed"
CHANNELS = ("IVR", "Email", "SMS")
RESOLVED = ("Yes", "No", "Partially")
MAIN_REASONS = (  # the Customer-Stated Reason (Q6)
    "The representative",
    "My bill amount",
    "Website or payment options",
    "Wait time or phone menu",
    "Company policy",
    "Power outage",
    "Other",
)
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"  # ISO 8601 UTC, to the second

SCHEMA = {  # in the contract's key order
    "event_type": pl.String,
    "survey_id": pl.String,
    "transaction_id": pl.String,
    "agent_login_id": pl.String,
    "survey_channel": pl.String,
    "completed_at": pl.String,
    "q1_ltr": pl.Int64,
    "q2_agent_sat": pl.Int64,
    "q3_explained_clearly": pl.Int64,
    "q4_ease": pl.Int64,
    "q5_issue_resolved": pl.String,
    "q5a_why_not_resolved": pl.String,
    "q6_main_reason": pl.String,
    "comment": pl.String,
    "callback_consent": pl.String,
    "escalated": pl.String,
}
NULLABLE = {
    "q2_agent_sat",
    "q3_explained_clearly",
    "q4_ease",
    "q5_issue_resolved",
    "q5a_why_not_resolved",
    "q6_main_reason",
    "comment",
}
_SURVEY_ID = re.compile(r"ACS-\d{4}-\d{6}")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


class InvalidEvent(ValueError):
    """A Survey Event that breaks the data contract."""


def _score(value) -> bool:
    return type(value) is int and 0 <= value <= 10  # bool is not a score


def _utc_timestamp(value) -> bool:
    if not isinstance(value, str) or not _TIMESTAMP.fullmatch(value):
        return False
    try:
        datetime.strptime(value, TIMESTAMP_FORMAT)
    except ValueError:
        return False
    return True


def validate_event(event: dict) -> None:
    """Raises InvalidEvent naming every rule the event breaks."""
    problems = []
    if set(event) != set(SCHEMA):
        problems.append(f"keys must be exactly {', '.join(SCHEMA)}")
    get = event.get
    for key, dtype in SCHEMA.items():
        value = get(key)
        if value is None and key not in NULLABLE:
            problems.append(f"{key} is missing")
        elif value is not None and dtype == pl.String and not isinstance(value, str):
            problems.append(f"{key} must be a string")
    for key in ("comment", "q5a_why_not_resolved"):
        if isinstance(get(key), str) and not get(key).strip():
            problems.append(f"{key} is blank; leave it null instead")
    checks = [
        (get("event_type") == EVENT_TYPE, f"event_type must be {EVENT_TYPE}"),
        (
            isinstance(get("survey_id"), str)
            and _SURVEY_ID.fullmatch(get("survey_id")),
            "survey_id must be ACS-YYYY-NNNNNN",
        ),
        (
            get("survey_channel") in CHANNELS,
            f"survey_channel must be one of {CHANNELS}",
        ),
        (
            _utc_timestamp(get("completed_at")),
            "completed_at must be UTC ISO",
        ),
        (_score(get("q1_ltr")), "q1_ltr must be an integer 0-10"),
        (
            get("q5_issue_resolved") in (None, *RESOLVED),
            f"q5 must be one of {RESOLVED}",
        ),
        (get("q6_main_reason") in (None, *MAIN_REASONS), "q6 is not a listed reason"),
        (
            get("callback_consent") in ("Yes", "No"),
            "callback_consent must be Yes or No",
        ),
        (get("escalated") in ("Y", "N"), "escalated must be Y or N"),
    ]
    problems += [message for ok, message in checks if not ok]
    for key in ("q2_agent_sat", "q3_explained_clearly", "q4_ease"):
        if get(key) is not None and not _score(get(key)):
            problems.append(f"{key} must be an integer 0-10")
    if get("q5a_why_not_resolved") is not None and get("q5_issue_resolved") not in (
        "No",
        "Partially",
    ):
        problems.append("q5a is only asked when Q5 is No or Partially")
    if (
        get("escalated") == "Y"
        and _score(get("q1_ltr"))
        and get("q1_ltr") > settings.DETRACTOR_MAX
    ):
        problems.append("only a detractor can be escalated")
    if problems:
        raise InvalidEvent(f"{get('survey_id')}: " + "; ".join(problems))


def write_events(events: Iterable[dict], path: Path) -> None:
    """One event per line, validated before anything is written."""
    events = list(events)
    for event in events:
        validate_event(event)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = (json.dumps(e, ensure_ascii=False, separators=(",", ":")) for e in events)
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def read_events(path: Path) -> list[dict]:
    events = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for event in events:
        validate_event(event)
    return events


def events_frame(events: Iterable[dict]) -> pl.DataFrame:
    """Events as a frame, `completed_at` as a UTC Datetime."""
    return pl.DataFrame(list(events), schema=SCHEMA).with_columns(
        pl.col("completed_at").str.to_datetime(TIMESTAMP_FORMAT, time_zone="UTC")
    )

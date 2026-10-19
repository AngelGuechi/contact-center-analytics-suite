"""Where the inputs live. The shared call detail is read, never written."""

from __future__ import annotations

from pathlib import Path

USE_CASE = Path(__file__).resolve().parents[3]  # 02-nps-driver-analyzer/
CALL_DETAIL = USE_CASE / "data" / "synthetic_call_detail.xlsx"
DATA = USE_CASE / "data"
ROSTER = DATA / "roster.csv"
CALL_CONTEXT = DATA / "call_context.csv"
SURVEY_EVENTS = DATA / "survey_events"  # synthetic Survey Event Feed, one file a day
ANSWER_KEY = DATA / "answer_key"  # never read by the pipeline; checks it

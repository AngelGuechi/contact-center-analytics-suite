"""Writes the synthetic Survey Event Feed and the Answer Key (data contract §1, §9)."""

from __future__ import annotations

import json
from pathlib import Path

from .. import paths
from ..events import write_events
from ..inputs import load_calls
from .findings import expected_findings, markdown
from .surveys import SEED, Generated, generate


def event_files(generated: Generated) -> dict[str, list[dict]]:
    """File name -> that business day's events, in completion order."""
    days: dict[str, list[dict]] = {}
    for s in generated.surveys:
        days.setdefault(f"survey_events_{s.day}.jsonl", []).append(s.event)
    return days


def answer_key_files(generated: Generated) -> dict[str, str]:
    """File name -> its full text."""
    surveys = sorted(generated.surveys, key=lambda s: s.survey_id)
    labels = [s.label for s in surveys if s.label]
    pii = [
        {
            "survey_id": s.survey_id,
            "field": "comment",
            "type": s.pii.type,
            "text": s.pii.text,
            "start": s.pii.start,
            "end": s.pii.end,
        }
        for s in surveys
        if s.pii
    ]
    findings = expected_findings(generated)

    def jsonl(rows):
        return "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows)

    return {
        "true_labels.jsonl": jsonl(labels),
        "pii_planted.jsonl": jsonl(pii),
        "expected_findings.json": json.dumps(findings, indent=2) + "\n",
        "expected_findings.md": markdown(findings),
    }


def write_all(
    seed: int = SEED,
    events_dir: Path = paths.SURVEY_EVENTS,
    key_dir: Path = paths.ANSWER_KEY,
) -> Generated:
    calls, _ = load_calls()
    generated = generate(calls, seed)
    files = event_files(generated)
    key = answer_key_files(generated)  # build everything before writing anything
    events_dir.mkdir(parents=True, exist_ok=True)
    for stale in events_dir.glob("survey_events_*.jsonl"):
        stale.unlink()
    for name, events in files.items():
        write_events(events, events_dir / name)
    key_dir.mkdir(parents=True, exist_ok=True)
    for name, text in key.items():
        (key_dir / name).write_text(text, encoding="utf-8")
    return generated

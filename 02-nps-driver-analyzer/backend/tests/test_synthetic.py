"""The synthetic surveys and their Answer Key (data contract §1, §9).

The Expected Findings are counted in plain Python by the generator; here the NPS
engine recomputes them from the written events and true Labels, so either side
going wrong fails a test.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import polars as pl
import pytest

from nps_pipeline import catalog, events, inputs, nps, paths, periods, settings
from nps_pipeline.synthetic import surveys as synthetic
from nps_pipeline.synthetic.write import answer_key_files, event_files

WRITTEN = (paths.ROSTER.exists() and paths.CALL_CONTEXT.exists()) and any(
    paths.SURVEY_EVENTS.glob("survey_events_*.jsonl")
)
pytestmark = pytest.mark.skipif(not WRITTEN, reason="run nps_pipeline.synthetic first")


@pytest.fixture(scope="module")
def calls() -> pl.DataFrame:
    return inputs.load_calls()[0]


@pytest.fixture(scope="module")
def written() -> list[dict]:
    files = sorted(paths.SURVEY_EVENTS.glob("survey_events_*.jsonl"))
    return [e for f in files for e in events.read_events(f)]


@pytest.fixture(scope="module")
def labels() -> dict[str, dict]:
    text = (paths.ANSWER_KEY / "true_labels.jsonl").read_text()
    rows = [json.loads(line) for line in text.splitlines()]
    return {r["survey_id"]: r for r in rows}


@pytest.fixture(scope="module")
def findings() -> dict[str, dict]:
    rows = json.loads((paths.ANSWER_KEY / "expected_findings.json").read_text())
    return {f["id"]: f for f in rows}


@pytest.fixture(scope="module")
def frame(written, labels, calls) -> pl.DataFrame:
    """One row per survey, as the engine reads it: event, call side, true Label."""
    label_rows = pl.DataFrame(
        list(labels.values()),
        schema={
            "survey_id": pl.String,
            "primary_driver": pl.String,
            "controllable": pl.String,
        },
        strict=False,
    )
    return (
        events.events_frame(written)
        .join(calls, left_on="transaction_id", right_on="transaction_id")
        .join(label_rows, on="survey_id", how="left")
        .with_columns(periods.business_date(pl.col("completed_at")).alias("day"))
    )


def test_the_written_files_match_a_rebuild(calls):
    generated = synthetic.generate(calls)
    for name, rows in event_files(generated).items():
        assert events.read_events(paths.SURVEY_EVENTS / name) == rows, name
    assert len(list(paths.SURVEY_EVENTS.glob("*.jsonl"))) == len(event_files(generated))
    for name, text in answer_key_files(generated).items():
        assert (paths.ANSWER_KEY / name).read_text() == text, name


def test_every_survey_joins_its_call(written, calls):
    by_id = {c["transaction_id"]: c for c in calls.to_dicts()}
    assert len({e["survey_id"] for e in written}) == len(written)
    assert len({e["transaction_id"] for e in written}) == len(written)
    for e in written:
        call = by_id[e["transaction_id"]]
        assert e["agent_login_id"] == call["login_id"]
        done = datetime.strptime(e["completed_at"], events.TIMESTAMP_FORMAT)
        ended = call["call_started_at"] + timedelta(seconds=call["handle_seconds"])
        assert done.replace(tzinfo=UTC) > ended, e["survey_id"]


def test_each_file_holds_one_business_day_in_order(frame):
    for path in sorted(paths.SURVEY_EVENTS.glob("survey_events_*.jsonl")):
        day = date.fromisoformat(path.stem.removeprefix("survey_events_"))
        rows = events.events_frame(events.read_events(path)).with_columns(
            periods.business_date(pl.col("completed_at")).alias("day")
        )
        assert rows["day"].unique().to_list() == [day]
        assert rows["completed_at"].is_sorted()
    assert frame["day"].max() <= synthetic.LAST_DAY


def test_volumes_follow_the_august_rates(frame, calls):
    total = round(synthetic.SURVEY_RATE * calls.height)
    groups = nps.nps_by(frame).row(0, named=True)
    detractors = round(synthetic.DETRACTOR_RATE * total)
    assert (groups["surveys"], groups["detractors"]) == (total, detractors)
    escalated = frame.filter(pl.col("escalated") == "Y")
    assert escalated.height == round(synthetic.ESCALATED_RATE * detractors)
    assert (escalated[settings.NPS_SCORE_FIELD] <= settings.DETRACTOR_MAX).all()


def test_labels_cover_exactly_the_surveys_with_a_verbatim(frame, labels):
    with_verbatim = frame.filter(nps.has_verbatim())["survey_id"].to_list()
    assert sorted(with_verbatim) == sorted(labels)
    for label in labels.values():
        catalog.validate_label(
            label["primary_driver"],
            label["secondary_driver"],
            label["sentiment"],
            label["controllable"],
        )


def test_the_verbatims_cover_what_the_data_needs(labels, frame):
    rows = list(labels.values())
    buckets = {catalog.BUCKET_OF[r["primary_driver"]] for r in rows}
    assert buckets == set(catalog.BUCKETS)
    assert any(r["controllable"] == "partly" for r in rows)
    assert any(r["secondary_driver"] for r in rows)
    promoters = frame.filter(pl.col(settings.NPS_SCORE_FIELD) >= 9)["survey_id"]
    assert any(sid in labels for sid in promoters)
    q5a_only = frame.filter(
        pl.col("comment").is_null() & pl.col("q5a_why_not_resolved").is_not_null()
    )
    assert q5a_only.height >= 1


def test_only_f7_contradicts_its_main_reason(written, labels, findings):
    flagged = sorted(
        e["survey_id"]
        for e in written
        if e["survey_id"] in labels
        and catalog.contradicts_reason(
            labels[e["survey_id"]]["primary_driver"], e["q6_main_reason"]
        )
    )
    assert flagged == findings["F7"]["survey_ids"]
    assert all("F7" in labels[sid]["patterns"] for sid in flagged)


def test_planted_pii_sits_where_the_key_says(written, findings):
    comments = {e["survey_id"]: e["comment"] for e in written}
    text = (paths.ANSWER_KEY / "pii_planted.jsonl").read_text()
    rows = [json.loads(line) for line in text.splitlines()]
    assert sorted(r["survey_id"] for r in rows) == findings["F8"]["survey_ids"]
    assert {r["type"] for r in rows} == set(synthetic.v.PII_TYPES)
    for r in rows:
        assert comments[r["survey_id"]][r["start"] : r["end"]] == r["text"]


def detractors(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.filter(pl.col(settings.NPS_SCORE_FIELD) <= settings.DETRACTOR_MAX)


def window(frame: pl.DataFrame, start: str, end: str) -> pl.DataFrame:
    w = periods.Window("w", date.fromisoformat(start), date.fromisoformat(end))
    return frame.filter(periods.in_window(pl.col("day"), w))


@pytest.mark.parametrize("finding_id", ["F1", "F1-WTD"])
def test_f1_credit_detractors_rise(frame, findings, finding_id):
    numbers = findings[finding_id]["numbers"]
    for side in ("before", "after"):
        rows = window(frame, numbers[side]["from"], numbers[side]["to"])
        credit = rows.filter(pl.col("call_type") == "Credit")
        assert nps.nps_by(rows)["detractors"].item() == numbers["detractors"][side]
        assert (
            nps.nps_by(credit)["detractors"].item()
            == (numbers["credit_detractors"][side])
        )
        high_bill = detractors(credit).filter(
            (pl.col("primary_driver") == "CUS_HIGH_BILL")
            & (pl.col("controllable") == "no")
        )
        assert high_bill.height == numbers["credit_high_bill_not_controllable"][side]
    after = numbers["credit_detractors"]["after"]
    assert after > numbers["credit_detractors"]["before"]
    assert numbers["credit_high_bill_not_controllable"]["after"] * 2 > after


def test_f2_and_f3_are_system_detractors_on_their_day(frame, findings):
    for finding_id, driver in (("F2", "SYS_PORTAL"), ("F3", "SYS_VIRTUAL_ASSISTANT")):
        numbers = findings[finding_id]["numbers"]
        day = window(frame, numbers["day"], numbers["day"])
        breakdown = nps.detractor_breakdown(day).row(0, named=True)
        assert breakdown["detractors"] == numbers["detractors"]
        hits = detractors(day).filter(pl.col("primary_driver") == driver)
        assert sorted(hits["survey_id"]) == findings[finding_id]["survey_ids"]
        assert breakdown[catalog.SYSTEM] >= hits.height
        assert (hits["controllable"] == "no").all()
    va = frame.filter(pl.col("survey_id").is_in(findings["F3"]["survey_ids"]))
    assert (va["virtual_assistant_used"] == "Y").all()


def test_f4_two_agents_pull_their_team_down(frame, findings):
    numbers = findings["F4"]["numbers"]
    mtd = window(frame, numbers["window"]["from"], numbers["window"]["to"])
    teams = {r["supervisor"]: r for r in nps.nps_by(mtd, ["supervisor"]).to_dicts()}
    team = teams.pop(numbers["supervisor"])
    assert team["nps"] == pytest.approx(numbers["team"]["nps"])
    assert team["surveys"] == numbers["team"]["surveys"]
    assert all(team["nps"] < other["nps"] for other in teams.values())
    rest = mtd.filter(
        (pl.col("supervisor") == numbers["supervisor"])
        & ~pl.col("login_id").is_in(list(numbers["agents"]))
    )
    assert nps.nps_by(rest)["nps"].item() == pytest.approx(
        numbers["team_without_the_two"]["nps"]
    )
    for login, agent in numbers["agents"].items():
        own = mtd.filter(pl.col("login_id") == login)
        assert nps.nps_by(own)["nps"].item() == pytest.approx(agent["nps"])
        cnps = nps.controllable_nps_by(own).row(0, named=True)
        assert cnps["not_controllable_detractors"] == 0  # every one is the agent's


def test_f5_partly_detractors_stay_counted(frame, findings):
    partly = frame.filter(pl.col("survey_id").is_in(findings["F5"]["survey_ids"]))
    before = nps.nps_by(partly)["detractors"].item()
    after = nps.controllable_nps_by(partly).row(0, named=True)
    assert (
        before
        == after["detractors"]
        == findings["F5"]["numbers"]["high_bill_not_explained"]
    )


def test_f6_detractors_without_a_verbatim_stay_counted(frame, findings):
    numbers = findings["F6"]["numbers"]
    full = nps.detractor_breakdown(frame).row(0, named=True)
    assert (full["detractors"], full[nps.NO_COMMENT]) == (
        numbers["aug_3_17"]["detractors"],
        numbers["aug_3_17"]["no_verbatim"],
    )
    assert full[nps.UNLABELED] == 0
    assert sum(full[s] for s in nps.SEGMENTS) == full["detractors"]
    mtd = nps.detractor_breakdown(window(frame, "2026-08-01", "2026-08-14"))
    assert mtd[nps.NO_COMMENT].item() == numbers["mtd"]["no_verbatim"]


def test_f9_one_agent_only_gets_promoters(frame, findings):
    numbers = findings["F9"]["numbers"]
    mtd = window(frame, "2026-08-01", "2026-08-14")
    own = nps.nps_by(mtd.filter(pl.col("login_id") == numbers["login_id"]))
    assert own["nps"].item() == pytest.approx(100.0)
    assert own["surveys"].item() == numbers["mtd"]["surveys"]


def test_controllable_nps_moves_only_labelled_not_controllable_detractors(
    frame, labels
):
    expected = sum(
        1
        for sid, label in labels.items()
        if label["controllable"] == "no"
        and frame.filter(pl.col("survey_id") == sid)[settings.NPS_SCORE_FIELD].item()
        <= settings.DETRACTOR_MAX
    )
    for rule in settings.CONTROLLABLE_RULES:
        row = nps.controllable_nps_by(frame, rule=rule).row(0, named=True)
        assert row["not_controllable_detractors"] == expected
        assert row["surveys_answered"] == frame.height

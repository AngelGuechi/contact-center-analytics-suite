"""AHT engine against the README worked example and hand-computed edge cases."""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from aht_pipeline import aht, settings

TODAY = date(2026, 8, 14)


def make(*calls: tuple) -> pl.DataFrame:
    """Calls as (login, CDMX local start "YYYY-MM-DD HH:MM", talk, hold, wrap[, extra]).

    `extra` is a dict of grouping columns (supervisor, call_type, ...) for that call.
    """
    rows = []
    for i, (login, start, talk, hold, wrap, *extra) in enumerate(calls):
        rows.append(
            {
                "transaction_id": f"TXN{i:04}",
                "login_id": login,
                "start": start,
                "talk_seconds": talk,
                "hold_seconds": hold,
                "wrap_seconds": wrap,
                **(extra[0] if extra else {}),
            }
        )
    return (
        pl.DataFrame(rows)
        .with_columns(
            pl.col("start")
            .str.to_datetime("%Y-%m-%d %H:%M")
            .dt.replace_time_zone(settings.BUSINESS_TIMEZONE)
            .dt.convert_time_zone("UTC")
            .alias("call_started_at")
        )
        .drop("start")
    )


def one(df: pl.DataFrame) -> dict:
    assert len(df) == 1
    return df.row(0, named=True)


def by_key(df: pl.DataFrame, key: str) -> dict:
    return {row[key]: row for row in df.iter_rows(named=True)}


# ------------------------------------------------------------------ aht_by
def test_readme_example_is_650_not_750():
    """README: A handles 10 calls at 600s and B 2 calls at 900s, on one team."""
    team = {"supervisor": "S1"}
    calls = make(
        *[("A", "2026-08-14 09:00", 600, 0, 0, team)] * 10,
        *[("B", "2026-08-14 09:00", 900, 0, 0, team)] * 2,
    )
    agents = by_key(aht.aht_by(calls, ["login_id"]), "login_id")
    assert (agents["A"]["aht"], agents["B"]["aht"]) == (600, 900)
    supervisor = one(aht.aht_by(calls, ["supervisor"]))
    assert supervisor["aht"] == 650  # (6,000 + 1,800) / 12, never (600 + 900) / 2
    assert (supervisor["calls"], supervisor["handle_seconds"]) == (12, 7800)


def test_talk_hold_and_wrap_per_call_add_up_to_aht():
    r = one(
        aht.aht_by(
            make(
                ("A", "2026-08-14 09:00", 500, 30, 70),
                ("A", "2026-08-14 10:00", 400, 0, 41),
            )
        )
    )
    assert (r["aht_talk"], r["aht_hold"], r["aht_wrap"]) == (450, 15, 55.5)
    assert r["aht_talk"] + r["aht_hold"] + r["aht_wrap"] == r["aht"] == 520.5


@pytest.mark.parametrize(("seconds", "above", "gap"), [(640, False, 0), (641, True, 1)])
def test_the_alert_is_strictly_above_640(seconds, above, gap):
    r = one(aht.aht_by(make(("A", "2026-08-14 09:00", seconds, 0, 0))))
    assert (r["alert_seconds"], r["above_alert"], r["gap_to_alert"]) == (
        640,
        above,
        gap,
    )


def test_per_call_type_thresholds_follow_the_call_mix(monkeypatch):
    calls = make(
        ("A", "2026-08-14 09:00", 700, 0, 0, {"call_type": "Credit"}),
        ("A", "2026-08-14 10:00", 620, 0, 0, {"call_type": "NEM"}),
    )
    assert one(aht.aht_by(calls))["above_alert"]  # 660s against a flat 640s
    monkeypatch.setattr(settings, "ALERT_SECONDS_BY_CALL_TYPE", {"Credit": 700})
    r = one(aht.aht_by(calls))
    assert (r["alert_seconds"], r["above_alert"], r["gap_to_alert"]) == (
        670,
        False,
        -10,
    )


def test_no_calls_gives_null_aht_and_no_alert():
    r = one(aht.aht_by(make(("A", "2026-08-14 09:00", 600, 0, 0)).clear()))
    assert (r["calls"], r["aht"], r["above_alert"]) == (0, None, False)


def test_a_repeated_call_is_rejected():
    calls = make(
        ("A", "2026-08-14 09:00", 600, 0, 0), ("A", "2026-08-14 09:00", 600, 0, 0)
    )
    calls = calls.with_columns(pl.lit("TXN1").alias("transaction_id"))
    with pytest.raises(ValueError, match="transaction_id repeated: TXN1"):
        aht.aht_by(calls)


def test_negative_or_fractional_seconds_are_rejected():
    with pytest.raises(ValueError, match="talk_seconds missing or negative"):
        aht.aht_by(make(("A", "2026-08-14 09:00", -1, 0, 0)))
    calls = make(("A", "2026-08-14 09:00", 600, 0, 0))
    with pytest.raises(ValueError, match="hold_seconds must be whole seconds"):
        aht.aht_by(calls.with_columns(pl.col("hold_seconds").cast(pl.Float64)))


# ------------------------------------------------------------------ board
def test_board_puts_today_yesterday_and_mtd_side_by_side():
    calls = make(
        ("A", "2026-08-14 09:00", 700, 0, 0),
        ("A", "2026-08-14 10:00", 600, 0, 0),
        ("A", "2026-08-13 09:00", 610, 0, 0),
        ("A", "2026-08-03 09:00", 590, 0, 0),
        ("A", "2026-07-31 09:00", 9999, 0, 0),  # last month: in no window
    )
    r = one(aht.board(calls, TODAY, ["login_id"]))
    assert (r["calls_today"], r["aht_today"]) == (2, 650)
    assert (r["calls_yesterday"], r["aht_yesterday"]) == (1, 610)
    assert (r["calls_mtd"], r["aht_mtd"]) == (4, 625)
    assert (r["vs_yesterday"], r["vs_mtd"]) == (40, 25)  # positive: longer, worse
    assert (r["gap_to_alert"], r["above_alert"]) == (10, True)


def test_a_late_call_counts_on_its_cdmx_day():
    # 23:30 in CDMX is 05:30 UTC the next day; it still belongs to the 14th
    r = one(aht.board(make(("A", "2026-08-14 23:30", 600, 0, 0)), TODAY))
    assert r["calls_today"] == 1


@pytest.mark.parametrize(
    ("earlier", "kind"),
    [
        ([("2026-08-05 09:00", 700), ("2026-08-12 09:00", 680)], "pattern"),
        ([("2026-08-05 09:00", 600), ("2026-08-12 09:00", 610)], "spike"),
        ([("2026-07-31 09:00", 700)], "no history"),  # nothing earlier this month
    ],
)
def test_alert_kind_judges_today_against_the_month_before_today(earlier, kind):
    calls = make(
        ("A", "2026-08-14 09:00", 742, 0, 0),
        *[("A", start, seconds, 0, 0) for start, seconds in earlier],
    )
    assert one(aht.board(calls, TODAY))["alert_kind"] == kind


def test_alert_kind_is_null_when_not_above_alert():
    calls = make(
        ("A", "2026-08-14 09:00", 600, 0, 0), ("A", "2026-08-05 09:00", 700, 0, 0)
    )
    r = one(aht.board(calls, TODAY))
    assert (r["above_alert"], r["alert_kind"]) == (False, None)


def test_an_agent_without_calls_today_is_listed_last_and_never_flagged():
    calls = make(
        ("A", "2026-08-14 09:00", 600, 0, 0),
        ("B", "2026-08-13 09:00", 900, 0, 0),  # only yesterday
        ("C", "2026-08-14 09:00", 700, 0, 0),
    )
    board = aht.board(calls, TODAY, ["login_id"])
    assert board["login_id"].to_list() == ["C", "A", "B"]  # worst gap first
    b = by_key(board, "login_id")["B"]
    assert (b["calls_today"], b["aht_today"], b["above_alert"], b["alert_kind"]) == (
        0,
        None,
        False,
        None,
    )
    assert (b["calls_yesterday"], b["aht_yesterday"]) == (1, 900)


def test_board_on_the_first_of_the_month():
    calls = make(
        ("A", "2026-09-01 09:00", 700, 0, 0), ("A", "2026-08-31 09:00", 500, 0, 0)
    )
    r = one(aht.board(calls, date(2026, 9, 1)))
    assert (r["aht_yesterday"], r["calls_mtd"], r["aht_mtd"]) == (500, 1, 700)
    assert r["alert_kind"] == "no history"


def test_supervisor_board_pools_its_agents():
    team = {"supervisor": "S1"}
    calls = make(
        *[("A", "2026-08-14 09:00", 600, 0, 0, team)] * 10,
        *[("B", "2026-08-14 09:00", 900, 0, 0, team)] * 2,
    )
    r = one(aht.board(calls, TODAY, ["supervisor"]))
    assert (r["supervisor"], r["calls_today"], r["aht_today"]) == ("S1", 12, 650)


def test_site_board_is_one_row_even_without_calls():
    r = one(aht.board(make(("A", "2026-07-01 09:00", 600, 0, 0)), TODAY))
    assert (r["calls_today"], r["aht_today"], r["above_alert"]) == (0, None, False)


# ------------------------------------------------------------------ intraday
def test_intraday_puts_each_hour_of_today_beside_yesterday():
    calls = make(
        ("A", "2026-08-14 09:10", 600, 0, 0),
        ("A", "2026-08-14 09:50", 700, 0, 0),
        ("A", "2026-08-14 23:30", 500, 0, 0),  # 05:30 UTC on the 15th
        ("A", "2026-08-13 09:20", 640, 0, 0),
        ("A", "2026-08-13 10:00", 620, 0, 0),
    )
    hours = by_key(aht.intraday(calls, TODAY), "hour")
    assert sorted(hours) == [9, 10, 23]
    assert (
        hours[9]["calls_today"],
        hours[9]["aht_today"],
        hours[9]["aht_yesterday"],
    ) == (
        2,
        650,
        640,
    )
    assert (
        hours[10]["calls_today"],
        hours[10]["aht_today"],
        hours[10]["calls_yesterday"],
    ) == (
        0,
        None,
        1,
    )
    assert (hours[23]["calls_today"], hours[23]["calls_yesterday"]) == (1, 0)

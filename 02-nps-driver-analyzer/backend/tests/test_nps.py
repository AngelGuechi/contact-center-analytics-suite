"""NPS engine against the README worked examples and hand-computed edge cases."""

from __future__ import annotations

import polars as pl
import pytest

from nps_pipeline import nps, settings

FIELD = settings.NPS_SCORE_FIELD
PROMOTERS, PASSIVES, DETRACTORS = [10, 9, 10, 9, 10], [7, 8, 8], [3, 5]


def make(scores: list[int], **cols) -> pl.DataFrame:
    """A survey frame. Column values are lists, or a scalar repeated on every row."""
    n = len(scores)
    base = {
        "survey_id": [f"S{i:03}" for i in range(n)],
        FIELD: scores,
        "controllable": None,
        "primary_driver": None,
        "comment": None,
        "q5a_why_not_resolved": None,
    }
    base.update(cols)
    data = {k: v if isinstance(v, list) else [v] * n for k, v in base.items()}
    return pl.DataFrame(
        data,
        schema_overrides={k: pl.Int64 if k == FIELD else pl.String for k in base},
    )


def one(df: pl.DataFrame) -> dict:
    assert len(df) == 1
    return df.row(0, named=True)


def readme_ten(controllable_of_first_detractor: str | None = None) -> pl.DataFrame:
    """README: 5 promoters, 3 passives, 2 detractors; the first is high bill."""
    controllable = [None] * 8 + [controllable_of_first_detractor, None]
    return make(PROMOTERS + PASSIVES + DETRACTORS, controllable=controllable)


# ------------------------------------------------------------------ plain NPS
def test_readme_example_is_plus_30():
    r = one(nps.nps_by(readme_ten()))
    assert (r["surveys"], r["promoters"], r["passives"], r["detractors"]) == (
        10,
        5,
        3,
        2,
    )
    assert r["nps"] == 30


@pytest.mark.parametrize(
    ("score", "group"),
    [
        (0, "detractor"),
        (6, "detractor"),
        (7, "passive"),
        (8, "passive"),
        (9, "promoter"),
        (10, "promoter"),
    ],
)
def test_score_boundaries(score, group):
    r = one(nps.nps_by(make([score])))
    assert r[f"{group}s"] == 1


def test_low_sample_flag_under_ten_surveys():
    assert settings.MIN_SAMPLE == 10  # README: under 10 surveys is "low sample"
    assert one(nps.nps_by(make([10] * 9)))["low_sample"] is True
    assert one(nps.nps_by(make([10] * 10)))["low_sample"] is False


def test_three_surveys_minus_33_is_flagged_low_sample():
    r = one(nps.nps_by(make([10, 3, 4])))
    assert r["nps"] == pytest.approx(-100 / 3)
    assert r["low_sample"] is True


def test_no_surveys_gives_null_nps():
    r = one(nps.nps_by(make([])))
    assert r["surveys"] == 0
    assert r["nps"] is None


def test_repeated_survey_id_is_rejected():
    df = make([10, 3], survey_id="S1")
    with pytest.raises(ValueError, match="survey_id repeated: S1"):
        nps.nps_by(df)


@pytest.mark.parametrize("bad", [11, -1, None])
def test_score_outside_scale_is_rejected(bad):
    with pytest.raises(ValueError, match="outside 0-10"):
        nps.nps_by(make([10, bad]))


def test_score_that_is_not_an_integer_is_rejected():
    with pytest.raises(ValueError, match="integer"):
        nps.nps_by(make([10, 6]).with_columns(pl.col(FIELD).cast(pl.Float64) + 0.5))


# ------------------------------------------------------------------ pooling
def test_readme_pooling_example_is_plus_10_not_plus_50():
    agent_a = make([10, 10], agent=["A"] * 2)
    agent_b = make([10] * 6 + [8] * 6 + [3] * 6, agent=["B"] * 18).with_columns(
        pl.col("survey_id") + "b"
    )
    team = pl.concat([agent_a, agent_b]).with_columns(supervisor=pl.lit("Sup 1"))

    agents = nps.nps_by(team, by=["agent"])
    assert agents["nps"].to_list() == [100, 0]
    assert agents["surveys"].to_list() == [2, 18]

    sup = one(nps.nps_by(team, by=["supervisor"]))
    assert sup["surveys"] == 20
    assert sup["nps"] == 10
    assert sup["nps"] != agents["nps"].mean()  # the average of agents would say +50


def test_manager_and_site_pool_their_surveys_too():
    # Sup 1: 2 surveys, +100. Sup 2: 18 surveys, 0. Same manager, same site.
    team = make(
        [10, 10] + [10] * 6 + [8] * 6 + [3] * 6,
        supervisor=["Sup 1"] * 2 + ["Sup 2"] * 18,
        manager="Mgr 1",
        site="MTY",
    )
    for level in ("manager", "site"):
        r = one(nps.nps_by(team, by=[level]))
        assert (r["surveys"], r["nps"]) == (20, 10)


def test_agent_missing_a_supervisor_stays_visible_as_null_group():
    df = make([10, 3], supervisor=["Sup 1", None])
    out = nps.nps_by(df, by=["supervisor"])
    assert out["supervisor"].to_list() == ["Sup 1", None]
    assert out["surveys"].sum() == 2


# ------------------------------------------------------------------ controllable NPS
def test_readme_controllable_drop_is_plus_44():
    r = one(nps.controllable_nps_by(readme_ten("no"), rule="drop"))
    assert (r["surveys"], r["promoters"], r["detractors"]) == (9, 5, 1)
    assert r["nps"] == pytest.approx(400 / 9)  # +44
    assert r["not_controllable_detractors"] == 1
    assert r["rule"] == "drop"


def test_controllable_low_sample_counts_the_dropped_surveys_too():
    # +44 sits on 9 surveys after the drop, but the agent answered 10: same flag as +30
    r = one(nps.controllable_nps_by(readme_ten("no"), rule="drop"))
    assert (r["surveys"], r["surveys_answered"], r["low_sample"]) == (9, 10, False)
    assert one(nps.nps_by(readme_ten()))["low_sample"] is False


def test_readme_controllable_reclassify_is_plus_40():
    r = one(nps.controllable_nps_by(readme_ten("no"), rule="reclassify"))
    assert (r["surveys"], r["passives"], r["detractors"]) == (10, 4, 1)
    assert r["nps"] == 40
    assert r["rule"] == "reclassify"


def test_default_rule_is_drop():
    assert settings.CONTROLLABLE_RULE == "drop"  # README: drop is the default
    r = one(nps.controllable_nps_by(readme_ten("no")))
    assert (r["rule"], r["nps"]) == ("drop", pytest.approx(400 / 9))


def test_partly_detractor_stays_against_the_agent():
    r = one(nps.controllable_nps_by(readme_ten("partly")))
    assert r["detractors"] == 2
    assert r["nps"] == 30


def test_partly_moves_when_setting_is_off(monkeypatch):
    monkeypatch.setattr(settings, "PARTLY_COUNTS_AGAINST_AGENT", False)
    r = one(nps.controllable_nps_by(readme_ten("partly"), rule="drop"))
    assert r["not_controllable_detractors"] == 1
    assert r["nps"] == pytest.approx(400 / 9)


def test_partly_reclassified_when_setting_is_off(monkeypatch):
    monkeypatch.setattr(settings, "PARTLY_COUNTS_AGAINST_AGENT", False)
    r = one(nps.controllable_nps_by(readme_ten("partly"), rule="reclassify"))
    assert (r["passives"], r["detractors"], r["nps"]) == (4, 1, 40)


@pytest.mark.parametrize("bad", ["No", "maybe", ""])
def test_controllable_outside_yes_no_partly_is_rejected(bad):
    with pytest.raises(ValueError, match="controllable not allowed"):
        nps.controllable_nps_by(readme_ten(bad))


def test_unlabeled_detractor_stays_counted():
    r = one(nps.controllable_nps_by(readme_ten(None)))
    assert r["detractors"] == 2
    assert r["nps"] == 30


def test_non_controllable_promoter_label_changes_nothing():
    df = make([10, 3], controllable=["no", None])
    r = one(nps.controllable_nps_by(df))
    assert (r["promoters"], r["detractors"], r["not_controllable_detractors"]) == (
        1,
        1,
        0,
    )


def test_group_keeps_its_row_when_drop_empties_it():
    df = make([3, 10], agent=["A", "B"], controllable=["no", None])
    out = nps.controllable_nps_by(df, by=["agent"], rule="drop")
    a = out.filter(pl.col("agent") == "A").row(0, named=True)
    assert (a["surveys"], a["surveys_answered"], a["nps"]) == (0, 1, None)
    assert a["low_sample"] is True


def test_unknown_rule_is_rejected():
    with pytest.raises(ValueError, match="unknown controllable rule"):
        nps.controllable_nps_by(readme_ten(), rule="ignore")


# ------------------------------------------------------------------ driver breakdown
def breakdown_frame() -> pl.DataFrame:
    return make(
        [3, 5, 0, 6, 4, 10],
        primary_driver=[
            "CUS_HIGH_BILL",
            "SYS_PORTAL",
            "AGT_COURTESY",
            None,
            None,
            "AGT_EMPATHY",
        ],
        comment=["bill", "portal", "rude", None, "text but no label", "kind"],
        team=["T1", "T1", "T2", "T2", "T1", "T1"],
    )


def test_breakdown_segments_add_up_to_every_detractor():
    r = one(nps.detractor_breakdown(breakdown_frame()))
    assert r["detractors"] == 5  # the promoter is left out
    assert sum(r[s] for s in nps.SEGMENTS) == 5
    assert (r["Customer"], r["System"], r["Agent"], r["Process / Policy"]) == (
        1,
        1,
        1,
        0,
    )
    assert (r[nps.NO_COMMENT], r[nps.UNLABELED]) == (1, 1)


def test_breakdown_by_group():
    out = nps.detractor_breakdown(breakdown_frame(), by=["team"])
    t1, t2 = out.rows(named=True)
    assert (t1["team"], t1["detractors"], t1[nps.UNLABELED]) == ("T1", 3, 1)
    assert (t2["team"], t2["detractors"], t2[nps.NO_COMMENT]) == ("T2", 2, 1)


def test_group_without_detractors_keeps_its_row_with_zeros():
    df = make([3, 10], team=["T1", "T2"], comment=["bill", None])
    out = nps.detractor_breakdown(df, by=["team"])
    t2 = out.filter(pl.col("team") == "T2").row(0, named=True)
    assert t2["detractors"] == sum(t2[s] for s in nps.SEGMENTS) == 0


def test_q5a_answer_alone_is_a_verbatim():
    df = make(
        [3], q5a_why_not_resolved="still waiting", primary_driver="AGT_RESOLUTION"
    )
    assert one(nps.detractor_breakdown(df))["Agent"] == 1


def test_blank_comment_counts_as_no_comment():
    df = make([3], comment="   ")
    assert one(nps.detractor_breakdown(df))[nps.NO_COMMENT] == 1


def test_driver_outside_catalog_is_rejected():
    df = make([3], comment="x", primary_driver="AGT_RUDE")
    with pytest.raises(ValueError, match="primary_driver not allowed: AGT_RUDE"):
        nps.detractor_breakdown(df)

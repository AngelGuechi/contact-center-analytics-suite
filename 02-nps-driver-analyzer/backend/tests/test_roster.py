"""The local roster: shape from data contract §4, and the file round trip."""

from __future__ import annotations

import polars as pl
import pytest

from nps_pipeline import roster


def agents(n: int = 42) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "login_id": [f"U2000{i:02}" for i in range(n)],
            "agent_name": [f"Agent {i}" for i in range(n)],
        }
    )


def test_the_hierarchy_the_contract_asks_for():
    r = roster.build_roster(agents())
    assert r.height == r["login_id"].n_unique() == 42
    sizes = r.group_by("supervisor").len()["len"].sort().to_list()
    assert sizes == [10, 10, 11, 11]
    assert r["manager"].n_unique() == 2
    assert r["delivery_manager"].n_unique() == 1
    per_team = r.group_by("supervisor").agg(pl.col("manager", "site").n_unique())
    assert per_team["manager"].max() == per_team["site"].max() == 1  # one each
    assert sorted(r["site"].unique()) == sorted(roster.SITES)


def test_same_seed_same_roster_and_one_row_per_agent_from_calls():
    per_call = pl.concat([agents(), agents()])  # each agent on two calls
    assert roster.build_roster(per_call).equals(roster.build_roster(agents()))


def test_build_rejects_two_names_for_one_login_or_a_wrong_headcount():
    two_names = pl.concat([agents(), agents(1).with_columns(agent_name=pl.lit("X"))])
    with pytest.raises(ValueError, match="more than one name"):
        roster.build_roster(two_names)
    with pytest.raises(ValueError, match="got 41"):
        roster.build_roster(agents(41))


def test_round_trip_through_the_csv(tmp_path):
    path = tmp_path / "roster.csv"
    built = roster.build_roster(agents())
    roster.write_roster(built, path)
    assert pl.read_csv(path).columns == list(roster.HEADERS)
    assert roster.read_roster(path).equals(built)


def test_read_rejects_a_repeated_login_or_an_unknown_site(tmp_path):
    path = tmp_path / "roster.csv"
    built = roster.build_roster(agents())
    roster.write_roster(pl.concat([built, built.head(1)]), path)
    with pytest.raises(ValueError, match="repeats"):
        roster.read_roster(path)
    roster.write_roster(built.with_columns(site=pl.lit("TIJ")), path)
    with pytest.raises(ValueError, match="Site"):
        roster.read_roster(path)

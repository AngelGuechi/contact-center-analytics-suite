"""The local roster (data contract §4): agent -> supervisor -> manager -> site.

Rollups and displayed names come from here, never from the call detail, whose
`Supervisor`, `Team` and `Site` change from call to call. The file keeps the
contract's Excel-style headers; in code the columns are snake_case.
"""

from __future__ import annotations

import random
from pathlib import Path

import polars as pl

from . import paths

SITES = ("MTY", "GDL", "CDMX")
STATUSES = ("Active",)
HEADERS = {
    "Login ID": "login_id",
    "Agent Name": "agent_name",
    "Supervisor": "supervisor",
    "Manager": "manager",
    "Delivery Manager": "delivery_manager",
    "Site": "site",
    "Status": "status",
}

# Synthetic hierarchy: 4 teams, each in one site, 2 managers, 1 delivery manager.
DELIVERY_MANAGER = "Patricia Rojas"
TEAMS = (  # supervisor, manager, site, team size
    ("Andrea Navarro", "Laura Medina", "MTY", 11),
    ("Carlos Ibarra", "Laura Medina", "MTY", 11),
    ("Daniela Fuentes", "Ricardo Ortega", "GDL", 10),
    ("Jorge Salinas", "Ricardo Ortega", "CDMX", 10),
)
SEED = 2026


def build_roster(agents: pl.DataFrame, seed: int = SEED) -> pl.DataFrame:
    """Deal the agents (`login_id`, `agent_name`, one row per call or per agent)
    into the synthetic teams. The same agents and seed give the same roster."""
    agents = agents.unique(["login_id", "agent_name"]).sort("login_id")
    if agents["login_id"].is_duplicated().any():
        raise ValueError("an agent login has more than one name")
    if agents.height != sum(size for *_, size in TEAMS):
        raise ValueError(
            f"the teams hold {sum(s for *_, s in TEAMS)} agents, got {agents.height}"
        )
    logins = agents["login_id"].to_list()
    random.Random(seed).shuffle(logins)

    rows, taken = [], 0
    for supervisor, manager, site, size in TEAMS:
        rows += [
            {
                "login_id": login,
                "supervisor": supervisor,
                "manager": manager,
                "delivery_manager": DELIVERY_MANAGER,
                "site": site,
                "status": "Active",
            }
            for login in logins[taken : taken + size]
        ]
        taken += size
    teams = pl.DataFrame(rows)
    return agents.join(teams, on="login_id").select(HEADERS.values()).sort("login_id")


def write_roster(roster: pl.DataFrame, path: Path = paths.ROSTER) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    roster.rename({v: k for k, v in HEADERS.items()}).write_csv(path)


def read_roster(path: Path = paths.ROSTER) -> pl.DataFrame:
    roster = pl.read_csv(path, schema={k: pl.String for k in HEADERS}).rename(HEADERS)
    if roster.null_count().sum_horizontal().item():
        raise ValueError("roster has blank cells")
    if roster["login_id"].is_duplicated().any():
        raise ValueError("roster repeats a Login ID")
    if not roster["site"].is_in(SITES).all():
        raise ValueError(f"roster Site must be one of {', '.join(SITES)}")
    if not roster["status"].is_in(STATUSES).all():
        raise ValueError(f"roster Status must be one of {', '.join(STATUSES)}")
    return roster

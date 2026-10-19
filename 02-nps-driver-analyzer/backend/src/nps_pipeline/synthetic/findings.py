"""Expected Findings (data contract §9): what the analysis must say about each
Planted Pattern, with its exact numbers.

Counted here in plain Python from the generated surveys, on purpose apart from
`nps.py`, so the tests can check the engine against an independent count.
"""

from __future__ import annotations

from collections import Counter
from datetime import date

from .. import settings
from ..catalog import contradicts_reason
from .surveys import F4_SUPERVISOR, Generated, Survey
from .verbatims import PII_TYPES

DEMO_DAY = date(2026, 8, 14)
WEEKS = ((date(2026, 8, 3), date(2026, 8, 9)), (date(2026, 8, 10), date(2026, 8, 16)))
WTDS = ((date(2026, 8, 3), date(2026, 8, 7)), (date(2026, 8, 10), DEMO_DAY))
MTD = (date(2026, 8, 1), DEMO_DAY)
YESTERDAY = date(2026, 8, 13)
F3_DAY = date(2026, 8, 11)


def _group(s: Survey) -> str:
    score = s.event[settings.NPS_SCORE_FIELD]
    if score >= settings.PROMOTER_MIN:
        return "promoter"
    return "detractor" if score <= settings.DETRACTOR_MAX else "passive"


def _detractor(s: Survey) -> bool:
    return _group(s) == "detractor"


def _within(surveys, window) -> list[Survey]:
    return [s for s in surveys if window[0] <= s.day <= window[1]]


def _span(window) -> str:
    return f"{window[0]:%b} {window[0].day}-{window[1].day}"


def _nps(surveys) -> dict:
    c = Counter(_group(s) for s in surveys)
    n = len(surveys)
    nps = (c["promoter"] - c["detractor"]) * 100 / n if n else None
    return {
        "surveys": n,
        "promoters": c["promoter"],
        "passives": c["passive"],
        "detractors": c["detractor"],
        "nps": nps,
    }


def _ids(surveys) -> list[str]:
    return sorted(s.survey_id for s in surveys)


def _label(s: Survey, key: str):
    return (s.label or {}).get(key)


def _f1(surveys, finding_id: str, windows) -> dict:
    """Credit detractors before and after, and how many are High Bill, not
    controllable."""
    sides = {}
    for side, window in zip(("before", "after"), windows, strict=True):
        detractors = [s for s in _within(surveys, window) if _detractor(s)]
        credit = [s for s in detractors if s.call["call_type"] == "Credit"]
        high_bill = [
            s
            for s in credit
            if _label(s, "primary_driver") == "CUS_HIGH_BILL"
            and _label(s, "controllable") == "no"
        ]
        sides[side] = (window, detractors, credit, high_bill)
    (wb, db, cb, hb), (wa, da, ca, ha) = sides["before"], sides["after"]
    return {
        "id": finding_id,
        "statement": (
            f"Detractors on Credit calls rose from {len(cb)} ({_span(wb)}) to "
            f"{len(ca)} ({_span(wa)}); {len(ha)} of them are High Bill Amount, not "
            f"controllable. All detractors went from {len(db)} to {len(da)}."
        ),
        "numbers": {
            "before": {"from": str(wb[0]), "to": str(wb[1])},
            "after": {"from": str(wa[0]), "to": str(wa[1])},
            "detractors": {"before": len(db), "after": len(da)},
            "credit_detractors": {"before": len(cb), "after": len(ca)},
            "credit_high_bill_not_controllable": {"before": len(hb), "after": len(ha)},
        },
        "survey_ids": _ids(hb + ha),
    }


def _f2(surveys) -> dict:
    day = [s for s in surveys if s.day == YESTERDAY]
    detractors = [s for s in day if _detractor(s)]
    portal = [s for s in detractors if _label(s, "primary_driver") == "SYS_PORTAL"]
    by_type = Counter(s.call["call_type"] for s in portal)
    mentions = [s for s in day if _label(s, "primary_driver") == "SYS_PORTAL"]
    types = " and ".join(f"{t} ({n})" for t, n in sorted(by_type.items()))
    return {
        "id": "F2",
        "statement": (
            f"On Aug 13, {len(portal)} of {len(detractors)} detractors were "
            f"Website / Payment Portal failures, on {types} calls; none controllable "
            f"by the agent. {len(mentions)} surveys that day mention the portal."
        ),
        "numbers": {
            "day": str(YESTERDAY),
            "detractors": len(detractors),
            "portal_detractors": len(portal),
            "portal_detractors_by_call_type": dict(sorted(by_type.items())),
            "portal_surveys": len(mentions),
        },
        "survey_ids": _ids(portal),
    }


def _f3(surveys) -> dict:
    detractors = [s for s in surveys if s.day == F3_DAY and _detractor(s)]
    va = [
        s for s in detractors if _label(s, "primary_driver") == "SYS_VIRTUAL_ASSISTANT"
    ]
    used = sum(s.call["virtual_assistant_used"] == "Y" for s in va)
    return {
        "id": "F3",
        "statement": (
            f"On Aug 11, {len(va)} of {len(detractors)} detractors blamed the virtual "
            f"assistant, {used} of them on calls that used it; none controllable."
        ),
        "numbers": {
            "day": str(F3_DAY),
            "detractors": len(detractors),
            "virtual_assistant_detractors": len(va),
            "on_calls_using_it": used,
        },
        "survey_ids": _ids(va),
    }


def _f4(surveys, f4: tuple[str, str]) -> dict:
    mtd = _within(surveys, MTD)
    team = [s for s in mtd if s.call["supervisor"] == F4_SUPERVISOR]
    rest = [s for s in team if s.call["login_id"] not in f4]
    agents = {}
    for login, driver in zip(f4, ("AGT_COURTESY", "AGT_BILL_EXPLANATION"), strict=True):
        own = [s for s in team if s.call["login_id"] == login]
        planted = [
            s
            for s in own
            if _detractor(s)
            and _label(s, "primary_driver") == driver
            and _label(s, "controllable") == "yes"
        ]
        agents[login] = {
            "agent_name": own[0].call["agent_name"],
            "driver": driver,
            "controllable_detractors": len(planted),
            **_nps(own),
        }
    others = {
        sup: _nps([s for s in mtd if s.call["supervisor"] == sup])
        for sup in sorted({s.call["supervisor"] for s in mtd} - {F4_SUPERVISOR})
    }
    a, b = (agents[x] for x in f4)
    team_nps, rest_nps = _nps(team), _nps(rest)
    lowest = all(team_nps["nps"] < o["nps"] for o in others.values())
    rank = "the lowest team" if lowest else "not the lowest team"
    return {
        "id": "F4",
        "statement": (
            f"{F4_SUPERVISOR}'s team has NPS {team_nps['nps']:+.0f} from "
            f"{team_nps['surveys']} surveys MTD (Aug 1-14), {rank}; without "
            f"{a['agent_name']} and {b['agent_name']} it is {rest_nps['nps']:+.0f} "
            f"from {rest_nps['surveys']}. {a['agent_name']} has "
            f"{a['controllable_detractors']} Courtesy and {b['agent_name']} "
            f"{b['controllable_detractors']} Bill Explanation detractors, all "
            f"controllable."
        ),
        "numbers": {
            "window": {"from": str(MTD[0]), "to": str(MTD[1])},
            "supervisor": F4_SUPERVISOR,
            "team": team_nps,
            "team_without_the_two": rest_nps,
            "agents": agents,
            "other_teams": others,
            "lowest_team": lowest,
        },
        "survey_ids": _ids(
            s for s in team if "F4" in s.spec.patterns and s.label is not None
        ),
    }


def _f5(surveys) -> dict:
    partly = [
        s for s in surveys if _detractor(s) and _label(s, "controllable") == "partly"
    ]
    planted = [s for s in partly if "F5" in s.spec.patterns]
    yesterday = [s for s in planted if s.day == YESTERDAY]
    return {
        "id": "F5",
        "statement": (
            f"{len(planted)} detractors are a High Bill Amount the agent also did not "
            f"explain: partly controllable, so they stay counted against the agent. "
            f"{len(yesterday)} of them are from Aug 13, ready for Label Review."
        ),
        "numbers": {
            "high_bill_not_explained": len(planted),
            "on_yesterday": len(yesterday),
            "all_partly_detractors": len(partly),
        },
        "survey_ids": _ids(planted),
    }


def _f6(surveys) -> dict:
    def count(window):
        detractors = [s for s in _within(surveys, window) if _detractor(s)]
        silent = [s for s in detractors if s.label is None]
        return {"detractors": len(detractors), "no_verbatim": len(silent)}, silent

    full, silent = count((date(2026, 8, 1), date(2026, 8, 17)))
    mtd, _ = count(MTD)
    share = full["no_verbatim"] * 100 / full["detractors"]
    return {
        "id": "F6",
        "statement": (
            f"{full['no_verbatim']} of {full['detractors']} detractors ({share:.0f}%) "
            f'left no comment and no Q5a answer; they stay counted as "No comment". '
            f"MTD Aug 1-14: {mtd['no_verbatim']} of {mtd['detractors']}."
        ),
        "numbers": {"aug_3_17": full, "mtd": mtd},
        "survey_ids": _ids(silent),
    }


def _f7(surveys) -> dict:
    flagged = [
        s
        for s in surveys
        if s.label
        and contradicts_reason(s.label["primary_driver"], s.event["q6_main_reason"])
    ]
    return {
        "id": "F7",
        "statement": (
            f"{len(flagged)} surveys pick a main reason their comment contradicts; "
            f"they are flagged to the analyst, and the Label stands."
        ),
        "numbers": {
            "flagged": len(flagged),
            "cases": [
                {
                    "survey_id": s.survey_id,
                    "q6_main_reason": s.event["q6_main_reason"],
                    "primary_driver": s.label["primary_driver"],
                }
                for s in sorted(flagged, key=lambda s: s.survey_id)
            ],
        },
        "survey_ids": _ids(flagged),
    }


def _f8(surveys) -> dict:
    with_pii = [s for s in surveys if s.pii]
    commented = sum(bool(s.event["comment"]) for s in surveys)
    by_type = Counter(s.pii.type for s in with_pii)
    return {
        "id": "F8",
        "statement": (
            f"Fake PII sits in {len(with_pii)} of {commented} comments ("
            + ", ".join(f"{by_type[t]} {t}" for t in PII_TYPES)
            + "); none of it may reach the model or the screen."
        ),
        "numbers": {
            "comments": commented,
            "with_pii": len(with_pii),
            "by_type": {t: by_type[t] for t in PII_TYPES},
        },
        "survey_ids": _ids(with_pii),
    }


def _f9(surveys, f9: str) -> dict:
    def profile(window):
        own = [s for s in _within(surveys, window) if s.call["login_id"] == f9]
        praise = [s for s in own if _label(s, "sentiment") == "positive"]
        return {**_nps(own), "praise_comments": len(praise)}, own

    mtd, own = profile(MTD)
    full, _ = profile((date(2026, 8, 1), date(2026, 8, 17)))
    name = own[0].call["agent_name"]
    return {
        "id": "F9",
        "statement": (
            f"{name} has {mtd['promoters']} promoters out of {mtd['surveys']} surveys "
            f"MTD (NPS {mtd['nps']:+.0f}), with {mtd['praise_comments']} praise "
            f"comments and no detractor."
        ),
        "numbers": {"login_id": f9, "agent_name": name, "mtd": mtd, "aug_3_17": full},
        "survey_ids": _ids(s for s in own if _label(s, "sentiment") == "positive"),
    }


def expected_findings(generated: Generated) -> list[dict]:
    surveys = generated.surveys
    return [
        _f1(surveys, "F1", WEEKS),
        _f1(surveys, "F1-WTD", WTDS),
        _f2(surveys),
        _f3(surveys),
        _f4(surveys, generated.f4_agents),
        _f5(surveys),
        _f6(surveys),
        _f7(surveys),
        _f8(surveys),
        _f9(surveys, generated.f9_agent),
    ]


def markdown(findings: list[dict]) -> str:
    """The findings, readable, for rehearsing the demo."""
    lines = [
        "# Expected Findings",
        "",
        "Generated with the synthetic surveys; do not edit by hand. Each Planted "
        "Pattern's statement is what the summary and the agent must be able to say, "
        "with these exact numbers. Machine-readable copy: `expected_findings.json`.",
        "",
    ]
    for f in findings:
        lines += [f"## {f['id']}", "", f["statement"], ""]
        lines += [f"Surveys: {', '.join(f['survey_ids']) or 'none'}", ""]
    return "\n".join(lines)

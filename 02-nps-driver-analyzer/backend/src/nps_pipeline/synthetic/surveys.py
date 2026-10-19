"""Synthetic surveys (data contract §1, §9): the Survey Events and their true Labels.

The same calls and seed give the same surveys. Planted Patterns go first, each on
calls that fit it and completed on the day it needs, inside the demo replay hours;
base surveys then fill the volume at the brief's August rates. Every comment is
written from its Label (see `verbatims`), so the true Label is known by
construction.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import polars as pl

from .. import roster, settings
from ..catalog import AGENT, BUCKET_OF, DRIVERS, SYSTEM
from ..events import MAIN_REASONS, SCHEMA, TIMESTAMP_FORMAT
from . import verbatims as v
from .verbatims import MILD, POS, STRONG

SEED = 2026
SURVEY_RATE = 0.074  # 9,319 answered of 125,536 calls in August
DETRACTOR_RATE = 0.049  # 457 negative of 9,319 answered
ESCALATED_RATE = 0.14  # 65 escalated of 457 negative
NO_VERBATIM_RATE = 0.15  # F6: detractors who leave no comment and no Q5a
PII_RATE = 0.05  # F8: comments carrying fake PII
LAST_DAY = date(2026, 8, 17)  # surveys completed later are not emitted
FIRST_SURVEY_NUMBER = 4001
TZ = ZoneInfo(settings.BUSINESS_TIMEZONE)
REPLAY_HOURS = (time(7), time(22))  # planted surveys complete inside these

CHANNEL_WEIGHTS = {"IVR": 60, "SMS": 25, "Email": 15}
LAG_SECONDS = {  # completed this long after the call ends
    "IVR": (60, 15 * 60),
    "SMS": (5 * 60, 8 * 3600),
    "Email": (3600, 7 * 86400),
}
F4_SUPERVISOR = roster.TEAMS[1][0]  # two of this team's agents carry F4
F9_SUPERVISOR = roster.TEAMS[3][0]  # one of this team's agents carries F9

PROMOTER, PASSIVE, DETRACTOR = "promoter", "passive", "detractor"


@dataclass(frozen=True)
class Spec:
    """What one survey says, before it has a call."""

    group: str
    primary: str | None = None  # None: no verbatim, so no Label
    tone: str = STRONG
    secondary: tuple[str, str] | None = None  # (driver, tone)
    controllable: str | None = None  # None: the primary Driver's default
    q5a_only: bool = False  # the verbatim is a Q5a answer, with no comment
    main_reason: str | None = None  # None: the reason that agrees with the Label
    escalated: bool = False
    abandoned: bool = False  # stopped after Q1
    patterns: tuple[str, ...] = ()


@dataclass
class Survey:
    spec: Spec
    call: dict
    channel: str
    completed_at: datetime  # UTC
    survey_id: str = ""
    event: dict | None = None
    pii: v.Pii | None = None

    @property
    def day(self) -> date:
        return self.completed_at.astimezone(TZ).date()

    @property
    def label(self) -> dict | None:
        """The true Label, for a survey with a verbatim."""
        s = self.spec
        if s.primary is None:
            return None
        if s.group == DETRACTOR:
            sentiment = "negative"
        else:
            sentiment = "positive" if s.tone == POS else "neutral"
        patterns = [*s.patterns, *(["F8"] if self.pii else [])]
        return {
            "survey_id": self.survey_id,
            "primary_driver": s.primary,
            "secondary_driver": s.secondary[0] if s.secondary else None,
            "sentiment": sentiment,
            "controllable": s.controllable or DRIVERS[s.primary].default_controllable,
            "patterns": patterns,
        }


@dataclass(frozen=True)
class Generated:
    surveys: list[Survey]  # ordered by completion
    f4_agents: tuple[str, str]  # Courtesy, then Bill Explanation
    f9_agent: str


def _day(n: int) -> date:
    return date(2026, 8, n)


def _ended(call: dict) -> datetime:
    return call["call_started_at"] + timedelta(seconds=call["handle_seconds"])


# Base surveys with a verbatim, by group: (primary, tone, secondary).
PROMOTER_MIX = (
    ("AGT_COURTESY", POS, None),
    ("AGT_COURTESY", POS, None),
    ("AGT_COURTESY", POS, ("SYS_LONG_IVR", MILD)),
    ("AGT_EMPATHY", POS, None),
    ("AGT_KNOWLEDGE", POS, None),
    ("AGT_KNOWLEDGE", POS, None),
    ("AGT_RESOLUTION", POS, None),
    ("AGT_RESOLUTION", POS, None),
    ("AGT_BILL_EXPLANATION", POS, None),
    ("AGT_HOLD_HANDLING", POS, None),
)
PASSIVE_MIX = (  # no portal or virtual-assistant complaints: those are F2 and F3
    ("SYS_LONG_IVR", MILD, None),
    ("SYS_LONG_IVR", MILD, ("AGT_COURTESY", POS)),
    ("AGT_HOLD_HANDLING", MILD, None),
    ("PRC_TRANSFERS", MILD, None),
    ("CUS_HIGH_BILL", MILD, None),
    ("AGT_RESOLUTION", MILD, None),
    ("AGT_KNOWLEDGE", MILD, None),
    ("AGT_COURTESY", MILD, None),
    ("AGT_EMPATHY", MILD, None),
    ("AGT_BILL_EXPLANATION", MILD, None),
    ("CUS_POLICY_DISAGREEMENT", MILD, None),
    ("CUS_OUTAGE", MILD, None),
    ("SYS_AGENT_TOOL", MILD, None),
    ("AGT_COURTESY", POS, None),
    ("AGT_KNOWLEDGE", POS, None),
)
F9_PRAISE = (
    ("AGT_COURTESY", POS, None),
    ("AGT_EMPATHY", POS, None),
    ("AGT_KNOWLEDGE", POS, None),
    ("AGT_BILL_EXPLANATION", POS, None),
    ("AGT_RESOLUTION", POS, None),
)
# Base detractors with a verbatim, dealt in this order: every Bucket, none of them
# a planted cause, one told only in Q5a.
BASE_DETRACTORS = (
    Spec(DETRACTOR, "SYS_LONG_IVR", secondary=("PRC_TRANSFERS", STRONG)),
    Spec(DETRACTOR, "PRC_TRANSFERS"),
    Spec(DETRACTOR, "CUS_OUTAGE"),
    Spec(DETRACTOR, "PRC_RATE_CHANGE"),
    Spec(DETRACTOR, "PRC_INSTALLMENT_LIMITS", q5a_only=True),
    Spec(DETRACTOR, "AGT_KNOWLEDGE"),
    Spec(DETRACTOR, "SYS_DROPPED_CALL"),
    Spec(DETRACTOR, "CUS_PRIOR_EXPERIENCE"),
    Spec(DETRACTOR, "PRC_DISCONNECTION"),
    Spec(DETRACTOR, "AGT_RESOLUTION"),
    Spec(DETRACTOR, "CUS_POLICY_DISAGREEMENT"),
    Spec(DETRACTOR, "SYS_AGENT_TOOL"),
    Spec(DETRACTOR, "AGT_EMPATHY"),
)

Fits = Callable[[dict], bool]


def planted(f4_agents: tuple[str, str], f9_agent: str) -> list[tuple[Spec, date, Fits]]:
    """Every planted survey: what it says, the day it is completed, the calls it
    may sit on. Detractor plants avoid the F4 and F9 agents unless they are F4."""
    special = {*f4_agents, f9_agent}

    def anyone(c):
        return c["login_id"] not in special

    def call_type(*types):
        return lambda c: anyone(c) and c["call_type"] in types

    def login(agent):
        return lambda c: c["login_id"] == agent

    high_bill = Spec(DETRACTOR, "CUS_HIGH_BILL", patterns=("F1",))
    polite = replace(high_bill, secondary=("AGT_COURTESY", POS))
    portal = Spec(DETRACTOR, "SYS_PORTAL", patterns=("F2",))
    portal_mild = Spec(PASSIVE, "SYS_PORTAL", MILD, patterns=("F2",))
    va = Spec(DETRACTOR, "SYS_VIRTUAL_ASSISTANT", patterns=("F3",))
    va_mild = Spec(PASSIVE, "SYS_VIRTUAL_ASSISTANT", MILD, patterns=("F3",))
    courtesy = Spec(DETRACTOR, "AGT_COURTESY", patterns=("F4",))
    explanation = Spec(DETRACTOR, "AGT_BILL_EXPLANATION", patterns=("F4",))
    partly = Spec(
        DETRACTOR,
        "CUS_HIGH_BILL",
        secondary=("AGT_BILL_EXPLANATION", STRONG),
        controllable="partly",
        patterns=("F5",),
    )
    credit, a, b = call_type("Credit"), *f4_agents
    va_call = lambda c: anyone(c) and c["virtual_assistant_used"] == "Y"  # noqa: E731
    esc = {"escalated": True}
    return [
        # F1: High Bill detractors on Credit calls, 2 in Aug 3-9, 8 in Aug 10-16.
        (high_bill, _day(4), credit),
        (polite, _day(6), credit),
        (high_bill, _day(10), credit),
        (polite, _day(11), credit),
        (replace(high_bill, **esc), _day(12), credit),
        (high_bill, _day(12), credit),
        (replace(high_bill, **esc), _day(13), credit),
        (replace(high_bill, **esc), _day(14), credit),
        (high_bill, _day(14), credit),
        (high_bill, _day(15), credit),
        # F2: the payment portal fails on Aug 13, on Credit and LPC calls.
        (replace(portal, **esc), _day(13), credit),
        (portal, _day(13), credit),
        (portal, _day(13), call_type("LPC")),
        (portal, _day(13), call_type("LPC")),
        (portal_mild, _day(13), call_type("Credit", "LPC")),
        (portal_mild, _day(13), call_type("Credit", "LPC")),
        # F3: the virtual assistant fails on Aug 11, only where it was used.
        (va, _day(11), va_call),
        (va, _day(11), va_call),
        (va, _day(11), va_call),
        (va_mild, _day(11), va_call),
        # F4: two agents of one team, one Courtesy and one Bill Explanation.
        (courtesy, _day(5), login(a)),
        (courtesy, _day(10), login(a)),
        (replace(courtesy, **esc), _day(12), login(a)),
        (courtesy, _day(14), login(a)),
        (explanation, _day(6), login(b)),
        (explanation, _day(11), login(b)),
        (explanation, _day(13), login(b)),
        (explanation, _day(14), login(b)),
        # F5: a high bill the agent did not explain, partly controllable.
        (partly, _day(7), call_type("General Billing")),
        (partly, _day(13), call_type("General Billing")),
        (partly, _day(13), call_type("General Billing")),
        # F7: the Customer-Stated Reason contradicts the comment.
        (
            Spec(
                DETRACTOR,
                "AGT_COURTESY",
                main_reason="My bill amount",
                patterns=("F7",),
            ),
            _day(5),
            anyone,
        ),
        (
            Spec(
                DETRACTOR,
                "CUS_OUTAGE",
                main_reason="The representative",
                patterns=("F7",),
            ),
            _day(9),
            anyone,
        ),
        (
            Spec(
                DETRACTOR,
                "AGT_HOLD_HANDLING",
                main_reason="Company policy",
                patterns=("F7",),
            ),
            _day(12),
            anyone,
        ),
    ]


def _place(
    rng: random.Random, by_day: dict[date, list[dict]], used: set, spec, day, fits
) -> Survey:
    """A planted survey on an unused call from `day` that fits, completed that same
    day inside the replay hours."""
    pool = [c for c in by_day[day] if c["transaction_id"] not in used and fits(c)]
    rng.shuffle(pool)
    for call in pool:
        channel = "IVR" if rng.random() < 0.7 else "SMS"
        lag = rng.randint(60, 900) if channel == "IVR" else rng.randint(300, 5400)
        done = _ended(call) + timedelta(seconds=lag)
        local = done.astimezone(TZ)
        if local.date() == day and REPLAY_HOURS[0] <= local.time() < REPLAY_HOURS[1]:
            used.add(call["transaction_id"])
            return Survey(spec, call, channel, done)
    raise ValueError(f"no call fits {spec.patterns} on {day}")


def _base_calls(
    rng: random.Random, calls: list[dict], used: set, n: int
) -> list[tuple[dict, str, datetime]]:
    """`n` more answered calls, each with a channel and a completion time by the
    last day."""
    pool = [c for c in calls if c["transaction_id"] not in used]
    rng.shuffle(pool)
    channels, weights = list(CHANNEL_WEIGHTS), list(CHANNEL_WEIGHTS.values())
    out = []
    for call in pool:
        channel = rng.choices(channels, weights)[0]
        done = _ended(call) + timedelta(seconds=rng.randint(*LAG_SECONDS[channel]))
        if done.astimezone(TZ).date() > LAST_DAY:
            continue
        out.append((call, channel, done))
        if len(out) == n:
            return out
    raise ValueError(f"only {len(out)} calls left for {n} base surveys")


def _non_detractor(rng: random.Random, login: str, f4: tuple, f9: str) -> Spec:
    if login == f9:  # F9: every survey a promoter, most with praise
        if rng.random() < 0.7:
            primary, tone, secondary = rng.choice(F9_PRAISE)
            return Spec(PROMOTER, primary, tone, secondary, patterns=("F9",))
        return Spec(PROMOTER, patterns=("F9",))
    promoter_share = 0.45 if login in f4 else 0.60  # F4's two agents run weaker
    group = PROMOTER if rng.random() < promoter_share else PASSIVE
    if rng.random() < (0.25 if group == PROMOTER else 0.35):
        primary, tone, secondary = rng.choice(
            PROMOTER_MIX if group == PROMOTER else PASSIVE_MIX
        )
        return Spec(group, primary, tone, secondary)
    return Spec(group, abandoned=rng.random() < 0.04)


def _reason_for(primary: str) -> str:
    """The Customer-Stated Reason that agrees with a Label's primary Driver."""
    fixed = {
        "CUS_HIGH_BILL": "My bill amount",
        "SYS_PORTAL": "Website or payment options",
        "SYS_LONG_IVR": "Wait time or phone menu",
        "SYS_VIRTUAL_ASSISTANT": "Wait time or phone menu",
        "PRC_TRANSFERS": "Wait time or phone menu",
        "CUS_OUTAGE": "Power outage",
        "CUS_POLICY_DISAGREEMENT": "Company policy",
    }
    if primary in fixed:
        return fixed[primary]
    if BUCKET_OF[primary] == AGENT:
        return "The representative"
    return "Company policy" if primary.startswith("PRC_") else "Other"


def _pick(rng: random.Random, weights: dict):
    return rng.choices(list(weights), list(weights.values()))[0]


def _event(rng: random.Random, survey: Survey) -> dict:
    """The Survey Event a platform would send for this survey."""
    s, call = survey.spec, survey.call
    if s.group == DETRACTOR:
        q1 = (
            rng.randint(0, 2)
            if s.escalated
            else _pick(rng, dict(enumerate((6, 5, 8, 10, 12, 15, 20))))
        )
    elif s.group == PASSIVE:
        q1 = _pick(rng, {7: 45, 8: 55})
    else:
        q1 = _pick(rng, {9: 40, 10: 60})

    bucket = BUCKET_OF.get(s.primary or "")
    if s.group == DETRACTOR and bucket == AGENT:
        ranges, resolved = [(0, 4), (0, 5), (0, 4)], {"No": 50, "Partially": 50}
        if s.primary == "AGT_BILL_EXPLANATION":
            ranges[1] = (0, 3)
    elif s.group == DETRACTOR and bucket:
        ranges = [(6, 10), (5, 10), (0, 4)]  # the agent did fine; the cause did not
        if s.controllable == "partly":
            ranges = [(3, 7), (0, 4), (0, 4)]
        resolved = (
            {"No": 70, "Partially": 30}
            if bucket == SYSTEM
            else {"Yes": 30, "Partially": 40, "No": 30}
        )
    elif s.group == DETRACTOR:
        ranges, resolved = (
            [(0, 8), (0, 8), (0, 5)],
            {"Yes": 20, "Partially": 40, "No": 40},
        )
    elif s.group == PASSIVE:
        ranges, resolved = (
            [(6, 9), (6, 9), (5, 9)],
            {"Yes": 70, "Partially": 25, "No": 5},
        )
    else:
        ranges, resolved = [(8, 10), (8, 10), (7, 10)], {"Yes": 95, "Partially": 5}
    q2, q3, q4 = (rng.randint(*r) for r in ranges)
    q5 = "No" if s.q5a_only else _pick(rng, resolved)

    q5a = None
    if s.primary and q5 in ("No", "Partially"):
        fill = {DETRACTOR: 0.5, PASSIVE: 0.2, PROMOTER: 0.0}[s.group]
        if s.q5a_only or rng.random() < fill:
            q5a = v.why_not_resolved(rng, s.primary)
        if s.q5a_only and q5a is None:
            raise ValueError(f"{s.primary} has no Q5a answer to tell it")
    comment = None
    if s.primary and not s.q5a_only:
        comment = v.comment(rng, s.primary, s.tone, s.secondary)

    if s.primary:
        reason = s.main_reason or _reason_for(s.primary)
    elif s.group == PROMOTER and rng.random() < 0.8:
        reason = "The representative"
    else:
        reason = rng.choice(MAIN_REASONS)
    consent = rng.random() < {DETRACTOR: 0.6, PASSIVE: 0.3, PROMOTER: 0.2}[s.group]

    answered = not s.abandoned
    event = {
        "event_type": "survey.completed",
        "survey_id": survey.survey_id,
        "transaction_id": call["transaction_id"],
        "agent_login_id": call["login_id"],
        "survey_channel": survey.channel,
        "completed_at": survey.completed_at.strftime(TIMESTAMP_FORMAT),
        "q1_ltr": q1,
        "q2_agent_sat": q2 if answered else None,
        "q3_explained_clearly": q3 if answered else None,
        "q4_ease": q4 if answered else None,
        "q5_issue_resolved": q5 if answered else None,
        "q5a_why_not_resolved": q5a if answered else None,
        "q6_main_reason": reason if answered else None,
        "comment": comment if answered else None,
        "callback_consent": "Yes" if consent else "No",
        "escalated": "Y" if s.escalated else "N",
    }
    assert list(event) == list(SCHEMA)
    return event


def _local_calls(calls: pl.DataFrame) -> list[dict]:
    rows = calls.sort("transaction_id").to_dicts()
    for row in rows:
        row["call_day"] = row["call_started_at"].astimezone(TZ).date()
    return rows


def special_agents(calls: list[dict], seed: int) -> tuple[tuple[str, str], str]:
    """The two F4 agents and the F9 agent, drawn from their teams."""
    rng = random.Random(seed)
    team = lambda sup: sorted({c["login_id"] for c in calls if c["supervisor"] == sup})  # noqa: E731
    a, b = rng.sample(team(F4_SUPERVISOR), 2)
    return (a, b), rng.choice(team(F9_SUPERVISOR))


def generate(calls: pl.DataFrame, seed: int = SEED) -> Generated:
    """Every synthetic survey, ordered by completion, with its event filled in.

    `calls` is the joined call side (`inputs.load_calls`).
    """
    rows = _local_calls(calls)
    rng = random.Random(seed)
    f4, f9 = special_agents(rows, seed)
    by_day: dict[date, list[dict]] = {}
    for row in rows:
        by_day.setdefault(row["call_day"], []).append(row)

    used: set[str] = set()
    plants = [_place(rng, by_day, used, *p) for p in planted(f4, f9)]
    total = round(SURVEY_RATE * len(rows))
    base = _base_calls(rng, rows, used, total - len(plants))

    detractors = round(DETRACTOR_RATE * total)
    planted_detractors = [p for p in plants if p.spec.group == DETRACTOR]
    n_base = detractors - len(planted_detractors)
    eligible = [i for i, (c, *_) in enumerate(base) if c["login_id"] not in {*f4, f9}]
    picks = rng.sample(eligible, n_base)
    silent = round(NO_VERBATIM_RATE * detractors)
    specs: dict[int, Spec] = {}
    for k, i in enumerate(picks[:silent]):
        specs[i] = Spec(DETRACTOR, abandoned=k % 2 == 0, patterns=("F6",))
    for k, i in enumerate(picks[silent:]):
        specs[i] = BASE_DETRACTORS[k % len(BASE_DETRACTORS)]
    escalate = round(ESCALATED_RATE * detractors) - sum(
        p.spec.escalated for p in planted_detractors
    )
    for i in rng.sample(picks[silent:], escalate):
        specs[i] = replace(specs[i], escalated=True)

    surveys = list(plants)
    for i, (call, channel, done) in enumerate(base):
        spec = specs.get(i) or _non_detractor(rng, call["login_id"], f4, f9)
        surveys.append(Survey(spec, call, channel, done))

    surveys.sort(key=lambda s: (s.completed_at, s.call["transaction_id"]))
    for n, survey in enumerate(surveys, FIRST_SURVEY_NUMBER):
        survey.survey_id = f"ACS-2026-{n:06d}"
        survey.event = _event(rng, survey)

    commented = [s for s in surveys if s.event["comment"]]
    pii_count = round(PII_RATE * len(commented))
    for k, survey in enumerate(rng.sample(commented, pii_count)):
        kind = v.PII_TYPES[k % len(v.PII_TYPES)]
        survey.event["comment"], survey.pii = v.add_pii(
            rng, survey.event["comment"], kind
        )
    return Generated(surveys, f4, f9)

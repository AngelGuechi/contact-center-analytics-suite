"""Verbatim templates: every sentence says one Driver, so a survey's true Label is
known by construction.

Tones: "strong" (a detractor complaint), "mild" (a passive's complaint) and "pos"
(praise). A comment is one core sentence for the primary Driver, plus an optional
clause for the secondary Driver. Fake PII uses reserved values only: 555-01xx
phone numbers and example.com addresses.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

from nps_pipeline.synthetic_names import FIRST_NAMES, LAST_NAMES

STRONG, MILD, POS = "strong", "mild", "pos"

CORE: dict[tuple[str, str], tuple[str, ...]] = {
    ("AGT_COURTESY", STRONG): (
        "The representative was rude and kept interrupting me.",
        "The agent talked down to me the whole call.",
        "She was short with me and sounded annoyed that I called.",
        "The person I spoke with was dismissive and rushed me off the phone.",
        "Rude agent. He sighed every time I asked a question.",
        "The agent was condescending and laughed when I asked about my bill.",
        "He raised his voice at me when I asked him to repeat something.",
    ),
    ("AGT_COURTESY", MILD): (
        "The agent was a bit short with me.",
        "Got my answer, but the representative sounded impatient.",
    ),
    ("AGT_COURTESY", POS): (
        "The representative was very kind and patient.",
        "Very polite and friendly agent.",
        "She was courteous from start to finish.",
        "The agent was warm and respectful the whole time.",
    ),
    ("AGT_EMPATHY", STRONG): (
        "I told them I was struggling to pay and the agent did not care at all.",
        "No understanding of my situation, just reading a script.",
        "I explained I have a sick child at home and got no sympathy.",
    ),
    ("AGT_EMPATHY", MILD): (
        "The agent was fine but did not seem to care much about my situation.",
    ),
    ("AGT_EMPATHY", POS): (
        "The agent understood my situation and really listened.",
        "He was understanding about my financial situation.",
        "She made me feel heard after a really stressful week.",
    ),
    ("AGT_KNOWLEDGE", STRONG): (
        "The agent did not know how payment arrangements work and gave me wrong "
        "information.",
        "He had to guess at every answer and told me two different things.",
        "The representative could not answer basic questions about my account.",
    ),
    ("AGT_KNOWLEDGE", MILD): (
        "The agent had to check with someone else for most of my questions.",
    ),
    ("AGT_KNOWLEDGE", POS): (
        "The agent knew exactly what to do.",
        "Very knowledgeable, answered every question I had.",
    ),
    ("AGT_RESOLUTION", STRONG): (
        "I called to fix one thing and it is still not fixed.",
        "Nothing was resolved, I will have to call again.",
        "They promised a callback that never came and my issue is still open.",
    ),
    ("AGT_RESOLUTION", MILD): ("Only part of my problem got solved.",),
    ("AGT_RESOLUTION", POS): (
        "Problem solved on the first call.",
        "Everything was taken care of quickly.",
    ),
    ("AGT_BILL_EXPLANATION", STRONG): (
        "Nobody explained why my bill changed, the agent just read me the total.",
        "I asked three times what the charges were for and never got a clear answer.",
        "The agent could not explain the line items on my bill.",
        "The representative just repeated the amount instead of explaining it.",
        "Nobody walked me through the new charges, I still have no idea what I pay "
        "for.",
        "The agent told me the bill is correct but would not say why.",
    ),
    ("AGT_BILL_EXPLANATION", MILD): (
        "I still do not really understand the charges on my bill.",
    ),
    ("AGT_BILL_EXPLANATION", POS): (
        "She walked me through my bill line by line, now I understand it.",
        "The agent explained the charges clearly.",
    ),
    ("AGT_HOLD_HANDLING", STRONG): (
        "I was put on hold for twenty minutes without anyone checking on me.",
        "The agent left me on hold over and over with no explanation.",
    ),
    ("AGT_HOLD_HANDLING", MILD): ("Long hold in the middle of the call.",),
    ("AGT_HOLD_HANDLING", POS): (
        "Even when she put me on hold she kept checking back with me.",
    ),
    ("SYS_AGENT_TOOL", STRONG): (
        "The agent said their system was down and could not see my account.",
        "They told me their computer was not working and to call back later.",
    ),
    ("SYS_AGENT_TOOL", MILD): ("The rep's system was slow, so it took a while.",),
    ("SYS_PORTAL", STRONG): (
        "Your website would not take my payment, that is why I had to call.",
        "The payment portal kept giving an error and I could not pay online.",
        "The online account page crashed every time I tried to pay my bill.",
        "Tried to pay on the app three times and it failed every time.",
    ),
    ("SYS_PORTAL", MILD): (
        "The website was down, so I had to call to pay.",
        "Could not pay online today, the portal kept failing.",
    ),
    ("SYS_LONG_IVR", STRONG): (
        "It took forever to get through the phone menu to a real person.",
        "Ten minutes pressing buttons before I reached anyone.",
        "The phone menu sent me in circles.",
    ),
    ("SYS_LONG_IVR", MILD): (
        "The phone menu is too long.",
        "Too many options before reaching a person.",
    ),
    ("SYS_VIRTUAL_ASSISTANT", STRONG): (
        "The virtual assistant did not understand anything I said and kept "
        "repeating itself.",
        "The automated assistant hung up on me twice before I got an agent.",
        "The bot kept asking for my account number and then said it could not help.",
    ),
    ("SYS_VIRTUAL_ASSISTANT", MILD): (
        "The automated assistant was useless, I just wanted a person.",
    ),
    ("SYS_DROPPED_CALL", STRONG): (
        "The call dropped in the middle and I had to start over.",
        "Got disconnected after waiting and had to call back.",
    ),
    ("CUS_HIGH_BILL", STRONG): (
        "My bill doubled this month and I have not changed anything.",
        "The bill is way too high, I cannot afford this.",
        "How is my bill this high for a small apartment?",
        "This month's bill is outrageous, almost twice what I normally pay.",
        "Paying this much for electricity is ridiculous.",
        "My bill went up again, it is just too expensive.",
        "Three hundred dollars for one month is too much for my family.",
        "The amount on this bill is impossible for us to pay.",
    ),
    ("CUS_HIGH_BILL", MILD): (
        "The bill is higher than I expected.",
        "Still not happy about how much my bill is.",
    ),
    ("CUS_POLICY_DISAGREEMENT", STRONG): (
        "It is not fair that I have to pay a deposit after ten years as a customer.",
        "I do not agree with charging a fee to pay over the phone.",
    ),
    ("CUS_POLICY_DISAGREEMENT", MILD): ("I do not like the deposit rule.",),
    ("CUS_OUTAGE", STRONG): (
        "We had no power for two days and all I get is an apology.",
        "The outages in my area keep happening and nothing changes.",
    ),
    ("CUS_OUTAGE", MILD): ("Still annoyed about last week's outage.",),
    ("CUS_PRIOR_EXPERIENCE", STRONG): (
        "This is the fourth time I call about the same thing in the last months.",
        "Every time I deal with this company it is a headache.",
    ),
    ("PRC_RATE_CHANGE", STRONG): (
        "Nobody told me the rates were going up.",
        "The new rate is costing me more and I never asked for it.",
    ),
    ("PRC_DISCONNECTION", STRONG): (
        "They threatened to disconnect my service over one late payment.",
        "The disconnection notice came with no warning.",
    ),
    ("PRC_INSTALLMENT_LIMITS", STRONG): (
        "They would only let me split the balance into two payments, that does "
        "not help.",
        "I asked for a longer payment plan and was told I already used my one "
        "plan this year.",
    ),
    ("PRC_TRANSFERS", STRONG): (
        "I was transferred three times and had to explain everything each time.",
        "They kept passing me to another department.",
    ),
    ("PRC_TRANSFERS", MILD): (
        "I got transferred once before reaching the right person.",
    ),
}

# A second Driver, said in its own sentence after the core one.
SECONDARY: dict[tuple[str, str], tuple[str, ...]] = {
    ("AGT_BILL_EXPLANATION", STRONG): (
        "And the agent never explained the charges.",
        "The representative could not tell me why it went up.",
    ),
    ("AGT_COURTESY", POS): (
        "The agent was nice though.",
        "The representative was polite, at least.",
    ),
    ("SYS_LONG_IVR", MILD): (
        "Only complaint is the phone menu takes too long.",
        "The phone menu took too long, though.",
    ),
    ("PRC_TRANSFERS", STRONG): ("I was transferred twice on top of that.",),
}

# Q5a, "why was it not fully resolved", by primary Driver. Only these Drivers get
# one: a generic answer such as "I have to call back" would say a second Driver
# (Resolution) the Label does not have.
Q5A: dict[str, tuple[str, ...]] = {
    "CUS_HIGH_BILL": (
        "The bill is still the same amount.",
        "They could not lower my bill.",
    ),
    "AGT_BILL_EXPLANATION": ("I still do not know why it went up.",),
    "AGT_RESOLUTION": ("My issue is still open.",),
    "SYS_PORTAL": ("I still cannot pay online.",),
    "SYS_VIRTUAL_ASSISTANT": ("The assistant never routed me correctly.",),
    "PRC_INSTALLMENT_LIMITS": ("They would not give me a longer payment plan.",),
    "AGT_KNOWLEDGE": ("They gave me the wrong information.",),
    "SYS_DROPPED_CALL": ("The call dropped before we finished.",),
}

# A comma opener runs into the sentence; "Terrible. " stands on its own.
OPENERS = {STRONG: ("", "", "Terrible. ", "Honestly, "), MILD: ("", "", "Okay, ")}


def has_template(driver: str, tone: str) -> bool:
    return (driver, tone) in CORE


def comment(
    rng: random.Random,
    primary: str,
    tone: str,
    secondary: tuple[str, str] | None = None,
) -> str:
    """One comment saying `primary` in `tone`, and `secondary` (driver, tone)."""
    text = rng.choice(CORE[primary, tone])
    opener = rng.choice(OPENERS.get(tone, ("",)))
    if opener:
        text = opener + (_lower_first(text) if opener.endswith(", ") else text)
    if secondary:
        text += " " + rng.choice(SECONDARY[secondary])
    if rng.random() < 0.15:  # some customers type fast
        text = _lower_first(text).rstrip(".")
    return text


def _lower_first(text: str) -> str:
    return text if re.match(r"I\b", text) else text[0].lower() + text[1:]


def why_not_resolved(rng: random.Random, primary: str) -> str | None:
    """A Q5a answer that says `primary`, or None when that Driver has none."""
    return rng.choice(Q5A[primary]) if primary in Q5A else None


# Fake PII (Planted Pattern F8).
PII_TYPES = ("account", "phone", "email", "address", "name")
_STREETS = ("Oak Street", "Maple Avenue", "Pine Road", "Cedar Lane", "Elm Drive")


@dataclass(frozen=True)
class Pii:
    type: str
    text: str  # the personal data itself, as it appears in the comment
    start: int  # its position in the comment, end exclusive
    end: int


def _pii_sentence(rng: random.Random, kind: str) -> tuple[str, str]:
    """A sentence carrying one fake piece of PII, and that piece."""
    first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
    match kind:
        case "account":
            value = f"{rng.randint(1000, 9999)} {rng.randint(1000, 9999)} "
            value += f"{rng.randint(10, 99)}"
            return f"My account number is {value}.", value
        case "phone":
            value = f"555-01{rng.randint(0, 99):02d}"
            return f"Call me back at {value}.", value
        case "email":
            value = f"{first.lower()}.{last.lower()}{rng.randint(10, 99)}@example.com"
            return f"You can email me at {value}.", value
        case "address":
            value = f"{rng.randint(100, 9899)} {rng.choice(_STREETS)}"
            return f"I live at {value}.", value
        case "name":
            value = f"{first} {last}"
            return f"This is {value}.", value
    raise ValueError(f"unknown PII type {kind!r}")


def add_pii(rng: random.Random, text: str, kind: str) -> tuple[str, Pii]:
    """`text` with one sentence of fake PII before or after it."""
    sentence, value = _pii_sentence(rng, kind)
    if rng.random() < 0.5:
        out = f"{sentence} {text}"
        start = sentence.index(value)
    else:
        joint = " " if text.endswith((".", "!", "?")) else ". "
        out = f"{text}{joint}{sentence}"
        start = len(text) + len(joint) + sentence.index(value)
    return out, Pii(kind, value, start, start + len(value))

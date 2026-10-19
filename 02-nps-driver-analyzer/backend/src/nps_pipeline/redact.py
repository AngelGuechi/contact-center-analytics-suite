"""Personal data redaction: Verbatim in, Redacted Verbatim out (data contract §11).

The Redacted Verbatim is the only form of a comment or Q5a answer that the AI,
the stored Labels, the Daily Survey Workbook or the screen ever see. Each piece of
personal data becomes a placeholder naming its type, so the model still knows that
a customer left a phone number without seeing it.

Rules are deterministic patterns, checked in priority order; a later rule never
claims text an earlier one already took (an email's digits are not an account).
Names from the shared synthetic vocabulary are caught regardless of letter case
after a self-introduction cue ("This is", "My name is", "Me llamo"). Bare names
mid-sentence are preserved so mentions of the contact-center agent stay intact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from nps_pipeline.synthetic_names import FIRST_NAME_SPELLINGS, LAST_NAME_SPELLINGS

PLACEHOLDERS = {
    "email": "[EMAIL]",
    "phone": "[PHONE]",
    "account": "[ACCOUNT]",
    "address": "[ADDRESS]",
    "name": "[NAME]",
}
PII_TYPES = tuple(PLACEHOLDERS)
VERBATIM_FIELDS = ("comment", "q5a_why_not_resolved")

_EMAIL = r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"

# North American (555-0197, (555) 010-0197, +1 555 010 0197) and Mexican
# (81 5555 0197, +52 81 5555 0197) numbers. Never part of a longer number, so
# amounts, dates and dashed account numbers stay out.
_PHONE = r"""
    (?<![\w$.,-])
    (?:
        (?:\+?1[\s.-])?(?:\(\d{3}\)\s?|\d{3}[\s.-]?)?\d{3}[\s.-]\d{4}
      | (?:\+?1[\s.-])?\d{10}
      | (?:\+?52[\s.-]?)?\d{2}[\s.-]\d{4}[\s.-]\d{4}
    )
    (?!\w|[.,-]\d)
"""

# A run of 8 or more digits, optionally grouped by spaces or dashes; dates stay.
_ACCOUNT = r"""
    (?<![\w$.,-])
    (?!(?:\d{4}-\d{2}-\d{2}|\d{2}-\d{2}-\d{4})(?!\w|-\d))
    \d(?:[ -]?\d){7,}
    (?!\w|[.,-]\d)
"""

# Explicit account context takes precedence over ambiguous numeric phone rules.
# Only the number is replaced, preserving the customer's surrounding words.
_EXPLICIT_ACCOUNT = rf"""
    \baccount(?:\s+number)?\b\s*(?:is\b\s*)?[:\#]?\s*
    (?P<pii>{_ACCOUNT})
"""

_WORD = r"[A-ZÁÉÍÓÚÑ][a-záéíóúñ'-]+"
_STREET = (
    r"Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|Boulevard|Blvd"
    r"|Court|Ct|Way|Place|Pl|Circle|Cir|Parkway|Pkwy|Highway|Hwy"
)
_ADDRESS = rf"""
    \b\d{{1,6}}\s+(?:{_WORD}\s+){{1,3}}(?:{_STREET})\b
  | \b(?:Calle|Avenida|Av\.|Av)\s+(?:{_WORD}\s+){{1,3}}\#?\d{{1,6}}\b
"""

# Match the agreed demo vocabulary, not arbitrary capitalized complaint words.
_FIRST_NAME = "|".join(re.escape(name) for name in FIRST_NAME_SPELLINGS)
_LAST_NAME = "|".join(re.escape(name) for name in LAST_NAME_SPELLINGS)
_NAME = rf"""
    \b(?:this\ is|my\ name\ is|me\ llamo|mi\ nombre\ es)\s+
    (?P<pii>(?:{_FIRST_NAME})\b(?:\s+(?:{_LAST_NAME})\b){{0,2}})
"""

_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(_EMAIL)),
    ("account", re.compile(_EXPLICIT_ACCOUNT, re.VERBOSE | re.IGNORECASE)),
    ("phone", re.compile(_PHONE, re.VERBOSE)),
    ("account", re.compile(_ACCOUNT, re.VERBOSE)),
    ("address", re.compile(_ADDRESS, re.VERBOSE)),
    ("name", re.compile(_NAME, re.VERBOSE | re.IGNORECASE)),
)


@dataclass(frozen=True)
class Pii:
    type: str
    text: str
    start: int  # position in the original text, end exclusive
    end: int


def find_pii(text: str) -> list[Pii]:
    """Every piece of personal data in `text`, in order of position."""
    found: list[Pii] = []
    for kind, pattern in _RULES:
        group = "pii" if "pii" in pattern.groupindex else 0
        for m in pattern.finditer(text):
            start, end = m.span(group)
            if any(start < p.end and p.start < end for p in found):
                continue
            found.append(Pii(kind, text[start:end], start, end))
    return sorted(found, key=lambda p: p.start)


def redact(text: str | None) -> str | None:
    """`text` with each piece of personal data replaced by its placeholder."""
    if not text:
        return text
    out = text
    for p in reversed(find_pii(text)):
        out = out[: p.start] + PLACEHOLDERS[p.type] + out[p.end :]
    return out


def redact_event(event: dict) -> dict:
    """A copy of a Survey Event whose comment and Q5a hold the Redacted Verbatim."""
    return {
        **event,
        **{f: redact(event[f]) for f in VERBATIM_FIELDS if f in event},
    }

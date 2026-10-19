"""Driver Catalog v1 (data contract §7). Closed: a Label outside it is invalid.

Driver names are neutral; the Label's sentiment gives the direction. The default
controllable value guides the AI, and a Label may differ from it.
"""

from __future__ import annotations

from dataclasses import dataclass

CATALOG_VERSION = "v1"

AGENT, SYSTEM, CUSTOMER, PROCESS = "Agent", "System", "Customer", "Process / Policy"
BUCKETS = (AGENT, SYSTEM, CUSTOMER, PROCESS)
CONTROLLABLE_VALUES = ("yes", "no", "partly")
SENTIMENTS = ("positive", "neutral", "negative")


@dataclass(frozen=True)
class Driver:
    code: str
    bucket: str
    name: str
    default_controllable: str


DRIVERS: dict[str, Driver] = {
    d.code: d
    for d in [
        Driver("AGT_COURTESY", AGENT, "Courtesy", "yes"),
        Driver("AGT_EMPATHY", AGENT, "Empathy", "yes"),
        Driver("AGT_KNOWLEDGE", AGENT, "Knowledge", "yes"),
        Driver("AGT_RESOLUTION", AGENT, "Resolution", "yes"),
        Driver("AGT_BILL_EXPLANATION", AGENT, "Bill Explanation", "yes"),
        Driver("AGT_HOLD_HANDLING", AGENT, "Hold Handling", "partly"),
        Driver("AGT_OTHER", AGENT, "Other", "yes"),
        Driver("SYS_AGENT_TOOL", SYSTEM, "Agent Tool Down", "no"),
        Driver("SYS_PORTAL", SYSTEM, "Website / Payment Portal", "no"),
        Driver("SYS_LONG_IVR", SYSTEM, "Long IVR", "no"),
        Driver("SYS_VIRTUAL_ASSISTANT", SYSTEM, "Virtual Assistant Failure", "no"),
        Driver("SYS_DROPPED_CALL", SYSTEM, "Dropped Call", "no"),
        Driver("SYS_OTHER", SYSTEM, "Other", "no"),
        Driver("CUS_HIGH_BILL", CUSTOMER, "High Bill Amount", "no"),
        Driver("CUS_POLICY_DISAGREEMENT", CUSTOMER, "Disagrees With Policy", "no"),
        Driver("CUS_OUTAGE", CUSTOMER, "Outage Frustration", "no"),
        Driver("CUS_PRIOR_EXPERIENCE", CUSTOMER, "Prior Bad Experience", "no"),
        Driver("CUS_OTHER", CUSTOMER, "Other", "no"),
        Driver("PRC_RATE_CHANGE", PROCESS, "Rate Change", "no"),
        Driver("PRC_DISCONNECTION", PROCESS, "Disconnection Rules", "no"),
        Driver("PRC_INSTALLMENT_LIMITS", PROCESS, "Installment Plan Limits", "no"),
        Driver("PRC_TRANSFERS", PROCESS, "Transfers", "partly"),
        Driver("PRC_OTHER", PROCESS, "Other", "no"),
    ]
}

BUCKET_OF: dict[str, str] = {code: d.bucket for code, d in DRIVERS.items()}

# The Buckets each Customer-Stated Reason (Q6) agrees with. A Label whose primary
# Bucket is outside its survey's set contradicts what the customer picked, and is
# flagged to the analyst (Planted Pattern F7); the Label still stands.
REASON_BUCKETS: dict[str, tuple[str, ...]] = {
    "The representative": (AGENT,),
    "My bill amount": (CUSTOMER, PROCESS),
    "Website or payment options": (SYSTEM,),
    "Wait time or phone menu": (SYSTEM, AGENT, PROCESS),
    "Company policy": (PROCESS, CUSTOMER),
    "Power outage": (CUSTOMER,),
    "Other": BUCKETS,
}


def contradicts_reason(primary_driver: str, main_reason: str | None) -> bool:
    """True when the customer's own reason points away from the Label's Bucket."""
    if main_reason is None:
        return False
    return BUCKET_OF[primary_driver] not in REASON_BUCKETS[main_reason]


class InvalidLabel(ValueError):
    """A Label that does not fit the closed catalog."""


def validate_label(
    primary_driver: str,
    secondary_driver: str | None,
    sentiment: str,
    controllable: str,
) -> None:
    """Raises InvalidLabel naming every field outside the catalog."""
    problems = []
    if primary_driver not in DRIVERS:
        problems.append(f"primary driver {primary_driver!r} is not in catalog v1")
    if secondary_driver and secondary_driver not in DRIVERS:
        problems.append(f"secondary driver {secondary_driver!r} is not in catalog v1")
    if sentiment not in SENTIMENTS:
        problems.append(f"sentiment {sentiment!r} is not one of {SENTIMENTS}")
    if controllable not in CONTROLLABLE_VALUES:
        problems.append(
            f"controllable {controllable!r} is not one of {CONTROLLABLE_VALUES}"
        )
    if problems:
        raise InvalidLabel("; ".join(problems))

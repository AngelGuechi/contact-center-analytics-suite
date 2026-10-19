"""The call context sidecar (data contract §3, ADR 0003): what the shared call
detail lacks, one row per call, joined on `transaction_id`.

`call_type` is dealt by the brief's proportions, exactly, ignoring `Queue` and
`Post_Route_Data` (random filler). Provisional until use case 1 decides call type.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from pathlib import Path

import polars as pl

from . import paths

CALL_TYPE_SHARES = {  # percent of calls
    "Credit": 28,
    "General Billing": 24,
    "MIMO": 16,
    "LPC": 12,
    "NEM": 10,
    "CBB": 10,
}
CALL_TYPES = tuple(CALL_TYPE_SHARES)

# Synthetic: about 30% of callers go through the virtual assistant first, which
# keeps them longer in the IVR.
VIRTUAL_ASSISTANT_SHARE = 0.30
IVR_SECONDS = {"N": (20, 120), "Y": (90, 240)}  # inclusive range by VA use
SEED = 2026

SCHEMA = {
    "transaction_id": pl.String,
    "call_type": pl.String,
    "ivr_seconds": pl.Int64,
    "virtual_assistant_used": pl.String,
}


def call_type_counts(n: int) -> dict[str, int]:
    """Calls per type, summing to n: largest remainder, ties in catalog order."""
    if sum(CALL_TYPE_SHARES.values()) != 100:
        raise ValueError("CALL_TYPE_SHARES must add up to 100")
    split = {t: divmod(n * share, 100) for t, share in CALL_TYPE_SHARES.items()}
    counts = {t: whole for t, (whole, _) in split.items()}
    by_remainder = sorted(CALL_TYPES, key=lambda t: -split[t][1])
    for t in by_remainder[: n - sum(counts.values())]:
        counts[t] += 1
    return counts


def build_call_context(
    transaction_ids: Sequence[str], seed: int = SEED
) -> pl.DataFrame:
    """One sidecar row per call. The same calls and seed give the same sidecar."""
    ids = sorted(transaction_ids)
    if len(set(ids)) != len(ids):
        raise ValueError("transaction_id repeated")
    rng = random.Random(seed)
    types = [t for t, k in call_type_counts(len(ids)).items() for _ in range(k)]
    rng.shuffle(types)
    va = ["Y" if rng.random() < VIRTUAL_ASSISTANT_SHARE else "N" for _ in ids]
    ivr = [rng.randint(*IVR_SECONDS[v]) for v in va]
    return pl.DataFrame(
        {
            "transaction_id": ids,
            "call_type": types,
            "ivr_seconds": ivr,
            "virtual_assistant_used": va,
        },
        schema=SCHEMA,
    )


def write_call_context(context: pl.DataFrame, path: Path = paths.CALL_CONTEXT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    context.write_csv(path)


def read_call_context(path: Path = paths.CALL_CONTEXT) -> pl.DataFrame:
    context = pl.read_csv(path, schema=SCHEMA)
    if context.null_count().sum_horizontal().item():
        raise ValueError("call context has blank cells")
    if context["transaction_id"].is_duplicated().any():
        raise ValueError("call context repeats a transaction_id")
    if not context["call_type"].is_in(CALL_TYPES).all():
        raise ValueError(f"call_type must be one of {', '.join(CALL_TYPES)}")
    if not context["virtual_assistant_used"].is_in(["Y", "N"]).all():
        raise ValueError("virtual_assistant_used must be Y or N")
    if (context["ivr_seconds"] < 0).any():
        raise ValueError("ivr_seconds must be non-negative")
    return context

"""The call-detail export's column names: they live here and nowhere else.

The names are the shared sample's (`sample_call_detail.ods`), the same ones use case
2 reads. Nobody has confirmed them against the client's real export yet, so expect
them to change: add the real header to the field's tuple, or replace it, and no other
code moves.

Matching ignores letter case and extra spaces, so `talk  time ` finds `Talk Time`.
"""

from __future__ import annotations

from collections.abc import Iterable

FIELDS: dict[str, tuple[str, ...]] = {  # our name -> export headers accepted for it
    "transaction_id": ("Transaction ID",),
    "login_id": ("Login ID",),
    "call_started_at": ("Start Date Time",),
    "talk_seconds": ("Talk Time",),
    "hold_seconds": ("Hold Time",),
    "wrap_seconds": ("Wrap Time",),
}


def _key(header: str) -> str:
    return " ".join(header.split()).casefold()


def match(headers: Iterable[str]) -> dict[str, str]:
    """A file's headers -> {export header: our name}, for every field.

    Raises when a field has no column in the file, or more than one, and lists the
    file's headers so the fix is a one-line edit to FIELDS. Other columns are ignored.
    """
    headers = list(headers)
    found: dict[str, list[str]] = {field: [] for field in FIELDS}
    for header in headers:
        for field, accepted in FIELDS.items():
            if _key(header) in {_key(a) for a in accepted}:
                found[field].append(header)
    missing = [f"{f} ({' / '.join(FIELDS[f])})" for f, hs in found.items() if not hs]
    repeated = [f"{f} ({', '.join(hs)})" for f, hs in found.items() if len(hs) > 1]
    problems = [
        f"no column for {'; '.join(missing)}" if missing else "",
        f"more than one column for {'; '.join(repeated)}" if repeated else "",
    ]
    if any(problems):
        raise ValueError(
            f"call-detail headers: {'; '.join(p for p in problems if p)}. "
            f"The file has: {', '.join(headers)}"
        )
    return {hs[0]: field for field, hs in found.items()}

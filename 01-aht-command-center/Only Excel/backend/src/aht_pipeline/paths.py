"""Where the inputs live. Files outside this use case are read, never written."""

from __future__ import annotations

from pathlib import Path

USE_CASE = Path(__file__).resolve().parents[3]  # 01-aht-command-center/
CALL_DETAIL = USE_CASE.parents[1] / "02-nps-driver-analyzer" / "data" / "synthetic_call_detail.xlsx"  # until a client .xlsx export

# Kept by use case 2 for now. CONTEXT-MAP: every use case shares the roster.
# Its ADR 0003: call type is dealt by the brief's proportions until this use case
# decides how to derive it.
NPS_DATA = USE_CASE.parents[1] / "02-nps-driver-analyzer" / "data"
ROSTER = NPS_DATA / "roster.csv"
CALL_CONTEXT = NPS_DATA / "call_context.csv"

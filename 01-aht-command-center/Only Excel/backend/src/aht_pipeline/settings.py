"""Engine settings. Each one lives here and nowhere else.

Several are README open questions; the comment beside each one says so.
"""

from __future__ import annotations

ALERT_SECONDS = 640  # brief: red status for any agent whose AHT today is above this

# open: one flat alert, or a target per call type? (Credit averaged 668s in August.)
# Empty means flat. Filled, e.g. {"Credit": 700}, each call is held to its call
# type's threshold, call types not listed keep ALERT_SECONDS, and the engine needs
# a `call_type` column.
ALERT_SECONDS_BY_CALL_TYPE: dict[str, int] = {}

BUSINESS_TIMEZONE = "America/Mexico_City"  # as in use case 2: CDMX, UTC-6, no DST

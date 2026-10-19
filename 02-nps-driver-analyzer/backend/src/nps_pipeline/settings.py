"""Engine settings (data contract §10). Each one lives here and nowhere else.

Several are README open questions; the comment beside each one says so.
"""

from __future__ import annotations

from typing import Literal

ControllableRule = Literal["drop", "reclassify"]
CONTROLLABLE_RULES: tuple[ControllableRule, ...] = ("drop", "reclassify")

NPS_SCORE_FIELD = "q1_ltr"  # open: which ACS question is the 0-10 likelihood question
PROMOTER_MIN = 9
DETRACTOR_MAX = 6
MIN_SAMPLE = 10  # under this many surveys an NPS is flagged "low sample"

# open: drop the non-controllable detractors, or reclassify them as passives
CONTROLLABLE_RULE: ControllableRule = "drop"
PARTLY_COUNTS_AGAINST_AGENT = True  # a "partly" detractor stays in controllable NPS

NPS_DATE = (
    "completed_at"  # a survey counts on the day it was completed, not the call day
)
BUSINESS_TIMEZONE = "America/Mexico_City"  # demo: CDMX time, UTC-6 with no DST
WEEK_START = 1  # ISO 8601: weeks start on Monday; WTD runs Monday to the as-of day

NPS_STORAGE = "files"  # open: whether a database is allowed (switch: "duckdb")
LABEL_LIVE = False  # labels are produced once before the demo

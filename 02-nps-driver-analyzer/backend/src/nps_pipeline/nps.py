"""NPS, exact and pooled (README "NPS calculation").

Every figure is counted from survey rows. A rollup groups the rows underneath it and
counts again; it never averages lower-level NPS.

Input is a survey frame: one row per survey, unique `survey_id`, the 0-10 score in
`settings.NPS_SCORE_FIELD`, and whatever columns the caller groups by (agent,
supervisor, manager, site, business date, call type). Controllable NPS also reads
`controllable` from the survey's current Label (null when it has none); the driver
breakdown reads `primary_driver`, `comment` and `q5a_why_not_resolved`.
"""

from __future__ import annotations

from collections.abc import Sequence

import polars as pl

from . import settings
from .catalog import BUCKET_OF, BUCKETS, CONTROLLABLE_VALUES

NO_COMMENT, UNLABELED = "No comment", "Unlabeled"
SEGMENTS = (*BUCKETS, NO_COMMENT, UNLABELED)


def nps_group(score: pl.Expr) -> pl.Expr:
    return (
        pl.when(score >= settings.PROMOTER_MIN)
        .then(pl.lit("promoter"))
        .when(score <= settings.DETRACTOR_MAX)
        .then(pl.lit("detractor"))
        .otherwise(pl.lit("passive"))
    )


def _check(surveys: pl.DataFrame) -> None:
    """Pooling is only exact if each survey is counted once with a valid score."""
    dupes = surveys.filter(pl.col("survey_id").is_duplicated())["survey_id"].unique()
    if len(dupes):
        raise ValueError(f"survey_id repeated: {', '.join(dupes.sort().to_list())}")
    if not surveys.schema[settings.NPS_SCORE_FIELD].is_integer():
        raise ValueError(f"{settings.NPS_SCORE_FIELD} must be an integer score")
    score = pl.col(settings.NPS_SCORE_FIELD)
    bad = surveys.filter(score.is_null() | ~score.is_between(0, 10))
    if len(bad):
        raise ValueError(f"score missing or outside 0-10: {bad['survey_id'].to_list()}")


def _check_values(surveys: pl.DataFrame, column: str, allowed) -> None:
    """A Label value outside its closed set is rejected, never read as something."""
    bad = surveys.filter(pl.col(column).is_not_null() & ~pl.col(column).is_in(allowed))
    if len(bad):
        values = ", ".join(sorted(set(bad[column].to_list())))
        raise ValueError(f"{column} not allowed: {values}")


def _tally(
    frame: pl.DataFrame, by: Sequence[str], extra: Sequence[pl.Expr] = ()
) -> pl.DataFrame:
    """Counts the `_group` column per group, then derives NPS from the counts."""
    counts = [
        pl.col("_group").eq("promoter").sum().cast(pl.Int64).alias("promoters"),
        pl.col("_group").eq("passive").sum().cast(pl.Int64).alias("passives"),
        pl.col("_group").eq("detractor").sum().cast(pl.Int64).alias("detractors"),
        *extra,
    ]
    if by:
        out = frame.group_by(by).agg(counts).sort(by, nulls_last=True)
    else:
        out = frame.select(counts)
    surveys = pl.col("promoters") + pl.col("passives") + pl.col("detractors")
    return out.with_columns(surveys.alias("surveys")).with_columns(
        pl.when(pl.col("surveys") > 0)
        .then((pl.col("promoters") - pl.col("detractors")) * 100 / pl.col("surveys"))
        .alias("nps"),
        (pl.col("surveys") < settings.MIN_SAMPLE).alias("low_sample"),
    )


def nps_by(surveys: pl.DataFrame, by: Sequence[str] = ()) -> pl.DataFrame:
    """One row per group (one row overall when `by` is empty): counts, NPS, low sample.

    `nps` is exact (not rounded) and null when the group has no surveys.
    """
    _check(surveys)
    frame = surveys.with_columns(
        nps_group(pl.col(settings.NPS_SCORE_FIELD)).alias("_group")
    )
    return _tally(frame, list(by))


def controllable_nps_by(
    surveys: pl.DataFrame,
    by: Sequence[str] = (),
    rule: settings.ControllableRule | None = None,
) -> pl.DataFrame:
    """NPS without the detractors the agent could not control.

    A detractor is not controllable when its Label says "no" (and "partly", if
    `PARTLY_COUNTS_AGAINST_AGENT` is off). Rule "drop" removes those surveys;
    "reclassify" counts them as passives. A detractor with no Label stays counted.
    The result names the rule and how many detractors it moved.

    `surveys_answered` counts every survey, dropped ones included, and `low_sample`
    is judged on it: the same flag plain NPS shows for the same surveys.
    """
    rule = rule or settings.CONTROLLABLE_RULE
    if rule not in settings.CONTROLLABLE_RULES:
        raise ValueError(f"unknown controllable rule {rule!r}")
    _check(surveys)
    _check_values(surveys, "controllable", list(CONTROLLABLE_VALUES))
    not_controllable = (
        ["no"] if settings.PARTLY_COUNTS_AGAINST_AGENT else ["no", "partly"]
    )
    group = nps_group(pl.col(settings.NPS_SCORE_FIELD))
    moved = group.eq("detractor") & pl.col("controllable").is_in(
        not_controllable
    ).fill_null(False)
    frame = surveys.with_columns(
        pl.when(moved)
        .then(pl.lit("dropped" if rule == "drop" else "passive"))
        .otherwise(group)
        .alias("_group"),
        moved.alias("_moved"),
    )
    extra = [
        pl.col("_moved").sum().cast(pl.Int64).alias("not_controllable_detractors"),
        pl.len().cast(pl.Int64).alias("surveys_answered"),
    ]
    return _tally(frame, list(by), extra).with_columns(
        (pl.col("surveys_answered") < settings.MIN_SAMPLE).alias("low_sample"),
        pl.lit(rule).alias("rule"),
    )


def has_verbatim() -> pl.Expr:
    """A survey can get a Label only if it has a comment or a Q5a answer."""

    def filled(col: str) -> pl.Expr:
        return pl.col(col).str.strip_chars().str.len_chars().fill_null(0) > 0

    return filled("comment") | filled("q5a_why_not_resolved")


def detractor_breakdown(surveys: pl.DataFrame, by: Sequence[str] = ()) -> pl.DataFrame:
    """Detractors by the primary driver's Bucket, per group.

    Detractors without a Verbatim (no comment and no Q5a answer) count as "No
    comment", and those with a Verbatim but no Label as "Unlabeled", so the segments
    always add up to `detractors`. A driver outside the catalog is rejected. A group
    with no detractors keeps its row, with zeros.
    """
    _check(surveys)
    _check_values(surveys, "primary_driver", list(BUCKET_OF))
    is_detractor = nps_group(pl.col(settings.NPS_SCORE_FIELD)).eq("detractor")
    segment = (
        pl.when(~is_detractor)
        .then(None)
        .when(~has_verbatim())
        .then(pl.lit(NO_COMMENT))
        .when(pl.col("primary_driver").is_null())
        .then(pl.lit(UNLABELED))
        .otherwise(pl.col("primary_driver").replace_strict(BUCKET_OF))
    )
    frame = surveys.with_columns(
        is_detractor.alias("_detractor"), segment.alias("_segment")
    )
    counts = [pl.col("_detractor").sum().cast(pl.Int64).alias("detractors")] + [
        pl.col("_segment").eq(s).sum().cast(pl.Int64).alias(s) for s in SEGMENTS
    ]
    if by:
        return frame.group_by(list(by)).agg(counts).sort(list(by), nulls_last=True)
    return frame.select(counts)

"""From `backend/`, `PYTHONPATH=src uv run python -m nps_pipeline.synthetic`
(re)writes the Survey Event Feed and the Answer Key. Deterministic: rerunning
changes nothing.
"""

from __future__ import annotations

from .write import write_all


def main() -> None:
    generated = write_all()
    surveys = generated.surveys
    detractors = sum(s.event["q1_ltr"] <= 6 for s in surveys)
    labels = sum(s.label is not None for s in surveys)
    print(
        f"{len(surveys)} surveys ({detractors} detractors, {labels} with a Label) "
        f"from {surveys[0].day} to {surveys[-1].day}"
    )


if __name__ == "__main__":
    main()

"""Optional, evidence-grounded Azure OpenAI explanation layer."""

from __future__ import annotations

import os
import re
from typing import Literal

from pydantic import BaseModel, Field


class AIUnavailable(RuntimeError):
    pass


class AIAdvice(BaseModel):
    scope: str
    period: str
    observation: str
    evidence_ids: list[str]
    hypothesis: str
    recommended_action: str
    sample_caveat: str
    expected_effect_scenario: str
    confidence: Literal["low", "medium", "high"]
    requires_supervisor_review: bool = True


def model_name() -> str:
    return os.getenv("AZURE_OPENAI_MODEL", "gpt-5-mini")


def generate(store, evidence: dict) -> dict:
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
    key = os.getenv("AZURE_OPENAI_API_KEY", "")
    if not endpoint or not key:
        raise AIUnavailable("Azure AI is not configured; rule-based recommendations remain available")
    if evidence.get("status") != "ready":
        raise AIUnavailable("AI requires a recommendation with enough measured evidence")
    version = store.status()["published_version"]
    model = model_name()
    cached = store.cached_ai(version, evidence["evidence_id"], model)
    if cached:
        return cached
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise AIUnavailable("Install the optional openai package from requirements.txt") from exc
    packet = {
        "evidence_id": evidence["evidence_id"],
        "publication_version": version,
        "period": evidence["period"],
        "date": evidence["date"],
        "scope": "agent aggregate",
        "goal_seconds": 640,
        "calls": evidence["calls"],
        "aht_seconds": evidence["aht_seconds"],
        "gap_seconds": evidence["gap_seconds"],
        "excess_minutes": evidence["excess_minutes"],
        "average_components_seconds": {name: evidence[f"avg_{name}_seconds"] for name in ("talk", "hold", "wrap")},
        "same_queue_comparison_calls": evidence["comparison_calls"],
        "same_queue_comparison_components_seconds": evidence["comparison_component_seconds"],
        "measured_driver": evidence["driver"],
        "measured_driver_difference_seconds": evidence["driver_difference_seconds"],
    }
    import json

    client = OpenAI(base_url=endpoint + "/openai/v1/", api_key=key)
    try:
        response = client.responses.parse(
            model=model,
            input=[
                {"role": "system", "content": (
                    "Explain an AHT metric packet for a supervisor. Use only supplied numbers and evidence IDs. "
                    "Do not infer a root cause, customer issue, quality outcome, or employee intent. "
                    "Frame causes as hypotheses and actions as small tests. State that estimated effects are scenarios, "
                    "not promises. Never recommend disciplinary or automatic personnel action. "
                    "Do not include a person name. Keep each field brief.")},
                {"role": "user", "content": json.dumps(packet)},
            ],
            text_format=AIAdvice,
        )
    except Exception as exc:
        raise AIUnavailable(f"Azure AI request failed: {exc}") from exc
    parsed = response.output_parsed
    if parsed is None:
        raise AIUnavailable("Azure AI returned no structured recommendation")
    result = parsed.model_dump()
    if result["evidence_ids"] != [evidence["evidence_id"]]:
        raise AIUnavailable("AI response referenced unsupported evidence")
    if result["period"] != evidence["period"] or result["scope"] != "agent aggregate":
        raise AIUnavailable("AI response changed the evidence scope or period")
    if not result["requires_supervisor_review"]:
        raise AIUnavailable("AI response omitted supervisor review")
    supplied = [640, version, evidence["calls"], evidence["aht_seconds"],
                evidence["gap_seconds"], evidence["excess_minutes"],
                evidence["comparison_calls"], evidence["driver_difference_seconds"],
                *packet["average_components_seconds"].values(),
                *packet["same_queue_comparison_components_seconds"].values()]
    allowed_numbers = {round(float(value), places) for value in supplied for places in (0, 1, 2)}
    prose = " ".join(result[field] for field in ("observation", "hypothesis", "recommended_action",
                                                 "sample_caveat", "expected_effect_scenario"))
    if any(float(number) not in allowed_numbers for number in re.findall(r"(?<![\w])[-+]?\d+(?:\.\d+)?", prose)):
        raise AIUnavailable("AI response introduced a number absent from the evidence packet")
    result.update({"model": model, "publication_version": version, "evidence_id": evidence["evidence_id"]})
    store.save_ai(version, evidence["evidence_id"], model, result)
    return result

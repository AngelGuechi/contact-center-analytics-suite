"""Deterministic calculations for the synthetic call-avoidance demonstration.

The importer owns source validation and deduplication. This module consumes its
normalized records and never infers intent, speech, silence, or a ghost call.
Rates are compared as fractions; floating-point numbers are display values only.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction
import hashlib
import json

ENGINE_VERSION = "call-patterns-1"

DEFAULT_SETTINGS = {
    "version": "demo-1",
    "short_handle_seconds": 15,
    "daily_min_transactions": 20,
    "daily_min_signals": 3,
    "daily_min_rate": 0.10,
    "baseline_days": 14,
    "peer_min_transactions": 100,
    "self_min_transactions": 40,
    "self_min_active_days": 3,
    "rate_increase_pp": 5,
    "rate_multiplier": 2,
    "interval_min_minutes": 15,
    "interval_max_minutes": 90,
    "interval_min_transactions": 5,
    "interval_max_mean_talk_seconds": 30,
    "intraday_consecutive_intervals": 2,
}

_COUNT_SETTINGS = (
    "daily_min_transactions", "daily_min_signals", "baseline_days",
    "peer_min_transactions", "self_min_transactions", "self_min_active_days",
    "interval_min_transactions", "intraday_consecutive_intervals",
)
_NUMERIC_SETTINGS = (
    "daily_min_rate", "rate_increase_pp", "rate_multiplier",
    "interval_min_minutes", "interval_max_minutes", "interval_max_mean_talk_seconds",
)
_UNKNOWN_TYPE = "Unknown call type"


def _fraction(value):
    return Fraction(str(value))


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(kind, value):
    return f"{kind}-" + hashlib.sha256(_canonical({"engine_version": ENGINE_VERSION, "value": value}).encode("utf-8")).hexdigest()[:24]


def _unique_sources(records):
    sources = {}
    for record in records:
        for source in record.get("sources", []):
            # Original cells remain on the normalized transaction/snapshot row.
            # Evidence references need the exact locator, not thousands of
            # redundant copies of every baseline workbook cell.
            locator = {key: value for key, value in source.items() if key != "raw_cells"}
            sources[_canonical(locator)] = locator
    return [sources[key] for key in sorted(sources)]


def _settings(overrides):
    result = dict(DEFAULT_SETTINGS)
    if overrides:
        result.update(overrides)
    for key in _COUNT_SETTINGS:
        value = result[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{key} must be a positive integer")
    for key in _NUMERIC_SETTINGS:
        try:
            number = _fraction(result[key])
        except (ValueError, TypeError, ZeroDivisionError) as exc:
            raise ValueError(f"{key} must be a finite nonnegative number") from exc
        if number < 0:
            raise ValueError(f"{key} must be a finite nonnegative number")
    if _fraction(result["daily_min_rate"]) > 1:
        raise ValueError("daily_min_rate must be between 0 and 1")
    if _fraction(result["interval_min_minutes"]) > _fraction(result["interval_max_minutes"]):
        raise ValueError("interval_min_minutes must not exceed interval_max_minutes")
    thresholds = result["short_handle_seconds"]
    thresholds = thresholds.values() if isinstance(thresholds, dict) else [thresholds]
    for threshold in thresholds:
        try:
            valid = _fraction(threshold) >= 0
        except (ValueError, TypeError, ZeroDivisionError):
            valid = False
        if not valid:
            raise ValueError("short_handle_seconds must contain finite nonnegative numbers")
    return result


def _threshold(settings, call_type):
    value = settings["short_handle_seconds"]
    if isinstance(value, dict):
        value = value.get(call_type, value.get("default", DEFAULT_SETTINGS["short_handle_seconds"]))
    return _fraction(value)


def _is_signal(transaction, settings):
    return (
        _fraction(transaction["duration_seconds"]) <= _threshold(settings, transaction["call_type"])
        and transaction["transfers"] == 0
    )


def _measure(records, settings):
    count = len(records)
    signals = sum(_is_signal(row, settings) for row in records)
    return {
        "transactions": count,
        "signals": signals,
        "rate": float(Fraction(signals, count)) if count else None,
        "transferred_transactions": sum(row["transfers"] > 0 for row in records),
        "distinct_connections": len({row["connection_id"] for row in records}),
    }


def _identity(agent_id, roster):
    row = roster.get(agent_id, {})
    return {
        "agent_id": agent_id,
        "login_id": row.get("login_id", agent_id.removeprefix("unmapped:")),
        "name": row.get("name") or "Unassigned",
        "supervisor": row.get("supervisor") or "Unassigned",
        "manager": row.get("manager") or "Unassigned",
    }


def _mapped(agent_id, roster):
    return (agent_id in roster and not agent_id.startswith("unmapped:")
            and bool(roster[agent_id].get("login_id")))


def _baseline(records, settings, kind, missing_days, mapping_reason):
    result = _measure(records, settings)
    active_days = sorted({row["business_date"] for row in records})
    minimum = settings["peer_min_transactions" if kind == "peer" else "self_min_transactions"]
    failures = []
    if missing_days:
        failures.append("Missing or incomplete daily exports")
    if result["transactions"] < minimum:
        failures.append(f"Requires at least {minimum} transactions")
    if kind == "self" and len(active_days) < settings["self_min_active_days"]:
        failures.append(f"Requires at least {settings['self_min_active_days']} active days")
    if mapping_reason:
        failures.append(mapping_reason)
    result.update({
        "available": not failures,
        "label": "Available" if not failures else "Insufficient history",
        "missing_days": missing_days,
        "missing_dates": missing_days,
        "active_days": len(active_days),
        "active_dates": active_days,
        "minimum_transactions": minimum,
        "unavailable_reasons": failures,
    })
    return result


def _comparison(current, baseline, settings):
    if not baseline["available"] or not current["transactions"]:
        return {"qualifies": False, "increase_pp": None, "ratio": None, "ratio_label": "Unavailable"}
    current_rate = Fraction(current["signals"], current["transactions"])
    baseline_rate = Fraction(baseline["signals"], baseline["transactions"])
    increase = (current_rate - baseline_rate) * 100
    ratio = current_rate / baseline_rate if baseline_rate else None
    eligible = (
        current["transactions"] >= settings["daily_min_transactions"]
        and current["signals"] >= settings["daily_min_signals"]
        and current_rate >= _fraction(settings["daily_min_rate"])
    )
    return {
        "qualifies": eligible
        and increase >= _fraction(settings["rate_increase_pp"])
        and current_rate >= _fraction(settings["rate_multiplier"]) * baseline_rate,
        "increase_pp": float(increase),
        "ratio": float(ratio) if ratio is not None else None,
        "ratio_label": "Baseline zero" if baseline_rate == 0 else f"{float(ratio):.2f}×",
    }


def _daily_note(row):
    facts = (
        f"{row['signals']} short-handle signals / {row['transactions']} transactions "
        f"for {row['call_type']} on {row['business_date']}. "
        f"{row['transferred_transactions']} transferred transactions remain in the denominator."
    )
    for kind in ("peer", "self"):
        baseline = row[f"{kind}_baseline"]
        if baseline["available"]:
            facts += f" {kind.capitalize()} baseline: {baseline['signals']} / {baseline['transactions']}."
        else:
            facts += f" {kind.capitalize()} comparison unavailable: {'; '.join(baseline['unavailable_reasons'])}."
    if row["flagged"]:
        facts += " The measured pattern requires human review; these data do not establish intent."
    return facts


def _daily(dataset, settings, report_date, roster, roster_records, evidence):
    transactions = dataset.get("transactions", [])
    # A row's content and lineage are hashed once. Slices reference those hashes
    # so an agent's pooled comparison does not reserialize full raw workbooks.
    transaction_hashes = {
        id(row): _fingerprint("row", {
            **row, "sources": sorted(row.get("sources", []), key=_canonical),
        }) for row in transactions
    }
    current_rows = [row for row in transactions if row["business_date"] == report_date]
    current_groups = defaultdict(list)
    for row in current_rows:
        current_groups[(row["agent_id"], row["call_type"])].append(row)
    analyzed = date.fromisoformat(report_date)
    prior_days = [(analyzed - timedelta(days=offset)).isoformat()
                  for offset in range(settings["baseline_days"], 0, -1)]
    complete_days = set(dataset.get("complete_days", []))
    missing_days = [day for day in prior_days if day not in complete_days]
    current_complete = report_date in complete_days
    history = defaultdict(list)
    for row in transactions:
        if row["business_date"] in prior_days:
            history[row["call_type"]].append(row)
    slices = []
    for (agent_id, call_type), records in sorted(current_groups.items()):
        records = sorted(records, key=lambda row: row["transaction_id"])
        identity = _identity(agent_id, roster)
        mapped = _mapped(agent_id, roster)
        mapping_reason = "Unmapped identity" if not mapped else (
            "Unknown call type" if call_type == _UNKNOWN_TYPE else None)
        type_history = history[call_type]
        self_rows = [row for row in type_history if row["agent_id"] == agent_id]
        peer_rows = [row for row in type_history if row["agent_id"] != agent_id
                     and _mapped(row["agent_id"], roster)]
        current = _measure(records, settings)
        peer = _baseline(peer_rows, settings, "peer", missing_days, mapping_reason)
        personal = _baseline(self_rows, settings, "self", missing_days, mapping_reason)
        peer_comparison = _comparison(current, peer, settings)
        self_comparison = _comparison(current, personal, settings)
        reasons = []
        if current_complete:
            if peer_comparison["qualifies"]:
                reasons.append("peer_outlier")
            if self_comparison["qualifies"]:
                reasons.append("self_change")
        if reasons:
            label = "Possible call avoidance — review required"
        elif not current_complete:
            label = "Incomplete day — descriptive only"
        elif current["transactions"] < settings["daily_min_transactions"]:
            label = "Low sample"
        elif mapping_reason:
            label = mapping_reason
        elif not peer["available"] and not personal["available"]:
            label = "Insufficient history"
        else:
            label = "No qualifying daily pattern"
        signal_rows = [row for row in records if _is_signal(row, settings)]
        baseline_rows = sorted(peer_rows + self_rows, key=lambda row: row["transaction_id"])
        payload = {
            "report_date": report_date, "agent_id": agent_id, "call_type": call_type,
            "transaction_hashes": [transaction_hashes[id(row)] for row in records],
            "baseline_transaction_hashes": [transaction_hashes[id(row)] for row in baseline_rows],
            "settings": settings, "roster": roster_records,
            "prior_days": prior_days, "missing_days": missing_days,
            "current_complete": current_complete,
            "parser_version": dataset.get("parser_version", dataset.get("manifest", {}).get("parser_version")),
        }
        evidence_id = _fingerprint("daily", payload)
        row = {
            **identity, **current, "business_date": report_date, "call_type": call_type,
            "short_handle_seconds": float(_threshold(settings, call_type)),
            "complete": current_complete, "reasons": reasons, "flagged": bool(reasons),
            "label": label, "peer_baseline": peer, "self_baseline": personal,
            "peer_comparison": peer_comparison, "self_comparison": self_comparison,
            "evidence_id": evidence_id,
            "transaction_ids": [transaction["transaction_id"] for transaction in records],
            "signal_transaction_ids": [transaction["transaction_id"] for transaction in signal_rows],
        }
        row["note"] = row["deterministic_note"] = _daily_note(row)
        slices.append(row)
        evidence[evidence_id] = {
            "evidence_id": evidence_id, "kind": "daily", "rule_version": settings["version"],
            "report_date": report_date, "agent_id": agent_id, "call_type": call_type,
            "transaction_ids": row["transaction_ids"],
            "signal_transaction_ids": row["signal_transaction_ids"],
            "transactions": records, "signal_transactions": signal_rows,
            "baseline_transaction_ids": {
                "peer": sorted(transaction["transaction_id"] for transaction in peer_rows),
                "self": sorted(transaction["transaction_id"] for transaction in self_rows),
            },
            "sources": _unique_sources(records + baseline_rows),
            "settings": settings, "result": row,
        }
    agent_rows = defaultdict(list)
    agent_slices = defaultdict(list)
    for transaction in current_rows:
        agent_rows[transaction["agent_id"]].append(transaction)
    for row in slices:
        agent_slices[row["agent_id"]].append(row)
    agents = []
    for agent_id in sorted(set(roster) | set(agent_rows)):
        rows = agent_rows[agent_id]
        measured = _measure(rows, settings)
        own_slices = agent_slices[agent_id]
        flagged = any(row["flagged"] for row in own_slices)
        label = "Possible call avoidance — review required" if flagged else (
            "No transactions" if not rows else (
                "Incomplete day — descriptive only" if not current_complete else (
                    "Low sample" if all(row["label"] == "Low sample" for row in own_slices)
                    else "No qualifying daily pattern")))
        agents.append({
            **_identity(agent_id, roster), **measured,
            "flagged": flagged, "label": label,
            "qualifying_signals": sum(row["signals"] for row in own_slices if row["flagged"]),
            "reasons": sorted({reason for row in own_slices for reason in row["reasons"]}),
            "slices": own_slices, "evidence_ids": [row["evidence_id"] for row in own_slices],
            "business_date": report_date, "complete": current_complete,
        })
    agents.sort(key=lambda row: (
        -row["qualifying_signals"],
        -Fraction(row["signals"], row["transactions"]) if row["transactions"] else Fraction(0),
        row["agent_id"],
    ))
    rollups = {"site": {"name": "Imported demo site", **_measure(current_rows, settings)}}
    for field, plural in (("supervisor", "supervisors"), ("manager", "managers"), ("call_type", "call_types")):
        groups = defaultdict(list)
        for transaction in current_rows:
            if field == "call_type":
                group = transaction["call_type"]
            else:
                group = _identity(transaction["agent_id"], roster)[field]
            groups[group].append(transaction)
        rollups[plural] = [
            {"name": name, field: name, **_measure(rows, settings),
             "comparison_supported": name not in ("Unassigned", _UNKNOWN_TYPE),
             "descriptive_only": True}
            for name, rows in sorted(groups.items())
        ]
    return {"slices": slices, "agents": agents, "rollups": rollups}, {
        "report_date_complete": current_complete, "status": "Complete" if current_complete else "Incomplete",
        "baseline_days": prior_days, "missing_baseline_days": missing_days,
        "baseline_complete": not missing_days,
        "expected_days": sorted(set(dataset.get("expected_days", []))),
        "complete_days": sorted(complete_days),
        "missing_expected_days": sorted(set(dataset.get("expected_days", [])) - complete_days),
    }


def _timestamp(text):
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    # Importers supply UTC. A timezone-free test record is interpreted as UTC,
    # never using the workstation's timezone or current date.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _interval_issue(agent_id, previous, snapshot, reason):
    return {
        "type": "intraday_gap", "agent_id": agent_id, "reason": reason,
        "from_snapshot_id": previous.get("snapshot_id") if previous else None,
        "to_snapshot_id": snapshot.get("snapshot_id"),
        "captured_at": snapshot.get("captured_at"),
    }


def _intraday(dataset, settings, report_date, roster, roster_records, evidence):
    raw = [snapshot for snapshot in dataset.get("snapshots", [])
           if snapshot.get("business_date") == report_date]
    issues = []
    for snapshot in raw:
        issues.extend(snapshot.get("issues", []))
    snapshots = []
    invalid_time = False
    for snapshot in raw:
        try:
            captured = _timestamp(snapshot["captured_at"])
        except (KeyError, TypeError, ValueError):
            invalid_time = True
            issues.append({"type": "invalid_snapshot_time", "snapshot_id": snapshot.get("snapshot_id"),
                           "reason": "Unparseable snapshot time; adjacency cannot be established"})
            continue
        snapshots.append((captured, snapshot))
    if invalid_time:
        return {"leads": [], "intervals": [], "issues": issues}
    snapshots.sort(key=lambda pair: (pair[0], pair[1].get("snapshot_id", "")))
    timestamp_counts = defaultdict(int)
    for captured, snapshot in snapshots:
        timestamp_counts[captured] += 1
    observed_agents = {row["agent_id"] for _, snapshot in snapshots for row in snapshot.get("agents", [])}
    intervals, leads = [], []
    for agent_id in sorted(set(roster) | observed_agents):
        previous = None
        anchor = None
        streak = []
        active_lead = None
        for captured, snapshot in snapshots:
            rows = [row for row in snapshot.get("agents", []) if row["agent_id"] == agent_id]
            accepted = snapshot.get("accepted", True) and snapshot.get("status", "accepted") != "rejected"
            invalid = None
            if not accepted:
                invalid = "Rejected snapshot"
            elif timestamp_counts[captured] > 1:
                invalid = "Conflicting snapshot timestamps"
            elif not rows:
                invalid = "Missing agent row"
            elif len(rows) > 1:
                invalid = "Duplicate agent rows in snapshot"
            if invalid:
                issues.append(_interval_issue(agent_id, previous, snapshot, invalid))
                if previous:
                    intervals.append({
                        **_identity(agent_id, roster), "business_date": report_date,
                        "started_at": previous["captured_at"], "ended_at": snapshot["captured_at"],
                        "valid": False, "qualifies": False, "label": invalid,
                        "from_snapshot_id": previous.get("snapshot_id"),
                        "to_snapshot_id": snapshot.get("snapshot_id"),
                        "evidence_id": None,
                    })
                anchor = None
                streak = []
                active_lead = None
                previous = snapshot
                continue
            current = rows[0]
            if anchor is None:
                anchor = (captured, snapshot, current)
                previous = snapshot
                continue
            start_time, start_snapshot, start_row = anchor
            spacing = Fraction((captured - start_time) // timedelta(microseconds=1), 1_000_000)
            deltas = {field: _fraction(current[field]) - _fraction(start_row[field])
                      for field in ("calls", "talk_seconds", "hold_seconds", "handle_seconds", "transfers")}
            invalid = "Cumulative total decreased" if any(value < 0 for value in deltas.values()) else None
            if invalid is None and not (
                _fraction(settings["interval_min_minutes"]) * 60 <= spacing
                <= _fraction(settings["interval_max_minutes"]) * 60
            ):
                invalid = "Snapshot spacing outside configured interval"
            source_rows = [start_row, current]
            interval_id = _fingerprint("interval", {
                "agent_id": agent_id, "business_date": report_date,
                "start": {"snapshot_id": start_snapshot.get("snapshot_id"), "captured_at": start_snapshot["captured_at"], "row": start_row},
                "end": {"snapshot_id": snapshot.get("snapshot_id"), "captured_at": snapshot["captured_at"], "row": current},
                "settings": settings, "roster": roster_records,
                "parser_version": dataset.get("parser_version", dataset.get("manifest", {}).get("parser_version")),
            })
            calls = deltas["calls"]
            mean_talk = deltas["talk_seconds"] / calls if calls > 0 and not invalid else None
            mean_handle = deltas["handle_seconds"] / calls if calls > 0 and not invalid else None
            qualifies = not invalid and calls >= settings["interval_min_transactions"] and (
                mean_talk <= _fraction(settings["interval_max_mean_talk_seconds"]))
            interval = {
                **_identity(agent_id, roster), "business_date": report_date,
                "started_at": start_snapshot["captured_at"], "ended_at": snapshot["captured_at"],
                "from_snapshot_id": start_snapshot.get("snapshot_id"),
                "to_snapshot_id": snapshot.get("snapshot_id"),
                "minutes": float(spacing / 60), "valid": not invalid, "qualifies": bool(qualifies),
                "delta_calls": int(calls) if not invalid else None,
                "delta_talk_seconds": float(deltas["talk_seconds"]) if not invalid else None,
                "delta_hold_seconds": float(deltas["hold_seconds"]) if not invalid else None,
                "delta_handle_seconds": float(deltas["handle_seconds"]) if not invalid else None,
                "delta_transfers": int(deltas["transfers"]) if not invalid else None,
                "mean_talk_seconds": float(mean_talk) if mean_talk is not None else None,
                "mean_handle_seconds": float(mean_handle) if mean_handle is not None else None,
                "label": invalid or ("No completed transactions" if calls == 0 else (
                    "Qualifying low aggregate talk interval" if qualifies else "No qualifying interval")),
                "sources": _unique_sources(source_rows), "evidence_id": interval_id,
            }
            intervals.append(interval)
            evidence[interval_id] = {
                "evidence_id": interval_id, "kind": "intraday_interval",
                "rule_version": settings["version"], "agent_id": agent_id,
                "snapshot_ids": [start_snapshot.get("snapshot_id"), snapshot.get("snapshot_id")],
                "sources": interval["sources"], "snapshot_rows": source_rows,
                "settings": settings, "result": interval,
            }
            if invalid:
                issues.append(_interval_issue(agent_id, start_snapshot, snapshot, invalid))
                anchor = None
            else:
                anchor = (captured, snapshot, current)
            previous = snapshot
            if not qualifies:
                streak = []
                active_lead = None
                continue
            streak.append(interval)
            if len(streak) >= settings["intraday_consecutive_intervals"]:
                if active_lead is None:
                    active_lead = {**_identity(agent_id, roster), "business_date": report_date,
                                   "label": "Low aggregate talk time — weak lead"}
                    leads.append(active_lead)
                active_lead["intervals"] = list(streak)
    # Finalize once a streak is complete, avoiding stale overlapping evidence.
    for lead in leads:
        own_intervals = lead["intervals"]
        lead.update({
            "started_at": own_intervals[0]["started_at"], "ended_at": own_intervals[-1]["ended_at"],
            "interval_count": len(own_intervals),
            "delta_calls": sum(interval["delta_calls"] for interval in own_intervals),
            "delta_talk_seconds": sum(interval["delta_talk_seconds"] for interval in own_intervals),
            "delta_handle_seconds": sum(interval["delta_handle_seconds"] for interval in own_intervals),
            "sources": _unique_sources(own_intervals),
        })
        lead["mean_talk_seconds"] = lead["delta_talk_seconds"] / lead["delta_calls"]
        lead["mean_handle_seconds"] = lead["delta_handle_seconds"] / lead["delta_calls"]
        lead["note"] = lead["deterministic_note"] = (
            f"{lead['interval_count']} consecutive qualifying intervals from {lead['started_at']} "
            f"to {lead['ended_at']} contain {lead['delta_calls']} completed-transaction increase "
            f"and {lead['delta_talk_seconds']:g} aggregate talk seconds. "
            "This is a weak aggregate lead with no per-call evidence; human review is required."
        )
        lead_id = _fingerprint("intraday", {
            "interval_ids": [interval["evidence_id"] for interval in own_intervals],
            "settings": settings, "roster": roster_records,
        })
        lead["evidence_id"] = lead_id
        evidence[lead_id] = {
            "evidence_id": lead_id, "kind": "intraday", "rule_version": settings["version"],
            "agent_id": lead["agent_id"], "sources": lead["sources"],
            "intervals": own_intervals,
            "snapshot_ids": [own_intervals[0]["from_snapshot_id"]] +
                            [interval["to_snapshot_id"] for interval in own_intervals],
            "settings": settings, "result": lead,
        }
    leads.sort(key=lambda lead: (lead["started_at"], lead["agent_id"]))
    return {"leads": leads, "intervals": intervals, "issues": issues}


def _reconciliation(dataset, report_date, roster):
    """Show final source differences without repairing either source's totals."""
    accepted = []
    for snapshot in dataset.get("snapshots", []):
        if (snapshot.get("business_date") != report_date or not snapshot.get("accepted", True)
                or snapshot.get("status", "accepted") == "rejected"):
            continue
        try:
            accepted.append((_timestamp(snapshot["captured_at"]), snapshot))
        except (KeyError, TypeError, ValueError):
            continue
    accepted.sort(key=lambda pair: (pair[0], pair[1].get("snapshot_id", "")))
    latest = accepted[-1][1] if accepted else None
    latest_conflicts = bool(accepted) and sum(time == accepted[-1][0] for time, _ in accepted) > 1
    groups = defaultdict(list)
    for row in dataset.get("transactions", []):
        if row["business_date"] == report_date:
            groups[row["agent_id"]].append(row)
    daily_complete = report_date in set(dataset.get("complete_days", []))
    result = []
    for agent_id in sorted(set(roster) | set(groups)):
        records = groups[agent_id]
        rows = [row for row in latest.get("agents", []) if row["agent_id"] == agent_id] if latest else []
        live = rows[0] if len(rows) == 1 and not latest_conflicts else None
        handle = sum((_fraction(row["duration_seconds"]) for row in records), Fraction(0))
        transfers = sum(row["transfers"] for row in records)
        differences = {
            "calls_difference": len(records) - live["calls"] if live and daily_complete else None,
            "handle_seconds_difference": float(handle - _fraction(live["handle_seconds"])) if live and daily_complete else None,
            "transfers_difference": transfers - live["transfers"] if live and daily_complete else None,
        }
        result.append({
            **_identity(agent_id, roster), "business_date": report_date,
            "captured_at": latest.get("captured_at") if latest else None,
            "snapshot_id": latest.get("snapshot_id") if latest else None,
            "tool1_calls": live["calls"] if live else None,
            "tool1_handle_seconds": live["handle_seconds"] if live else None,
            "tool1_transfers": live["transfers"] if live else None,
            "tool2_transactions": len(records), "tool2_duration_seconds": float(handle),
            "tool2_complete": daily_complete,
            "tool2_transfers": transfers, **differences,
            "difference_direction": "Tool 2 minus Tool 1",
            "label": "Unavailable latest Tool 1 row" if not live else ("Incomplete Tool 2 day — differences unavailable" if not daily_complete else (
                "Matching measured totals" if all(value == 0 for value in differences.values())
                else "Different source totals")),
            "descriptive_only": True,
            "sources": _unique_sources(records + ([live] if live else [])),
        })
    return result


def build_report(dataset: dict, settings: dict | None = None, report_date: str | None = None) -> dict:
    """Compute one explicit business day's report from normalized source records.

    The function is pure: it reads no files, uses no model, network or wall clock,
    and does not mutate its arguments. A report without a supplied/manifest date
    uses the latest dated source, never the machine's current day.
    """
    configured = _settings(settings)
    manifest = dataset.get("manifest", {})
    selected_date = report_date or manifest.get("report_date")
    if not selected_date:
        dates = [row["business_date"] for row in dataset.get("transactions", [])]
        dates.extend(row["business_date"] for row in dataset.get("snapshots", []))
        dates.extend(dataset.get("expected_days", []))
        if not dates:
            raise ValueError("A report_date or a dated source is required")
        selected_date = max(dates)
    date.fromisoformat(selected_date)
    roster_records = sorted(dataset.get("roster", []), key=lambda row: _canonical(row))
    roster = {row["agent_id"]: row for row in roster_records}
    evidence = {}
    daily, coverage = _daily(dataset, configured, selected_date, roster, roster_records, evidence)
    intraday = _intraday(dataset, configured, selected_date, roster, roster_records, evidence)
    current = daily["rollups"]["site"]
    latest = max((snapshot.get("captured_at", "") for snapshot in dataset.get("snapshots", [])
                  if snapshot.get("business_date") == selected_date), default=None)
    return {
        "report_date": selected_date, "synthetic": bool(manifest.get("synthetic", False)),
        "engine_version": ENGINE_VERSION,
        "settings": configured, "daily": daily, "intraday": intraday, "evidence": evidence,
        "coverage": coverage, "issues": list(dataset.get("issues", [])),
        "import_summary": dict(dataset.get("import_summary", {})),
        "latest_source_time": latest,
        "reconciliation": _reconciliation(dataset, selected_date, roster),
        "annotations": list(dataset.get("annotations", manifest.get("annotations", manifest.get("incident_annotations", [])))),
        "overview": {
            "transactions": current["transactions"], "signals": current["signals"],
            "rate": current["rate"], "daily_agents": len(daily["agents"]),
            "daily_patterns": sum(agent["flagged"] for agent in daily["agents"]),
            "flagged_slices": sum(row["flagged"] for row in daily["slices"]),
            "intraday_leads": len(intraday["leads"]),
            "low_sample_agents": sum(agent["label"] == "Low sample" for agent in daily["agents"]),
            "unmapped_transactions": sum(row["transactions"] for row in daily["agents"]
                                         if not _mapped(row["agent_id"], roster)),
            "unknown_call_type_transactions": sum(row["transactions"] for row in daily["slices"]
                                                  if row["call_type"] == _UNKNOWN_TYPE),
        },
        "unavailable_signals": [
            "Ghost-call count or rate", "Per-transaction talk or silence", "Disconnect attribution",
            "Repeat-customer matching", "After-call work", "Not-ready duration", "Survey-to-call joins",
        ],
    }

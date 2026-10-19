"""Hand-worked acceptance cases for the model-independent calculation engine."""

import copy
from datetime import date, datetime, timedelta
import json
import unittest

from avoidance.detector import DEFAULT_SETTINGS, build_report


DAY = "2026-09-15"
PRIOR = [(date.fromisoformat(DAY) - timedelta(days=offset)).isoformat()
         for offset in range(14, 0, -1)]


def dataset():
    return {
        "roster": [
            {"agent_id": agent, "login_id": f"login-{agent}", "name": f"Agent {agent}",
             "supervisor": "Supervisor 1", "manager": "Manager 1"}
            for agent in ("a", "b", "c")
        ],
        "transactions": [], "snapshots": [],
        "complete_days": PRIOR + [DAY], "expected_days": PRIOR + [DAY],
        "manifest": {"report_date": DAY, "synthetic": True, "parser_version": "test-1"},
        "issues": [], "import_summary": {},
    }


def add_transactions(data, agent, count, signals, *, day=DAY, call_type="Billing", prefix=None):
    prefix = prefix or f"{agent}-{day}-{call_type}"
    for index in range(count):
        data["transactions"].append({
            "transaction_id": f"{prefix}-{index}", "connection_id": f"connection-{prefix}-{index}",
            "agent_id": agent, "login_id": f"login-{agent}", "business_date": day,
            "call_type": call_type, "duration_seconds": 15 if index < signals else 120,
            "transfers": 0, "holds": 0,
            "started_at": f"{day}T15:00:00Z", "ended_at": f"{day}T15:02:00Z",
            "sources": [{"file": f"Tool2-{day}.xlsx", "sha256": f"hash-{day}",
                         "sheet": "Data", "row": len(data["transactions"]) + 2, "import_id": f"import-{day}"}],
        })


def add_history(data, agent, count, signals, *, call_type="Billing"):
    remaining_signals = signals
    remaining_count = count
    for index, day in enumerate(PRIOR):
        daily_count = remaining_count // (len(PRIOR) - index)
        daily_signals = min(remaining_signals, daily_count)
        add_transactions(data, agent, daily_count, daily_signals, day=day, call_type=call_type)
        remaining_signals -= daily_signals
        remaining_count -= daily_count


def add_snapshots(data, samples, *, missing_indexes=(), day=DAY):
    start = datetime.fromisoformat(f"{day}T15:00:00+00:00")
    for index, (calls, talk) in enumerate(samples):
        captured = (start + timedelta(minutes=30 * index)).isoformat()
        rows = [] if index in missing_indexes else [{
            "agent_id": "a", "calls": calls, "talk_seconds": talk,
            "hold_seconds": 0, "handle_seconds": talk, "transfers": 0,
            "sources": [{"file": f"snapshot-{day}-{index}.xlsx", "sha256": f"snap-hash-{index}",
                         "sheet": "LiveAgentData", "row": 3, "import_id": f"snapshot-import-{index}"}],
        }]
        data["snapshots"].append({
            "snapshot_id": f"snapshot-{day}-{index}", "captured_at": captured,
            "business_date": day, "agents": rows, "issues": [],
        })


def slice_for(report, agent="a", call_type="Billing"):
    return next(row for row in report["daily"]["slices"]
                if row["agent_id"] == agent and row["call_type"] == call_type)


class DailyRulesTests(unittest.TestCase):
    def test_hand_worked_pattern_and_exact_evidence(self):
        data = dataset()
        add_transactions(data, "a", 30, 6)
        add_history(data, "a", 200, 4)
        add_history(data, "b", 600, 12)
        report = build_report(data)
        row = slice_for(report)
        self.assertEqual(row["reasons"], ["peer_outlier", "self_change"])
        self.assertEqual((row["signals"], row["transactions"], row["rate"]), (6, 30, .2))
        self.assertEqual(row["peer_baseline"]["rate"], .02)
        self.assertEqual(row["self_baseline"]["rate"], .02)
        self.assertEqual(row["peer_comparison"]["increase_pp"], 18)
        self.assertEqual(row["self_comparison"]["ratio"], 10)
        evidence = report["evidence"][row["evidence_id"]]
        self.assertEqual(len(evidence["transaction_ids"]), 30)
        self.assertEqual(len(evidence["signal_transaction_ids"]), 6)
        self.assertEqual(evidence["signal_transaction_ids"], row["signal_transaction_ids"])
        self.assertEqual(len(evidence["baseline_transaction_ids"]["peer"]), 600)
        self.assertEqual(report["overview"]["daily_patterns"], 1)
        self.assertIn("human review", row["note"])
        # The complete response remains a plain, serializable public API value.
        json.dumps(report, allow_nan=False)

    def test_absolute_boundary_still_requires_multiplier(self):
        data = dataset()
        add_transactions(data, "a", 20, 3)
        add_history(data, "b", 100, 10)
        row = slice_for(build_report(data))
        self.assertEqual(row["peer_comparison"]["increase_pp"], 5)
        self.assertEqual(row["peer_comparison"]["ratio"], 1.5)
        self.assertFalse(row["flagged"])

    def test_exact_five_point_and_two_times_boundaries_qualify(self):
        data = dataset()
        add_transactions(data, "a", 30, 3)
        add_history(data, "b", 100, 5)
        row = slice_for(build_report(data))
        self.assertEqual(row["peer_comparison"]["increase_pp"], 5)
        self.assertEqual(row["peer_comparison"]["ratio"], 2)
        self.assertEqual(row["reasons"], ["peer_outlier"])

    def test_zero_baseline_has_a_label_and_no_infinity(self):
        data = dataset()
        add_transactions(data, "a", 20, 3)
        add_history(data, "b", 100, 0)
        row = slice_for(build_report(data))
        self.assertTrue(row["flagged"])
        self.assertEqual(row["peer_comparison"]["ratio_label"], "Baseline zero")
        self.assertIsNone(row["peer_comparison"]["ratio"])
        self.assertFalse(row["self_baseline"]["available"])

    def test_small_sample_and_transfer_exclusion(self):
        data = dataset()
        add_transactions(data, "a", 10, 3)
        add_history(data, "b", 100, 2)
        row = slice_for(build_report(data))
        self.assertEqual(row["label"], "Low sample")
        self.assertFalse(row["flagged"])
        data = dataset()
        add_transactions(data, "a", 20, 3)
        data["transactions"][2]["transfers"] = 1
        add_history(data, "b", 100, 0)
        row = slice_for(build_report(data))
        self.assertEqual((row["signals"], row["transactions"], row["transferred_transactions"]), (2, 20, 1))
        self.assertEqual(row["rate"], .10)
        self.assertFalse(row["flagged"])

    def test_incomplete_current_day_is_descriptive(self):
        data = dataset()
        add_transactions(data, "a", 20, 3)
        add_history(data, "b", 100, 0)
        data["complete_days"].remove(DAY)
        report = build_report(data)
        row = slice_for(report)
        self.assertTrue(row["peer_comparison"]["qualifies"])
        self.assertFalse(row["flagged"])
        self.assertEqual(row["label"], "Incomplete day — descriptive only")
        self.assertEqual(report["coverage"]["status"], "Incomplete")

    def test_missing_one_calendar_day_disables_both_baselines(self):
        data = dataset()
        add_transactions(data, "a", 30, 6)
        add_history(data, "a", 200, 4)
        add_history(data, "b", 600, 12)
        data["complete_days"].remove(PRIOR[3])
        report = build_report(data)
        row = slice_for(report)
        self.assertEqual(row["peer_baseline"]["missing_days"], [PRIOR[3]])
        self.assertFalse(row["peer_baseline"]["available"])
        self.assertFalse(row["self_baseline"]["available"])
        self.assertFalse(row["flagged"])
        self.assertEqual(row["label"], "Insufficient history")

    def test_current_day_is_not_history_and_self_needs_three_days(self):
        data = dataset()
        add_transactions(data, "a", 30, 6)
        add_transactions(data, "b", 100, 0)
        add_transactions(data, "a", 50, 0, day=PRIOR[-1])
        row = slice_for(build_report(data))
        self.assertEqual(row["peer_baseline"]["transactions"], 0)
        self.assertEqual(row["self_baseline"]["active_days"], 1)
        self.assertFalse(row["self_baseline"]["available"])
        self.assertFalse(row["flagged"])

    def test_peer_excludes_focal_and_baselines_pool_counts(self):
        data = dataset()
        add_transactions(data, "a", 30, 6)
        add_history(data, "a", 100, 50)
        add_transactions(data, "b", 20, 3, day=PRIOR[0])
        add_transactions(data, "c", 80, 2, day=PRIOR[-1])
        row = slice_for(build_report(data))
        self.assertEqual(row["peer_baseline"]["transactions"], 100)
        self.assertEqual(row["peer_baseline"]["signals"], 5)
        self.assertEqual(row["peer_baseline"]["rate"], .05)
        self.assertEqual(row["reasons"], ["peer_outlier"])

    def test_site_and_team_rollups_pool_transaction_counts(self):
        data = dataset()
        add_transactions(data, "a", 20, 3)
        add_transactions(data, "b", 80, 2)
        report = build_report(data)
        site = report["daily"]["rollups"]["site"]
        team = report["daily"]["rollups"]["supervisors"][0]
        self.assertEqual((site["signals"], site["transactions"], site["rate"]), (5, 100, .05))
        self.assertEqual(team["rate"], .05)
        zero_agent = next(row for row in report["daily"]["agents"] if row["agent_id"] == "c")
        self.assertIsNone(zero_agent["rate"])
        self.assertEqual(zero_agent["label"], "No transactions")

    def test_call_type_slices_do_not_mix_for_eligibility(self):
        data = dataset()
        add_transactions(data, "a", 10, 3, call_type="Billing")
        add_transactions(data, "a", 10, 3, call_type="Service")
        add_history(data, "b", 100, 0, call_type="Billing")
        add_history(data, "b", 100, 0, call_type="Service")
        report = build_report(data)
        self.assertTrue(all(row["label"] == "Low sample" for row in report["daily"]["slices"]))
        self.assertEqual(report["overview"]["daily_patterns"], 0)

    def test_unknown_mapping_is_visible_but_not_compared(self):
        data = dataset()
        add_transactions(data, "unmapped:orphan", 20, 5)
        add_transactions(data, "a", 20, 5, call_type="Unknown call type")
        add_history(data, "b", 100, 0)
        add_history(data, "b", 100, 0, call_type="Unknown call type")
        report = build_report(data)
        orphan = slice_for(report, "unmapped:orphan")
        unknown = slice_for(report, "a", "Unknown call type")
        self.assertEqual(orphan["name"], "Unassigned")
        self.assertFalse(orphan["flagged"])
        self.assertFalse(unknown["flagged"])
        self.assertEqual(report["overview"]["unmapped_transactions"], 20)
        self.assertEqual(report["overview"]["unknown_call_type_transactions"], 20)

    def test_unmapped_peer_is_not_a_named_type_comparison(self):
        data = dataset()
        add_transactions(data, "a", 20, 5)
        add_history(data, "unmapped:orphan", 500, 0)
        row = slice_for(build_report(data))
        self.assertEqual(row["peer_baseline"]["transactions"], 0)
        self.assertFalse(row["flagged"])

    def test_evidence_is_stable_for_order_and_changes_with_source_rules_or_roster(self):
        data = dataset()
        add_transactions(data, "a", 20, 3)
        add_history(data, "b", 100, 0)
        original_copy = copy.deepcopy(data)
        first = slice_for(build_report(data))["evidence_id"]
        self.assertEqual(data, original_copy)
        reordered = copy.deepcopy(data)
        reordered["transactions"].reverse()
        reordered["roster"].reverse()
        self.assertEqual(first, slice_for(build_report(reordered))["evidence_id"])
        changed = copy.deepcopy(data)
        changed["transactions"][0]["sources"][0]["sha256"] = "new-file-hash"
        self.assertNotEqual(first, slice_for(build_report(changed))["evidence_id"])
        self.assertNotEqual(first, slice_for(build_report(data, {"version": "demo-2"}))["evidence_id"])
        changed = copy.deepcopy(data)
        changed["roster"][0]["supervisor"] = "Other supervisor"
        self.assertNotEqual(first, slice_for(build_report(changed))["evidence_id"])

    def test_per_type_duration_settings_are_inclusive(self):
        data = dataset()
        add_transactions(data, "a", 20, 3)
        row = slice_for(build_report(data, {"short_handle_seconds": {"Billing": 14}}))
        self.assertEqual(row["signals"], 0)
        row = slice_for(build_report(data, {"short_handle_seconds": {"Billing": 15}}))
        self.assertEqual(row["signals"], 3)


class IntradayRulesTests(unittest.TestCase):
    def test_exact_weak_lead_has_snapshot_evidence_and_no_transaction_claim(self):
        data = dataset()
        add_snapshots(data, [(10, 3000), (15, 3120), (20, 3270)])
        report = build_report(data)
        self.assertEqual(len(report["intraday"]["leads"]), 1)
        lead = report["intraday"]["leads"][0]
        self.assertEqual([interval["mean_talk_seconds"] for interval in lead["intervals"]], [24, 30])
        self.assertEqual(lead["delta_calls"], 10)
        self.assertEqual(lead["delta_talk_seconds"], 270)
        self.assertEqual(len(lead["sources"]), 3)
        self.assertNotIn("transaction_ids", report["evidence"][lead["evidence_id"]])
        self.assertEqual(len(report["evidence"][lead["evidence_id"]]["snapshot_ids"]), 3)

    def test_extended_streak_creates_one_merged_lead(self):
        data = dataset()
        add_snapshots(data, [(10, 3000), (15, 3120), (20, 3270), (25, 3420)])
        report = build_report(data)
        self.assertEqual(len(report["intraday"]["leads"]), 1)
        self.assertEqual(report["intraday"]["leads"][0]["interval_count"], 3)
        lead_evidence = [item for item in report["evidence"].values() if item["kind"] == "intraday"]
        self.assertEqual(len(lead_evidence), 1)

    def test_decrease_suppresses_pair_and_next_snapshot_only_reanchors(self):
        data = dataset()
        add_snapshots(data, [(10, 1000), (15, 1100), (14, 1090), (19, 1190), (24, 1290), (29, 1390)])
        report = build_report(data)
        leads = report["intraday"]["leads"]
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["started_at"], data["snapshots"][3]["captured_at"])
        invalid = next(row for row in report["intraday"]["intervals"] if not row["valid"])
        self.assertEqual(invalid["label"], "Cumulative total decreased")
        self.assertIsNone(invalid["delta_calls"])
        self.assertTrue(any(issue["reason"] == "Cumulative total decreased"
                            for issue in report["intraday"]["issues"]))

    def test_missing_agent_row_breaks_without_bridging(self):
        data = dataset()
        add_snapshots(data, [(10, 1000), (15, 1100), (20, 1200), (25, 1300), (30, 1400), (35, 1500)],
                      missing_indexes=(2,))
        report = build_report(data)
        leads = report["intraday"]["leads"]
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["started_at"], data["snapshots"][3]["captured_at"])
        valid = [row for row in report["intraday"]["intervals"] if row["valid"]]
        self.assertFalse(any(row["from_snapshot_id"] == "snapshot-2026-09-15-1"
                             and row["to_snapshot_id"] == "snapshot-2026-09-15-3" for row in valid))

    def test_zero_calls_breaks_streak_and_remains_null_mean(self):
        data = dataset()
        add_snapshots(data, [(10, 1000), (15, 1100), (15, 1100), (20, 1200)])
        report = build_report(data)
        self.assertEqual(report["intraday"]["leads"], [])
        zero = next(row for row in report["intraday"]["intervals"] if row.get("delta_calls") == 0)
        self.assertEqual(zero["label"], "No completed transactions")
        self.assertIsNone(zero["mean_talk_seconds"])

    def test_conflicting_time_breaks_streak(self):
        data = dataset()
        add_snapshots(data, [(10, 1000), (15, 1100), (20, 1200), (25, 1300)])
        data["snapshots"][2]["captured_at"] = data["snapshots"][1]["captured_at"]
        report = build_report(data)
        self.assertEqual(report["intraday"]["leads"], [])
        self.assertTrue(any(issue["reason"] == "Conflicting snapshot timestamps"
                            for issue in report["intraday"]["issues"]))

    def test_interval_spacing_bounds_are_inclusive(self):
        data = dataset()
        add_snapshots(data, [(10, 1000), (15, 1100), (20, 1200)])
        data["snapshots"][1]["captured_at"] = f"{DAY}T15:15:00Z"
        data["snapshots"][2]["captured_at"] = f"{DAY}T16:45:00Z"
        report = build_report(data)
        self.assertEqual([row["minutes"] for row in report["intraday"]["intervals"]
                          if row["agent_id"] == "a"], [15, 90])
        self.assertEqual(len(report["intraday"]["leads"]), 1)

    def test_no_subtraction_across_midnight(self):
        data = dataset()
        add_snapshots(data, [(10, 1000), (15, 1100)], day=PRIOR[-1])
        add_snapshots(data, [(20, 1200)], day=DAY)
        report = build_report(data)
        self.assertEqual(report["intraday"]["intervals"], [])
        self.assertEqual(report["intraday"]["leads"], [])

    def test_lead_lineage_changes_with_source_rows(self):
        data = dataset()
        add_snapshots(data, [(10, 1000), (15, 1100), (20, 1200)])
        first = build_report(data)["intraday"]["leads"][0]["evidence_id"]
        data["snapshots"][1]["agents"][0]["sources"][0]["sha256"] = "replacement"
        second = build_report(data)["intraday"]["leads"][0]["evidence_id"]
        self.assertNotEqual(first, second)

    def test_unparseable_snapshot_cannot_be_skipped_to_bridge_a_lead(self):
        data = dataset()
        add_snapshots(data, [(10, 1000), (15, 1100), (20, 1200), (25, 1300)])
        data["snapshots"][1]["captured_at"] = "missing timestamp"
        report = build_report(data)
        self.assertEqual(report["intraday"]["leads"], [])
        self.assertTrue(any(issue["type"] == "invalid_snapshot_time"
                            for issue in report["intraday"]["issues"]))


class ReconciliationTests(unittest.TestCase):
    def test_difference_is_descriptive_and_neither_source_is_repaired(self):
        data = dataset()
        add_transactions(data, "a", 2, 1)
        add_snapshots(data, [(3, 100)])
        before = copy.deepcopy(data)
        report = build_report(data)
        row = next(item for item in report["reconciliation"] if item["agent_id"] == "a")
        self.assertEqual(row["tool1_calls"], 3)
        self.assertEqual(row["tool2_transactions"], 2)
        self.assertEqual(row["tool2_duration_seconds"], 135)
        self.assertEqual(row["calls_difference"], -1)
        self.assertEqual(row["handle_seconds_difference"], 35)
        self.assertEqual(row["label"], "Different source totals")
        self.assertTrue(row["descriptive_only"])
        self.assertEqual(data, before)

    def test_missing_final_row_is_unavailable_and_annotation_is_preserved(self):
        data = dataset()
        add_snapshots(data, [(3, 100), (4, 120)], missing_indexes=(1,))
        data["manifest"]["annotations"] = [{"annotation_id": "issue-1", "note": "Synthetic site outage"}]
        report = build_report(data)
        row = next(item for item in report["reconciliation"] if item["agent_id"] == "a")
        self.assertIsNone(row["tool1_calls"])
        self.assertIsNone(row["calls_difference"])
        self.assertEqual(row["label"], "Unavailable latest Tool 1 row")
        self.assertEqual(report["annotations"], data["manifest"]["annotations"])

    def test_original_cells_remain_on_transactions_and_locators_are_compact(self):
        data = dataset()
        add_transactions(data, "a", 20, 3)
        data["transactions"][0]["sources"][0]["raw_cells"] = {"Duration": "00:00:15"}
        report = build_report(data)
        row = slice_for(report)
        evidence = report["evidence"][row["evidence_id"]]
        self.assertEqual(evidence["transactions"][0]["sources"][0]["raw_cells"], {"Duration": "00:00:15"})
        self.assertTrue(all("raw_cells" not in source for source in evidence["sources"]))


class ConfigurationTests(unittest.TestCase):
    def test_invalid_settings_are_visible(self):
        for overrides in ({"baseline_days": 0}, {"daily_min_rate": 2},
                          {"rate_multiplier": "NaN"}, {"short_handle_seconds": -1},
                          {"interval_min_minutes": 100, "interval_max_minutes": 90}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                build_report(dataset(), overrides)

    def test_report_date_uses_source_and_does_not_mutate_defaults(self):
        data = dataset()
        data["manifest"].pop("report_date")
        self.assertEqual(build_report(data)["report_date"], DAY)
        build_report(data, {"version": "custom"})
        self.assertEqual(DEFAULT_SETTINGS["version"], "demo-1")


if __name__ == "__main__":
    unittest.main()

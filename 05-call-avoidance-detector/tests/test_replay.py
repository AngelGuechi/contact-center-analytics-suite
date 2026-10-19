"""Replay stages must pass through the actual native importer and store."""
from pathlib import Path
import tempfile
import unittest

from avoidance.replay import replay_folder
from avoidance.store import LocalStore


class ReplayTests(unittest.TestCase):
    def test_lead_arrives_before_the_complete_daily_report(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = LocalStore(root / "data")
            expected = [(False, 0, 0), (False, 0, 0), (False, 0, 1), (True, 1, 1)]
            for stage, (complete, patterns, leads) in enumerate(expected, 1):
                with self.subTest(stage=stage):
                    report = store.import_folder(replay_folder(root / "inputs", stage))
                    self.assertEqual(report["coverage"]["report_date_complete"], complete)
                    self.assertEqual(report["overview"]["daily_patterns"], patterns)
                    self.assertEqual(report["overview"]["intraday_leads"], leads)
                    self.assertTrue(report["synthetic"])
                    self.assertEqual(report["import_summary"]["files_rejected"], 0)
                    if stage < 4:
                        self.assertTrue(all(row["calls_difference"] is None and not row["tool2_complete"] for row in report["reconciliation"]))
                    if stage == 3:
                        lead = report["intraday"]["leads"][0]
                        evidence = store.evidence(lead["evidence_id"])
                        self.assertEqual(evidence["transaction_count"], 0)
                        self.assertEqual(len(evidence["sources"]), 3)
                        self.assertTrue(all(source.get("raw_cells") for source in evidence["sources"]))
                        store.save_review(lead["evidence_id"], "Needs review", "Replay reviewer", "Inspected the original aggregate source cells.")
            self.assertEqual(len(store.reviews()), 1)
            self.assertTrue(replay_folder(root / "inputs", 4).exists())

    def test_invalid_stage_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                replay_folder(Path(folder), 0)

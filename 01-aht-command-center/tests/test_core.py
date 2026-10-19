import io
import tempfile
import unittest
from datetime import datetime

from openpyxl import Workbook

from core import AHTStore, HEADERS, ImportProblem


def workbook(calls):
    book = Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    sheet.append(HEADERS)
    for transaction, start, talk, hold, wrap in calls:
        sheet.append((transaction, "A01", "Agent One", "Supervisor One", "Team One", "Support",
                      start, start.replace(minute=start.minute + 1), talk, hold, wrap, "Voice", "Inbound"))
    content = io.BytesIO()
    book.save(content)
    book.close()
    return content.getvalue()


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = AHTStore(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_weighted_duplicate_revision_and_history(self):
        first = workbook([("1", datetime(2026, 9, 30, 9, 1), 500, 100, 100),
                          ("2", datetime(2026, 9, 30, 9, 3), 400, 100, 100)])
        second = workbook([("3", datetime(2026, 10, 1, 9, 1), 300, 100, 100)])
        name1 = "Calls_2026-09-30_0900_2026-09-30_0930_r01.xlsx"
        name2 = "Calls_2026-10-01_0900_2026-10-01_0930_r01.xlsx"
        self.store.import_bytes(first, name1)
        self.assertEqual(self.store.import_bytes(first, name1)["status"], "duplicate")
        self.store.import_bytes(second, name2)
        d = self.store.dashboard("2026-10-01")
        self.assertEqual(d["cards"]["today"]["aht_seconds"], 500)
        self.assertEqual(d["cards"]["yesterday"]["aht_seconds"], 650)
        self.assertEqual(d["cards"]["mtd"]["calls"], 1)
        correction = workbook([("1", datetime(2026, 9, 30, 9, 1), 500, 100, 100)])
        self.store.import_bytes(correction, "Calls_2026-09-30_0900_2026-09-30_0930_r02.xlsx")
        d = self.store.dashboard("2026-10-01")
        self.assertEqual(d["cards"]["yesterday"]["calls"], 1)
        self.assertEqual(d["cards"]["yesterday"]["aht_seconds"], 700)
        self.assertEqual(self.store.total_calls(), 2)
        self.assertTrue((self.store.history_dir / "2026" / "09" / "30" / name1).exists())

    def test_conflicting_call_and_bad_window_keep_last_good(self):
        first = workbook([("1", datetime(2026, 9, 30, 9, 1), 500, 100, 100)])
        self.store.import_bytes(first, "Calls_2026-09-30_0900_2026-09-30_0930_r01.xlsx")
        conflict = workbook([("1", datetime(2026, 9, 30, 9, 31), 100, 100, 100)])
        with self.assertRaisesRegex(ImportProblem, "Contradictory active Transaction ID"):
            self.store.import_bytes(conflict, "Calls_2026-09-30_0930_2026-09-30_1000_r01.xlsx")
        outside = workbook([("2", datetime(2026, 9, 30, 10, 1), 500, 100, 100)])
        with self.assertRaisesRegex(ImportProblem, "outside"):
            self.store.import_bytes(outside, "Calls_2026-09-30_0930_2026-09-30_1000_r01.xlsx")
        self.assertEqual(self.store.status()["published_version"], 1)
        self.assertEqual(self.store.total_calls(), 1)
        self.assertFalse((self.store.history_dir / "2026" / "09" / "30" /
                          "Calls_2026-09-30_0930_2026-09-30_1000_r01.xlsx").exists())

    def test_existing_history_is_not_deleted_on_failed_import(self):
        file = workbook([("1", datetime(2026, 9, 30, 9, 1), 500, 100, 100)])
        folder = self.store.history_dir / "2026" / "09" / "30"
        folder.mkdir(parents=True)
        target = folder / "Calls_2026-09-30_0900_2026-09-30_0930_r01.xlsx"
        target.write_bytes(b"preserve")
        with self.assertRaisesRegex(ImportProblem, "History already contains"):
            self.store.import_bytes(file, target.name)
        self.assertEqual(target.read_bytes(), b"preserve")


if __name__ == "__main__":
    unittest.main()

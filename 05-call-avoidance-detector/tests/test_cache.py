"""Lossless compact persistence and isolated native descriptor-pool checks."""
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from avoidance.cache import CACHE_VERSION, load_dataset, save_dataset
from avoidance.readers import read_dataset

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class CompactCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = read_dataset(FIXTURES)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "normalized.json"

    def tearDown(self):
        self.temporary.cleanup()

    def test_native_roundtrip_preserves_every_cell_and_source_locator(self):
        before = json.dumps(self.data, ensure_ascii=False)
        save_dataset(self.path, self.data)
        restored = load_dataset(self.path)
        self.assertEqual(restored, self.data)
        self.assertEqual(json.dumps(restored, ensure_ascii=False), before)
        self.assertEqual(json.dumps(self.data, ensure_ascii=False), before)
        source = restored["transactions"][0]["sources"][0]
        self.assertEqual(len(source["raw_cells"]), 42)
        self.assertTrue(source["raw_cells"]["X01"]["type"])
        self.assertIn("number_format", source["raw_cells"]["X01"])
        self.assertEqual(source["row"], 2)
        self.assertEqual(len(source["sha256"]), 64)

    def test_compact_representation_deduplicates_cells_and_restores_shared_values(self):
        save_dataset(self.path, self.data)
        encoded = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(encoded["cache_format"], CACHE_VERSION)
        self.assertLess(len(encoded["cells"]), len(self.data["transactions"]) * 42)
        self.assertLess(self.path.stat().st_size, len(json.dumps(self.data).encode("utf-8")))
        restored = load_dataset(self.path)
        first, second = restored["transactions"][:2]
        self.assertIs(first["sources"][0]["raw_cells"]["X01"], second["sources"][0]["raw_cells"]["X01"])

    def test_legacy_plain_cache_remains_readable(self):
        self.path.write_text(json.dumps(self.data), encoding="utf-8")
        self.assertEqual(load_dataset(self.path), self.data)

    def test_failed_write_does_not_replace_previous_valid_cache(self):
        save_dataset(self.path, self.data)
        initial = self.path.read_bytes()
        with self.assertRaises(ValueError):
            save_dataset(self.path, {"invalid": float("nan")})
        self.assertEqual(self.path.read_bytes(), initial)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_rejects_unsupported_version_and_invalid_references(self):
        save_dataset(self.path, self.data)
        valid = json.loads(self.path.read_text(encoding="utf-8"))
        for field, value in (("cache_format", "future-unknown"), ("schemas", [[]])):
            with self.subTest(field=field):
                invalid = {**valid, field: value}
                self.path.write_text(json.dumps(invalid), encoding="utf-8")
                self.assertRaises(ValueError, load_dataset, self.path)
        source = valid["dataset"]["transactions"][0]["sources"][0]
        source["raw_cells"]["cells"][0] = len(valid["cells"])
        self.path.write_text(json.dumps(valid), encoding="utf-8")
        self.assertRaises(ValueError, load_dataset, self.path)

    def test_concurrent_imports_have_separate_contexts_and_equal_api_values(self):
        with ThreadPoolExecutor(max_workers=2) as executor:
            first, second = list(executor.map(read_dataset, (FIXTURES, FIXTURES)))
        self.assertEqual(first, second)
        first_blank = first["transactions"][0]["sources"][0]["raw_cells"]["X01"]
        same_import_blank = first["transactions"][1]["sources"][0]["raw_cells"]["X01"]
        second_blank = second["transactions"][0]["sources"][0]["raw_cells"]["X01"]
        self.assertIs(first_blank, same_import_blank)
        self.assertIsNot(first_blank, second_blank)
        subsequent = read_dataset(FIXTURES)
        self.assertIsNot(first_blank, subsequent["transactions"][0]["sources"][0]["raw_cells"]["X01"])


if __name__ == "__main__":
    unittest.main()

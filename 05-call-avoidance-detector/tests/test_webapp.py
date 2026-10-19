"""Real localhost HTTP seam, using no model or external service."""
import json
from pathlib import Path
import shutil
import socket
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import uvicorn

from avoidance.webapp import create_app


class LocalHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.app = create_app(Path(cls.temporary.name), seed_demo=False)
        cls.app.state.store.import_folder(Path(__file__).resolve().parents[1] / "fixtures")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            cls.port = probe.getsockname()[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.server = uvicorn.Server(uvicorn.Config(cls.app, host="127.0.0.1", port=cls.port, log_level="critical"))
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        for _ in range(50):
            try:
                with urlopen(cls.base + "/api/health", timeout=.2):
                    break
            except OSError:
                time.sleep(.05)
        else:
            raise RuntimeError("Test server failed to start")

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(5)
        cls.temporary.cleanup()

    def request(self, path, data=None, headers=None):
        active = {"X-Call-Review": "1", **(headers or {})}
        payload = json.dumps(data).encode() if data is not None else None
        if payload is not None:
            active["Content-Type"] = "application/json"
        request = Request(self.base + path, data=payload, headers=active)
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status, json.load(response)

    def test_health_identity_and_report_exclude_bulk_evidence(self):
        status, health = self.request("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["product"], "call-avoidance-review")
        status, report = self.request("/api/report")
        self.assertEqual(status, 200)
        self.assertNotIn("evidence", report)
        self.assertEqual(report["overview"]["daily_patterns"], 1)
        self.assertEqual(report["overview"]["intraday_leads"], 1)

    def test_transaction_pagination_and_exact_review(self):
        _, report = self.request("/api/report")
        row = next(s for s in report["daily"]["slices"] if s["flagged"])
        evidence_id = row["evidence_id"]
        status, evidence = self.request(f"/api/evidence/{evidence_id}?page_size=5")
        self.assertEqual(status, 200)
        self.assertEqual(len(evidence["transactions"]), 5)
        self.assertEqual(evidence["transaction_count"], 30)
        status, peers = self.request(f"/api/evidence/{evidence_id}?page_size=5&scope=peer")
        self.assertEqual(status, 200)
        self.assertEqual(peers["transaction_count"], 2800)
        self.assertEqual(len(peers["transactions"]), 5)
        self.assertTrue(all(t["agent_id"] != row["agent_id"] for t in peers["transactions"]))
        self.assertTrue(all(t["sources"][0]["raw_cells"] for t in peers["transactions"]))
        self.assertNotIn("baseline_transaction_ids", peers)
        status, saved = self.request("/api/reviews", {"evidence_id": evidence_id, "state": "Technical issue", "reviewer": "Demo reviewer", "note": "Reviewed the supporting source rows."})
        self.assertEqual(status, 200)
        self.assertEqual(saved["evidence_id"], evidence_id)
        _, refreshed = self.request("/api/report")
        self.assertEqual(refreshed["reviews"][evidence_id]["state"], "Technical issue")
        self.assertNotIn("sources", refreshed["reviews"][evidence_id])
        self.assertNotIn("transaction_ids", refreshed["reviews"][evidence_id])

    def test_stale_or_missing_evidence_and_invalid_page_are_visible(self):
        self.assertEqual(self.request("/api/evidence/not-a-current-evidence-id")[0], 404)
        _, report = self.request("/api/report")
        evidence_id = report["daily"]["slices"][0]["evidence_id"]
        self.assertEqual(self.request(f"/api/evidence/{evidence_id}?page=0")[0], 400)

    def test_publication_specific_evidence_and_short_filter_over_http(self):
        _, before = self.request("/api/report")
        row = next(record for record in before["daily"]["slices"] if record["flagged"])
        evidence_id = row["evidence_id"]
        publication_id = before["publication"]["id"]
        query = f"/api/evidence/{evidence_id}?publication_id={publication_id}&signals_only=true&page_size=2&page=2"
        status, filtered = self.request(query)
        self.assertEqual(status, 200)
        self.assertEqual((filtered["transaction_count"], filtered["population_count"]), (6, 30))
        self.assertEqual(len(filtered["transactions"]), 2)
        self.assertTrue(filtered["signals_only"])
        self.assertTrue(filtered["is_current"])
        self.assertEqual(filtered["publication_id"], publication_id)
        status, changed = self.request("/api/settings", {"daily_min_rate": .15})
        self.assertEqual(status, 200)
        try:
            status, archived = self.request(query)
            self.assertEqual(status, 200)
            self.assertFalse(archived["is_current"])
            self.assertEqual(archived["publication_id"], publication_id)
            self.assertEqual(archived["current_publication_id"], changed["publication"]["id"])
            self.assertEqual(archived["rule_version"], before["settings"]["version"])
            self.assertTrue(all(record["sources"][0]["raw_cells"] for record in archived["transactions"]))
            status, unavailable = self.request(f"/api/evidence/{evidence_id}")
            self.assertEqual(status, 404)
            self.assertEqual(unavailable["code"], "evidence_unavailable")
            self.assertTrue(unavailable["reload_report"])
            self.assertEqual(self.request("/api/reviews", {"evidence_id": evidence_id, "state": "Needs review", "reviewer": "Reviewer", "note": "Old evidence cannot become a new-source review."})[0], 400)
        finally:
            self.request("/api/settings", {"daily_min_rate": before["settings"]["daily_min_rate"]})

    def test_review_rejects_publication_race_with_unchanged_evidence_id(self):
        _, before = self.request("/api/report")
        row = next(record for record in before["daily"]["slices"] if record["flagged"])
        old_publication = before["publication"]["id"]
        source = Path(self.temporary.name) / "race-input"
        shutil.copytree(Path(__file__).resolve().parents[1] / "fixtures", source)
        manifest_path = source / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["annotations"] = [{"annotation_id": "context-update", "note": "Updated site context."}]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.app.state.store.import_folder(source)
        _, after = self.request("/api/report")
        current_row = next(record for record in after["daily"]["slices"] if record["agent_id"] == row["agent_id"] and record["call_type"] == row["call_type"])
        self.assertEqual(current_row["evidence_id"], row["evidence_id"])
        self.assertNotEqual(after["publication"]["id"], old_publication)
        reviews_before = self.app.state.store.reviews()
        body = {"evidence_id": row["evidence_id"], "publication_id": old_publication,
                "state": "Needs review", "reviewer": "Reviewer", "note": "Previous publication decision."}
        status, rejected = self.request("/api/reviews", body)
        self.assertEqual(status, 400)
        self.assertIn("source report changed", rejected["detail"])
        self.assertEqual(self.app.state.store.reviews(), reviews_before)
        body["publication_id"] = after["publication"]["id"]
        status, saved = self.request("/api/reviews", body)
        self.assertEqual(status, 200)
        self.assertEqual(saved["publication_id"], after["publication"]["id"])

    def test_external_origin_cannot_change_review(self):
        status, _ = self.request("/api/reviews", {}, {"Origin": "https://example.com"})
        self.assertEqual(status, 403)

    def test_wrong_settings_do_not_replace_publication(self):
        _, before = self.request("/api/report")
        status, error = self.request("/api/settings", {"baseline_days": 0})
        self.assertEqual(status, 400)
        self.assertIn("positive integer", error["detail"])
        _, after = self.request("/api/report")
        self.assertEqual(before["publication"]["id"], after["publication"]["id"])

    def test_import_bad_relative_paths_are_actionable(self):
        boundary = "callreviewtest"
        data = (f'--{boundary}\r\nContent-Disposition: form-data; name="paths"\r\n\r\n[7]\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="admin.xlsx"\r\nContent-Type: application/octet-stream\r\n\r\ninvalid\r\n--{boundary}--\r\n').encode()
        request = Request(self.base + "/api/import", data=data, headers={"Content-Type": "multipart/form-data; boundary=" + boundary, "X-Call-Review": "1"})
        with self.assertRaises(HTTPError) as caught:
            urlopen(request, timeout=5)
        self.assertEqual(caught.exception.code, 400)
        self.assertIn("paths", json.load(caught.exception)["detail"])
        caught.exception.close()

    def test_prebuilt_interface_is_served_locally(self):
        if not (Path(__file__).resolve().parents[1] / "frontend" / "dist" / "index.html").exists():
            self.skipTest("Frontend is still being built")
        with urlopen(self.base + "/", timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b"<html", response.read().lower())

    def test_valid_folder_upload_preserves_manifest_paths_and_report(self):
        fixture_root = Path(__file__).resolve().parents[1] / "fixtures"
        sources = sorted(path for path in fixture_root.rglob("*") if path.is_file() and (path.suffix == ".xlsx" or path.name == "manifest.json"))
        names = [path.relative_to(fixture_root).as_posix() for path in sources]
        boundary = "callreviewvalidfolder"
        parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="paths"\r\n\r\n{json.dumps(names)}\r\n'.encode()]
        for path in sources:
            parts.extend([f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{path.name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode(), path.read_bytes(), b"\r\n"])
        parts.append(f"--{boundary}--\r\n".encode())
        request = Request(self.base + "/api/import", data=b"".join(parts), headers={"Content-Type": "multipart/form-data; boundary=" + boundary, "X-Call-Review": "1"})
        with urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 200)
        for _ in range(100):
            _, status = self.request("/api/status")
            if status["job"]["state"] != "running":
                break
            time.sleep(.1)
        self.assertEqual(status["job"]["state"], "done")
        _, report = self.request("/api/report")
        self.assertEqual(report["overview"]["daily_patterns"], 1)
        self.assertTrue(report["coverage"]["report_date_complete"])


if __name__ == "__main__":
    unittest.main()

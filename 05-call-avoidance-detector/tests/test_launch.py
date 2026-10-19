"""Read-only diagnostics, instance identity, and ordinary launcher shutdown."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, HTTPServer

import launch


class LaunchBehaviorTests(unittest.TestCase):
    def setUp(self):
        directory = launch.PROJECT / "runtime"
        directory.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="launch-tests-", dir=directory)
        self.project = Path(self.temp.name).resolve() / "App ! & (Á)"
        self.data = self.project / "runtime" / "data"
        self.data.mkdir(parents=True)
        browser = self.project / "frontend" / "dist"
        browser.mkdir(parents=True)
        (browser / "index.html").write_text("<html></html>", encoding="utf-8")
        self.report = {
            "report_date": "2026-10-06", "synthetic": True,
            "coverage": {"status": "Complete", "report_date_complete": True, "baseline_complete": True,
                         "complete_days": ["2026-10-06"], "expected_days": ["2026-10-06"], "missing_baseline_days": []},
            "latest_source_time": "2026-10-06T16:00:00+00:00",
        }
        self.publication = {"published_at": "2026-10-07T03:00:00+00:00", "report": self.report}

    def tearDown(self):
        self.temp.cleanup()

    def save_publication(self):
        path = self.data / "publications" / "saved.json"
        path.parent.mkdir()
        path.write_text(json.dumps(self.publication), encoding="utf-8")
        (self.data / "current.json").write_text(json.dumps({"publication": "publications/saved.json"}), encoding="utf-8")

    def file_contents(self):
        return {str(path.relative_to(self.project)): path.read_bytes() for path in self.project.rglob("*") if path.is_file()}

    def test_check_reads_coverage_and_local_freshness_without_mutating_data(self):
        self.save_publication()
        before = self.file_contents()
        output = io.StringIO()
        with patch.object(launch, "PROJECT", self.project), patch.object(launch, "runtime_problems", return_value=[]), \
                patch.object(launch, "occupied", return_value=False), patch.dict(os.environ, {"CA_DATA_DIR": str(self.data), "CA_PORT": "8505"}), \
                redirect_stdout(output):
            self.assertEqual(launch.check(), 0)
        self.assertIn("Source coverage: Complete", output.getvalue())
        self.assertIn("Baseline: Complete", output.getvalue())
        self.assertIn("2026-10-06 21:00:00-06:00", output.getvalue())
        self.assertEqual(self.file_contents(), before)

    def test_check_uses_verified_saved_alternative_port(self):
        (self.data / "instance.json").write_text(json.dumps({"port": 8508, "instance_id": "saved-instance"}), encoding="utf-8")
        health = {"product": launch.PRODUCT, "instance_id": "saved-instance", "project_directory": str(self.project),
                  "data_directory": str(self.data), "publication": {"published_at": self.publication["published_at"]},
                  "job": {"message": "Report ready"}}
        output = io.StringIO()
        before = self.file_contents()
        with patch.object(launch, "PROJECT", self.project), patch.object(launch, "runtime_problems", return_value=[]), \
                patch.object(launch, "health", return_value=health) as probe, \
                patch.object(launch, "urlopen", return_value=io.StringIO(json.dumps(self.report))), \
                patch.dict(os.environ, {"CA_DATA_DIR": str(self.data), "CA_PORT": "8505"}), redirect_stdout(output):
            self.assertEqual(launch.check(), 0)
        self.assertIn("Running app: http://127.0.0.1:8508", output.getvalue())
        probe.assert_called_once_with(8508)
        self.assertEqual(self.file_contents(), before)

    def test_other_project_or_changed_identity_cannot_be_reused(self):
        (self.data / "instance.json").write_text(json.dumps({"port": 8508, "instance_id": "saved"}), encoding="utf-8")
        for instance_id, project in (("different", self.project), ("saved", self.project.parent / "Other app")):
            with self.subTest(instance=instance_id, project=str(project)), patch.object(launch, "PROJECT", self.project), \
                    patch.object(launch, "health", return_value={"product": launch.PRODUCT, "instance_id": instance_id,
                                "data_directory": str(self.data), "project_directory": str(project)}):
                self.assertIsNone(launch.matching_instance(self.data))

    def test_saved_pointer_cannot_read_outside_its_data_folder(self):
        outside = self.project / "private.json"
        outside.write_text("private content", encoding="utf-8")
        (self.data / "current.json").write_text(json.dumps({"publication": "../../private.json"}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "outside"):
            launch.source_summary(self.data, None)

    def test_ctrl_c_is_successful_without_a_traceback(self):
        output = io.StringIO()
        with patch.object(launch.sys, "argv", ["launch.py", "run", "--no-browser"]), \
                patch.object(launch, "run", side_effect=KeyboardInterrupt), patch.dict(os.environ, {"CA_PORT": "8505"}), redirect_stdout(output):
            self.assertEqual(launch.main(), 0)
        self.assertIn("App stopped", output.getvalue())
        self.assertNotIn("needs attention", output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())

    def test_launch_failure_records_a_short_runtime_error(self):
        output = io.StringIO()
        with patch.object(launch, "PROJECT", self.project), patch.object(launch.sys, "argv", ["launch.py", "run", "--no-browser"]), \
                patch.object(launch, "run", side_effect=RuntimeError("No free local port found.")), \
                patch.dict(os.environ, {"CA_PORT": "8505"}), redirect_stdout(output):
            self.assertEqual(launch.main(), 1)
        events = [json.loads(line) for line in (self.project / "runtime" / "run.log").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(events[0]["event"], "error")
        self.assertEqual(events[0]["error_type"], "RuntimeError")
        self.assertEqual(events[0]["message"], "No free local port found.")

    def test_incomplete_saved_coverage_requires_the_missing_exports(self):
        self.report["coverage"].update({"baseline_complete": False, "missing_baseline_days": ["2026-10-01"]})
        self.save_publication()
        output = io.StringIO()
        with patch.object(launch, "PROJECT", self.project), patch.object(launch, "runtime_problems", return_value=[]), \
                patch.object(launch, "occupied", return_value=False), patch.dict(os.environ, {"CA_DATA_DIR": str(self.data), "CA_PORT": "8505"}), \
                redirect_stdout(output):
            self.assertEqual(launch.check(), 1)
        self.assertIn("Insufficient history", output.getvalue())
        self.assertIn("Missing baseline days: 2026-10-01", output.getvalue())

    def test_local_health_ignores_network_proxies_and_does_not_follow_redirects(self):
        contacts = []

        class OtherProgram(BaseHTTPRequestHandler):
            def do_GET(self):
                contacts.append(self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args):
                pass

        destination = HTTPServer(("127.0.0.1", 0), OtherProgram)

        class LocalProgram(BaseHTTPRequestHandler):
            redirect = False

            def do_GET(self):
                if self.redirect:
                    self.send_response(302)
                    self.send_header("Location", f"http://127.0.0.1:{destination.server_port}/untrusted")
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(json.dumps({"product": launch.PRODUCT}).encode())

            def log_message(self, *args):
                pass

        local = HTTPServer(("127.0.0.1", 0), LocalProgram)
        threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (destination, local)]
        for thread in threads:
            thread.start()
        try:
            with patch.dict(os.environ, {"http_proxy": f"http://127.0.0.1:{destination.server_port}", "no_proxy": ""}):
                self.assertEqual(launch.health(local.server_port)["product"], launch.PRODUCT)
                LocalProgram.redirect = True
                self.assertIsNone(launch.health(local.server_port))
            self.assertEqual(contacts, [])
        finally:
            for server in (destination, local):
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join(5)


if __name__ == "__main__":
    unittest.main()

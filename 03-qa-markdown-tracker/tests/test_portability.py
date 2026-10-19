"""Exercise deployment boundaries without private attachments or API calls."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from qa_shared.core import DataError, selected_calls
from qa_shared.demo import ensure_sample
from qa_shared.paths import source_paths, store_path


class PortabilityTests(unittest.TestCase):
    def test_report_timezone_is_available(self):
        self.assertEqual(ZoneInfo('America/Mexico_City').key, 'America/Mexico_City')

    def test_writable_data_and_database_can_live_outside_checkout(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {
            'QA_DATA_DIR': temp, 'QA_INPUT_FOLDER': '', 'QA_SAMPLE_FILE': '', 'QA_STORE_PATH': ''
        }):
            folder, _ = source_paths(demo=True)
            self.assertEqual(folder, Path(temp).resolve() / 'demo-data')
            self.assertEqual(store_path(), Path(temp).resolve() / '02-modern-ai/runtime/qa.db')

    def test_explicit_missing_source_is_an_error(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(DataError):source_paths(Path(temp)/'missing')
            with self.assertRaises(DataError):source_paths(temp, Path(temp)/'missing.ods')

    def test_anonymous_sample_has_no_implied_audit_results(self):
        with tempfile.TemporaryDirectory() as temp:
            calls = selected_calls(ensure_sample(Path(temp)/'Synthetic_sample.ods'))
            self.assertEqual(len(calls), 1512)
            self.assertEqual(len({c['agent_id'] for c in calls}), 42)
            self.assertTrue(all(c['agent'].startswith('Example person ') for c in calls))
            self.assertTrue(all(c['transaction_id'].startswith('EXAMPLE-CALL-') for c in calls))

    def test_launch_rejects_invalid_port(self):
        result = subprocess.run([sys.executable, str(ROOT/'launch.py'), 'ai', '--port', '99999'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('65535', result.stderr)

    def test_both_solutions_run_from_moved_folder_without_attachment(self):
        with tempfile.TemporaryDirectory(prefix='qa portable ') as temp:
            moved = Path(temp)/'Another folder with spaces'
            shutil.copytree(ROOT, moved, ignore=shutil.ignore_patterns(
                '.venv', '__pycache__', 'demo-data', 'private-data', 'runtime', 'output',
                'node_modules', '*.ods', '*.xlsx', '*.pdf', '*.db*', '.env', '.env.*'))
            self.assertFalse(list(moved.glob('*.ods')))
            env = dict(os.environ, QA_DATA_DIR=str(Path(temp)/'Private data'), QA_INPUT_FOLDER='',
                       QA_SAMPLE_FILE='', QA_STORE_PATH='', OPENAI_API_KEY='')
            output = Path(temp)/'Private data'/'report.xlsx'
            result = subprocess.run([sys.executable, str(moved/'launch.py'), 'limited', '--demo',
                '--output', str(output)], cwd=temp, env=env, capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(output.with_suffix('.json').read_text(encoding='utf-8'))
            self.assertEqual(report['audit_count'], 714)
            self.assertEqual(len(report['sample']), 1512)
            self.assertTrue(all(a['agent'].startswith('Example person ') for a in report['agents']))
            # A separate process prevents imports from this checkout hiding path bugs.
            script = ("from streamlit.testing.v1 import AppTest; "
                      "a=AppTest.from_file('02-modern-ai/app.py',default_timeout=40).run(); "
                      "assert not a.exception, a.exception; assert a.metric[1].value=='714'; "
                      "a.radio[0].set_value('Pivot Tables').run(); assert not a.exception")
            result = subprocess.run([sys.executable, '-c', script], cwd=moved, env=env,
                                    capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':unittest.main()

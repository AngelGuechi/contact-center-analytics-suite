"""Windows entry points must keep working after a GitHub download or relocation."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'win32', 'Windows batch entry points')
class WindowsLauncherTests(unittest.TestCase):
    def call(self, folder, mode, **overrides):
        env = {**os.environ, 'QA_PYTHON':sys.executable, 'QA_NO_UI':'1', **overrides}
        return subprocess.run(['cmd.exe', '/d', '/c', 'run.bat', mode], cwd=folder,
                              env=env, capture_output=True, text=True, timeout=30)

    def test_check_from_relocated_folder_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix='QA batch review ') as temp:
            moved = Path(temp)/'Another folder with spaces'
            moved.mkdir()
            for name in ['run.bat', 'windows-portable.ps1', 'launch.py']:
                shutil.copy2(ROOT/name, moved/name)
            result = self.call(moved, 'check')
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn('Both solutions have their required packages', result.stdout)

    def test_invalid_choice_has_clear_message_and_failure_status(self):
        result = self.call(ROOT, 'unknown-choice')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Choose 1, 2, 3, 4 or 0', result.stdout)

    def test_missing_environment_points_to_installer(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self.call(ROOT, 'check', QA_PYTHON=str(Path(temp)/'missing.exe'))
            self.assertEqual(result.returncode, 1)
            self.assertIn('portable.bat first', result.stdout)


if __name__ == '__main__':unittest.main()

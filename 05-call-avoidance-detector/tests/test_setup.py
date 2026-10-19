"""Installation preserves reviews, handles relocation, and respects writer locks."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import venv

import setup as installer


class CollectingLog:
    def __init__(self):
        self.lines = []

    def write(self, message):
        self.lines.append(message)


class SetupSafetyTests(unittest.TestCase):
    def setUp(self):
        directory = installer.PROJECT / "runtime"
        directory.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="setup-tests-", dir=directory)
        self.root = Path(self.temp.name).resolve() / "App with spaces ! & (accents Á)"
        self.root.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def release_files(self):
        (self.root / "requirements.txt").write_text("fastapi==0.142.2\n", encoding="utf-8")
        (self.root / "launch.py").write_text("", encoding="utf-8")
        browser = self.root / "frontend" / "dist"
        browser.mkdir(parents=True)
        (browser / "index.html").write_text("<html></html>", encoding="utf-8")

    def known_environment(self):
        environment = self.root / ".venv"
        environment.mkdir()
        (environment / "pyvenv.cfg").write_text("home = C:\\Python312\n", encoding="utf-8")
        python = installer.environment_python(environment)
        python.parent.mkdir(parents=True, exist_ok=True)
        python.touch()
        installer.write_environment_marker(self.root, {"status": "ready"})
        return environment

    def test_repair_deletes_only_environment_and_preserves_reviews(self):
        environment = self.known_environment()
        review = self.root / "runtime" / "data" / "reviews.jsonl"
        review.parent.mkdir(parents=True)
        review.write_text('{"note":"keep this review"}\n', encoding="utf-8")
        installer.remove_environment(self.root)
        self.assertFalse(environment.exists())
        self.assertEqual(review.read_text(encoding="utf-8"), '{"note":"keep this review"}\n')
        self.assertTrue(self.root.exists())

    def test_arbitrary_folder_named_venv_is_preserved(self):
        folder = self.root / ".venv"
        folder.mkdir()
        document = folder / "my-file.txt"
        document.write_text("do not delete", encoding="utf-8")
        with self.assertRaisesRegex(installer.SetupError, "preserve"):
            installer.remove_environment(self.root)
        self.assertEqual(document.read_text(encoding="utf-8"), "do not delete")

    def test_link_to_another_folder_is_never_recursively_removed(self):
        outside = Path(self.temp.name) / "private-reviews"
        outside.mkdir()
        document = outside / "saved.txt"
        document.write_text("saved review", encoding="utf-8")
        try:
            os.symlink(outside, self.root / ".venv", target_is_directory=True)
        except OSError:
            self.skipTest("This Windows account cannot create directory symlinks.")
        with self.assertRaisesRegex(installer.SetupError, "link"):
            installer.remove_environment(self.root)
        self.assertEqual(document.read_text(encoding="utf-8"), "saved review")

    def test_copied_environment_is_reported_before_interpreter_execution(self):
        environment = self.known_environment()
        marker = environment / installer.ENVIRONMENT_MARKER
        state = json.loads(marker.read_text(encoding="utf-8"))
        state["project_root"] = str(Path(self.temp.name) / "old-computer-location")
        marker.write_text(json.dumps(state), encoding="utf-8")
        with patch.object(installer, "probe_environment") as probe:
            problem = installer.environment_problem(self.root, (3, 12))
        self.assertIn("copied", problem)
        probe.assert_not_called()

    def test_damaged_environment_marker_gives_an_actionable_repair_reason(self):
        environment = self.known_environment()
        (environment / installer.ENVIRONMENT_MARKER).write_text("[]", encoding="utf-8")
        with patch.object(installer, "probe_environment") as probe:
            self.assertIn("damaged", installer.environment_problem(self.root, (3, 12)))
        probe.assert_not_called()
        installer.remove_environment(self.root)
        self.assertFalse(environment.exists())

    def test_installer_respects_an_existing_app_writer_lock(self):
        self.release_files()
        environment = self.known_environment()
        review = self.root / "runtime" / "data" / "reviews.jsonl"
        review.parent.mkdir(parents=True)
        review.write_text("keep review\n", encoding="utf-8")
        marker_before = (environment / installer.ENVIRONMENT_MARKER).read_bytes()
        arguments = argparse.Namespace(offline=False, wheel_dir=None, repair=True)
        with patch.dict(os.environ, {"CA_DATA_DIR": str(review.parent)}):
            with installer.RuntimeLock(review.parent / "runtime.lock"):
                with patch.object(installer, "run_logged") as install_packages:
                    with self.assertRaises(installer.BusyError):
                        installer.install(self.root, arguments, CollectingLog())
        install_packages.assert_not_called()
        self.assertEqual((environment / installer.ENVIRONMENT_MARKER).read_bytes(), marker_before)
        self.assertEqual(review.read_text(encoding="utf-8"), "keep review\n")

    def test_lock_file_can_be_reused_after_a_process_releases_it(self):
        path = self.root / "runtime" / "data" / "runtime.lock"
        with installer.RuntimeLock(path):
            with self.assertRaises(installer.BusyError):
                with installer.RuntimeLock(path):
                    self.fail("A second writer acquired the lock")
        self.assertTrue(path.exists())
        with installer.RuntimeLock(path):
            pass

    def test_data_inside_environment_is_rejected_without_deleting_it(self):
        self.release_files()
        environment = self.known_environment()
        review = environment / "data" / "reviews.jsonl"
        review.parent.mkdir()
        review.write_text("keep review\n", encoding="utf-8")
        arguments = argparse.Namespace(offline=False, wheel_dir=None, repair=True)
        with patch.dict(os.environ, {"CA_DATA_DIR": str(review.parent)}):
            with self.assertRaisesRegex(installer.SetupError, "inside .venv"):
                installer.install(self.root, arguments, CollectingLog())
        self.assertEqual(review.read_text(encoding="utf-8"), "keep review\n")

    def test_offline_setup_rejects_missing_bundle_before_environment_changes(self):
        self.release_files()
        arguments = argparse.Namespace(offline=True, wheel_dir=None, repair=False)
        with self.assertRaisesRegex(installer.SetupError, "wheel-dir"):
            installer.install(self.root, arguments, CollectingLog())
        self.assertFalse((self.root / ".venv").exists())

    def test_offline_command_uses_project_interpreter_and_no_package_index(self):
        bundle = Path(self.temp.name) / "Python 3.12 Windows wheels"
        bundle.mkdir()
        python = installer.environment_python(self.root / ".venv")
        command = installer.pip_install_command(python, self.root / "requirements.txt", True, bundle)
        self.assertEqual(command[0], str(python))
        self.assertIn("--no-index", command)
        self.assertEqual(command[command.index("--find-links") + 1], str(bundle))
        self.assertIn("--only-binary=:all:", command)

    @unittest.skipUnless(os.name == "nt", "Windows batch shortcuts")
    def test_shortcuts_run_from_another_directory_with_spaces_and_special_characters(self):
        for name in ("setup.py", "INSTALL.bat", "RUN.bat", "CHECK.bat"):
            shutil.copy2(installer.PROJECT / name, self.root / name)
        self.root.joinpath("launch.py").write_text(
            "import json, os, sys\nprint(json.dumps({'arguments': sys.argv[1:], 'cwd': os.getcwd()}))\n",
            encoding="utf-8",
        )
        venv.EnvBuilder(with_pip=False, symlinks=False).create(self.root / ".venv")
        child_env = dict(os.environ)
        child_env["CA_PYTHON"] = str(Path(sys._base_executable).resolve())
        for name, arguments, expected in (
            ("INSTALL.bat", "/nopause --help", None),
            ("RUN.bat", "/nopause --no-browser", ["run", "/nopause", "--no-browser"]),
            ("CHECK.bat", "/nopause", ["check", "/nopause"]),
        ):
            with self.subTest(shortcut=name):
                command = f'"{os.environ.get("COMSPEC", "cmd.exe")}" /d /s /c ""{self.root / name}" {arguments}"'
                result = subprocess.run(
                    command,
                    cwd=Path(self.temp.name),
                    env=child_env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                if expected is None:
                    self.assertIn("--offline", result.stdout)
                else:
                    output = json.loads(result.stdout)
                    self.assertEqual(output["arguments"], expected)
                    self.assertEqual(Path(output["cwd"]).resolve(), self.root)

    @unittest.skipUnless(os.name == "nt", "Windows batch shortcuts")
    def test_bootstrap_override_is_a_path_and_cannot_execute_shell_arguments(self):
        for name in ("setup.py", "INSTALL.bat"):
            shutil.copy2(installer.PROJECT / name, self.root / name)
        child_env = dict(os.environ)
        child_env["CA_PYTHON"] = 'C:\\nonexistent\\python.exe" & echo SHELL_INJECTION & "'
        command = f'"{os.environ.get("COMSPEC", "cmd.exe")}" /d /s /c ""{self.root / "INSTALL.bat"}" /nopause"'
        result = subprocess.run(
            command,
            cwd=Path(self.temp.name),
            env=child_env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("CA_PYTHON does not point", result.stdout)
        self.assertNotIn("SHELL_INJECTION", result.stdout + result.stderr)

    @unittest.skipUnless(os.name == "nt", "Windows launcher selection")
    def test_install_uses_a_launcher_with_only_the_313_selection_available(self):
        powershell = shutil.which("powershell.exe")
        if powershell is None:
            self.skipTest("Windows' bundled compiler is unavailable for the launcher fixture.")
        for name in ("setup.py", "INSTALL.bat"):
            shutil.copy2(installer.PROJECT / name, self.root / name)
        calls = self.root / "fake-launcher-calls.txt"
        source = self.root / "FakeLauncher.cs"
        source.write_text(
            "using System; using System.IO; using System.Diagnostics;\n"
            "public class FakeLauncher { public static int Main(string[] args) {\n"
            f"File.AppendAllText({json.dumps(str(calls))}, args[0] + \"\\n\");\n"
            "if (args[0] != \"-3.13\") return 101;\n"
            "string needle = \" -3.13\";\n"
            "int offset = Environment.CommandLine.IndexOf(needle, StringComparison.Ordinal);\n"
            "if (offset < 0) return 102;\n"
            "string forwarded = Environment.CommandLine.Substring(offset + needle.Length).TrimStart();\n"
            f"var info = new ProcessStartInfo({json.dumps(str(Path(sys._base_executable).resolve()))}, forwarded);\n"
            "info.UseShellExecute = false; info.CreateNoWindow = true;\n"
            "info.RedirectStandardOutput = true; info.RedirectStandardError = true;\n"
            "using (var process = Process.Start(info)) {\n"
            "string output = process.StandardOutput.ReadToEnd(); string error = process.StandardError.ReadToEnd();\n"
            "process.WaitForExit(); Console.Out.Write(output); Console.Error.Write(error); return process.ExitCode; }\n"
            "} }\n",
            encoding="utf-8",
        )
        executable = self.root / "py.exe"
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        compiler_env = {**os.environ, "TEMP": str(self.root), "TMP": str(self.root)}
        compilation = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command",
             f"Add-Type -Path {quote(source)} -OutputAssembly {quote(executable)} -OutputType ConsoleApplication"],
            capture_output=True, text=True, errors="replace", timeout=45, check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
            env=compiler_env,
        )
        if compilation.returncode or not executable.is_file():
            self.skipTest("The temporary launcher fixture could not be compiled: " + compilation.stderr)
        child_env = dict(os.environ)
        child_env.pop("CA_PYTHON", None)
        command = f'"{os.environ.get("COMSPEC", "cmd.exe")}" /d /s /c ""{self.root / "INSTALL.bat"}" /nopause --help"'
        result = subprocess.run(command, cwd=Path(self.temp.name), env=child_env,
                                capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("--offline", result.stdout)
        # This simulates launcher availability; it does not claim that the
        # computer has a real Python 3.13 runtime installed.
        self.assertEqual(calls.read_text(encoding="utf-8").splitlines(), ["-3.12", "-3.13", "-3.13"])


if __name__ == "__main__":
    unittest.main()

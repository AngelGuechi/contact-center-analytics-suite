"""Install this source release without changing the computer's Python installation.

The Windows shortcut selects a supported base interpreter; this script creates
the project's own environment and always installs through that environment.
Only the Python standard library is required to execute this file.
"""

from __future__ import annotations

import argparse
from contextlib import AbstractContextManager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
import venv


PROJECT = Path(__file__).resolve().parent
MIN_PYTHON = (3, 12)
MAX_PYTHON = (3, 15)
ENVIRONMENT_MARKER = "ca_environment.json"
INSTALLER_ID = "call-avoidance-detector"


class SetupError(Exception):
    """A setup failure with an explanation suitable for the user."""

    exit_code = 1


class BusyError(SetupError):
    exit_code = 2


class InstallerLog(AbstractContextManager):
    def __init__(self, path: Path):
        self.path = path
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a", encoding="utf-8")
        self.write("\n" + "=" * 64)
        self.write("Installation: " + datetime.now(timezone.utc).isoformat())
        return self

    def write(self, message: str):
        print(message, flush=True)
        if self.file is not None:
            self.file.write(message + "\n")
            self.file.flush()

    def __exit__(self, *exc):
        if self.file is not None:
            self.file.close()


class RuntimeLock(AbstractContextManager):
    """Hold byte zero of the same persistent lock file used by launch.py.

    The operating system releases the lock if a process crashes. The file is
    deliberately retained; its existence is not evidence of a running app.
    """

    def __init__(self, path: Path):
        self.path = path
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            self.file.write(b"\0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            self.file = None
            raise BusyError(
                "The app or another installer is using this data folder. "
                "Stop the app with Ctrl+C, then run INSTALL.bat again. "
                "No environment or review data was changed."
            ) from exc
        return self

    def __exit__(self, *exc):
        if self.file is None:
            return
        try:
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        finally:
            self.file.close()
            self.file = None


def data_directory(project: Path) -> Path:
    configured = os.environ.get("CA_DATA_DIR")
    path = Path(configured).expanduser() if configured else project / "runtime" / "data"
    return (project / path if not path.is_absolute() else path).resolve()


def environment_python(environment: Path) -> Path:
    return environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def validate_environment_target(project: Path) -> Path:
    """Allow recursive removal only of this project's real .venv directory."""
    root = project.resolve()
    target = root / ".venv"
    resolved = target.resolve(strict=False)
    junction = getattr(target, "is_junction", lambda: False)()
    if target.is_symlink() or junction or resolved != target or resolved.parent != root:
        raise SetupError(
            "The .venv path is a link or points outside the app folder. "
            "Setup will not remove it. Move the link aside and run INSTALL.bat again."
        )
    if target.exists() and not target.is_dir():
        raise SetupError(".venv is a file. Move it aside and run INSTALL.bat again.")
    return target


def remove_environment(project: Path):
    target = validate_environment_target(project)
    if not target.exists():
        return
    marker = target / ENVIRONMENT_MARKER
    recognized = (target / "pyvenv.cfg").is_file()
    if marker.is_file():
        try:
            state = json.loads(marker.read_text(encoding="utf-8"))
            recognized = recognized or (
                isinstance(state, dict) and state.get("installer") == INSTALLER_ID
            )
        except (OSError, ValueError, TypeError):
            pass
    if not recognized:
        raise SetupError(
            "The .venv folder does not look like a Python environment made for this app. "
            "Setup will preserve it. Rename it, then run INSTALL.bat again."
        )
    # Verify the final absolute target immediately before recursive deletion.
    checked = validate_environment_target(project)
    if checked != target:
        raise SetupError("The .venv path changed during setup; installation stopped.")
    shutil.rmtree(checked)


def read_pins(requirements: Path) -> dict[str, str]:
    if not requirements.is_file():
        raise SetupError("requirements.txt is missing. Extract or copy the complete app folder.")
    pins = {}
    for number, line in enumerate(requirements.read_text(encoding="utf-8-sig").splitlines(), 1):
        value = line.partition("#")[0].strip()
        if not value:
            continue
        match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9_.-]*)==([^\s;]+)", value)
        if not match:
            raise SetupError(f"requirements.txt line {number} is not an exact package pin.")
        name = re.sub(r"[-_.]+", "-", match.group(1)).lower()
        if name in pins and pins[name] != match.group(2):
            raise SetupError(f"requirements.txt contains conflicting versions for {name}.")
        pins[name] = match.group(2)
    if not pins:
        raise SetupError("requirements.txt contains no pinned packages.")
    return pins


ENVIRONMENT_PROBE = """
import json, os, struct, sys
import pip
print(json.dumps({
    'version': list(sys.version_info[:3]),
    'prefix': sys.prefix,
    'base_prefix': sys.base_prefix,
    'executable': sys.executable,
    'bits': struct.calcsize('P') * 8,
}))
"""


def probe_environment(python: Path, project: Path) -> dict:
    result = subprocess.run(
        [str(python), "-I", "-c", ENVIRONMENT_PROBE],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode:
        raise SetupError("The existing environment's Python or pip does not run correctly.")
    try:
        result_info = json.loads(result.stdout)
        if not isinstance(result_info, dict):
            raise ValueError("Expected a Python information object")
        version = result_info.get("version")
        if not isinstance(version, list) or len(version) != 3 or any(type(part) is not int for part in version):
            raise ValueError("Invalid Python version")
        for key in ("prefix", "base_prefix", "executable"):
            if not isinstance(result_info.get(key), str) or not result_info[key]:
                raise ValueError("Missing interpreter path")
        return result_info
    except (ValueError, TypeError) as exc:
        raise SetupError("The existing environment did not return a valid Python check.") from exc


def environment_problem(project: Path, selected_version: tuple[int, int]) -> str | None:
    environment = validate_environment_target(project)
    if not environment.exists():
        return "No local Python environment is installed yet."
    python = environment_python(environment)
    if not python.is_file() or not (environment / "pyvenv.cfg").is_file():
        return "The local environment is incomplete."
    marker = environment / ENVIRONMENT_MARKER
    if marker.exists():
        try:
            state = json.loads(marker.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                return "The local environment marker is damaged."
            if state.get("installer") != INSTALLER_ID:
                return "The environment marker belongs to another app."
            if Path(state.get("project_root", "")).resolve() != project.resolve():
                return "This environment was copied or the app folder was moved."
        except (OSError, ValueError, TypeError):
            return "The local environment marker is damaged."
    try:
        info = probe_environment(python, project)
    except (OSError, subprocess.SubprocessError, SetupError):
        return "The local environment's Python or pip is broken."
    version = tuple(info.get("version", [])[:2])
    if not MIN_PYTHON <= version < MAX_PYTHON:
        return "The installed environment uses an unsupported Python version."
    if version != selected_version:
        return "The installed environment uses a different Python version from this setup."
    prefix = Path(info.get("prefix", "")).resolve()
    base = Path(info.get("base_prefix", "")).resolve()
    if prefix != environment or prefix == base:
        return "The local interpreter does not belong to this app's isolated environment."
    if Path(info.get("executable", "")).resolve() != python.resolve():
        return "The local interpreter points to another environment."
    return None


def pip_install_command(python: Path, requirements: Path, offline: bool, wheel_dir: Path | None):
    command = [
        str(python),
        "-I",
        "-m",
        "pip",
        "--disable-pip-version-check",
        "--no-input",
        "install",
        "--only-binary=:all:",
        "--timeout",
        "30",
        "--retries",
        "2",
        "--requirement",
        str(requirements),
    ]
    if offline:
        if wheel_dir is None:
            raise SetupError("Offline setup needs --wheel-dir pointing to a compatible wheel bundle.")
        command.append("--no-index")
    if wheel_dir is not None:
        if not wheel_dir.is_dir():
            raise SetupError("The wheel bundle folder does not exist: " + str(wheel_dir))
        command.extend(["--find-links", str(wheel_dir)])
    return command


def run_logged(command: list[str], project: Path, log: InstallerLog):
    # Ignore pip targets/index/config inherited from the shell so installation
    # stays inside .venv and --offline cannot inherit a remote package source.
    child_env = {key: value for key, value in os.environ.items() if not key.upper().startswith("PIP_")}
    child_env["PIP_CONFIG_FILE"] = os.devnull
    process = subprocess.Popen(
        command,
        cwd=project,
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        bufsize=1,
    )
    try:
        assert process.stdout is not None
        for line in process.stdout:
            log.write(line.rstrip("\r\n"))
        code = process.wait()
    except BaseException:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        raise
    finally:
        if process.stdout is not None:
            process.stdout.close()
    if code:
        raise SetupError(
            f"The package command failed (exit {code}). "
            "Check the installation log and your internet connection or offline wheel bundle, "
            "then run INSTALL.bat again."
        )


DEPENDENCY_PROBE = """
import importlib, importlib.metadata, json, sys
from zoneinfo import ZoneInfo
expected = json.loads(sys.argv[1])
problems = []
versions = {}
for name, wanted in expected.items():
    try:
        found = importlib.metadata.version(name)
        versions[name] = found
        if found != wanted:
            problems.append(f'{name}: found {found}; expected {wanted}')
    except importlib.metadata.PackageNotFoundError:
        problems.append(f'{name}: missing')
for module in ('fastapi', 'uvicorn', 'openpyxl'):
    try:
        importlib.import_module(module)
    except Exception as exc:
        problems.append(f'{module}: cannot import ({exc})')
try:
    ZoneInfo('America/Mexico_City')
except Exception as exc:
    problems.append(f'America/Mexico_City timezone is unavailable ({exc})')
print(json.dumps({'versions': versions, 'problems': problems}))
raise SystemExit(1 if problems else 0)
"""


def verify_packages(python: Path, project: Path, pins: dict[str, str]) -> dict[str, str]:
    result = subprocess.run(
        [str(python), "-I", "-c", DEPENDENCY_PROBE, json.dumps(pins)],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    try:
        info = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise SetupError("Installed packages could not be checked: " + result.stderr.strip()) from exc
    if result.returncode or info["problems"]:
        raise SetupError("Package checks failed: " + "; ".join(info["problems"]))
    return info["versions"]


def write_environment_marker(project: Path, payload: dict):
    environment = validate_environment_target(project)
    state = {
        "installer": INSTALLER_ID,
        "project_root": str(project.resolve()),
        "environment_root": str(environment),
        **payload,
    }
    temporary = environment / (ENVIRONMENT_MARKER + ".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, environment / ENVIRONMENT_MARKER)


def install(project: Path, args: argparse.Namespace, log: InstallerLog):
    project = project.resolve()
    selected_version = sys.version_info[:2]
    if not MIN_PYTHON <= selected_version < MAX_PYTHON:
        raise SetupError(
            f"Python {platform.python_version()} is unsupported. "
            "Install Python 3.12, 3.13 or 3.14 from python.org, then run INSTALL.bat again. "
            "Python 3.12 is the preferred runtime."
        )
    log.write(f"Python {platform.python_version()} ({struct.calcsize('P') * 8}-bit): {sys.executable}")
    log.write("App folder: " + str(project))
    requirements = project / "requirements.txt"
    pins = read_pins(requirements)
    if not (project / "launch.py").is_file() or not (project / "frontend" / "dist" / "index.html").is_file():
        raise SetupError(
            "The release is incomplete: launch.py or the bundled browser interface is missing. "
            "Extract or copy the complete app folder. End users do not need Node."
        )
    environment = validate_environment_target(project)
    wheel_dir = Path(args.wheel_dir).expanduser().resolve() if args.wheel_dir else None
    # Validate offline options before changing any environment files.
    command = pip_install_command(environment_python(environment), requirements, args.offline, wheel_dir)
    data = data_directory(project)
    if data == environment or environment in data.parents:
        raise SetupError(
            "CA_DATA_DIR points inside .venv. Choose a data folder outside .venv "
            "so environment repairs can preserve your sources and reviews."
        )
    log.write("Data folder: " + str(data))
    with RuntimeLock(data / "runtime.lock"):
        problem = environment_problem(project, selected_version)
        if args.repair and environment.exists():
            problem = "A fresh environment was requested with --repair."
        if problem:
            log.write(problem)
            if environment.exists():
                log.write("Rebuilding only .venv. Saved sources, settings and reviews are preserved.")
                remove_environment(project)
            environment.mkdir()
            write_environment_marker(project, {"status": "creating"})
            log.write("Creating the app's local Python environment...")
            venv.EnvBuilder(with_pip=True, symlinks=False).create(environment)
        else:
            log.write("Using the compatible local environment.")
        write_environment_marker(project, {"status": "installing"})
        log.write("Installing the pinned release packages" + (" from the offline bundle..." if args.offline else "..."))
        run_logged(command, project, log)
        log.write("Checking package versions, imports and the local timezone...")
        versions = verify_packages(environment_python(environment), project, pins)
        run_logged(
            [str(environment_python(environment)), "-I", "-m", "pip", "--disable-pip-version-check", "check"],
            project,
            log,
        )
        write_environment_marker(
            project,
            {
                "status": "ready",
                "python_version": platform.python_version(),
                "python_bits": struct.calcsize("P") * 8,
                "requirements_sha256": hashlib.sha256(requirements.read_bytes()).hexdigest(),
                "packages": versions,
                "installed_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    log.write("Installation complete. Double-click RUN.bat to open the dashboard.")
    log.write("For a diagnostic report, use CHECK.bat.")


def parse_arguments(arguments: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Set up the local Call Avoidance Detector.")
    parser.add_argument("--offline", action="store_true", help="Install only from a supplied wheel bundle; do not use PyPI.")
    parser.add_argument("--wheel-dir", metavar="FOLDER", help="Folder of wheels matching this computer and Python version.")
    parser.add_argument("--repair", action="store_true", help="Recreate only .venv while preserving application data.")
    return parser.parse_args([arg for arg in arguments if arg.lower() != "/nopause"])


def main(arguments: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    args = parse_arguments(arguments)
    # A user may have activated a venv before choosing INSTALL. Recreate using
    # its base interpreter so setup never deletes its own running executable.
    if sys.prefix != sys.base_prefix:
        base = Path(getattr(sys, "_base_executable", ""))
        if not base.is_file() or base.resolve() == Path(sys.executable).resolve():
            print("The activated environment has no working base Python. Use INSTALL.bat outside that environment.")
            return 1
        return subprocess.call([str(base), "-I", str(PROJECT / "setup.py"), *arguments], cwd=PROJECT)
    log_path = PROJECT / "runtime" / "install.log"
    try:
        with InstallerLog(log_path) as log:
            try:
                install(PROJECT, args, log)
            except KeyboardInterrupt:
                log.write("Installation cancelled. Re-run INSTALL.bat to finish setup.")
                return 130
            except (SetupError, OSError, subprocess.SubprocessError) as exc:
                log.write("INSTALLATION NEEDS ACTION: " + str(exc))
                log.write("Installation log: " + str(log_path))
                return getattr(exc, "exit_code", 1)
    except OSError as exc:
        print("Cannot write the installation log: " + str(exc), file=sys.stderr)
        print("Move the complete app folder to a writable user folder and run INSTALL.bat again.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Portable command entry: run, check, demo, import and test."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
import socket
import subprocess
import sys
import threading
import uuid
import webbrowser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

PROJECT = Path(__file__).resolve().parent
PRODUCT = "call-avoidance-review"
_RUN_LOG_LOCK = threading.Lock()


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


# Local health/report checks must remain on this computer even if the shell
# configures a network proxy or another program responds with a redirect.
urlopen = build_opener(ProxyHandler({}), _NoRedirect()).open


def run_event(event: str, **details) -> None:
    """Record launcher events only; source rows and review notes stay in data."""
    try:
        path = PROJECT / "runtime" / "run.log"
        entry = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "event": event, **details}
        with _RUN_LOG_LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(entry, ensure_ascii=False, allow_nan=False) + "\n")
                stream.flush()
    except OSError as exc:
        print("The run log could not be saved:", str(exc), file=sys.stderr)


def runtime_problems() -> list[str]:
    problems = []
    marker = PROJECT / ".venv" / "ca_environment.json"
    try:
        state = json.loads(marker.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError("Invalid environment marker")
        if state.get("installer") != "call-avoidance-detector" or state.get("status") != "ready":
            problems.append("Installation is incomplete. Run INSTALL.bat.")
        if Path(state.get("project_root", "")).resolve() != PROJECT:
            problems.append("This folder was moved or copied. Run INSTALL.bat on this computer.")
        if state.get("requirements_sha256") != hashlib.sha256((PROJECT / "requirements.txt").read_bytes()).hexdigest():
            problems.append("The release's package requirements changed. Run INSTALL.bat.")
    except (OSError, ValueError, TypeError):
        problems.append("This computer's app environment is not ready. Run INSTALL.bat.")
    if Path(sys.prefix).resolve() != (PROJECT / ".venv").resolve():
        problems.append("Use RUN.bat or this folder's .venv Python to run the app.")
    try:
        for line in (PROJECT / "requirements.txt").read_text(encoding="utf-8").splitlines():
            if "==" not in line:
                continue
            package, expected = line.strip().split("==", 1)
            if importlib.metadata.version(package) != expected:
                problems.append(package + " does not match this release. Run INSTALL.bat.")
    except (OSError, importlib.metadata.PackageNotFoundError):
        problems.append("A release package is missing. Run INSTALL.bat.")
    if not (PROJECT / "frontend" / "dist" / "index.html").exists():
        problems.append("The built browser interface is missing. Use the complete release folder.")
    return list(dict.fromkeys(problems))


def data_root() -> Path:
    value = Path(os.environ.get("CA_DATA_DIR", str(PROJECT / "runtime" / "data"))).expanduser()
    return (PROJECT / value).resolve() if not value.is_absolute() else value.resolve()


class InstanceLock:
    def __init__(self, path: Path):
        self.path = path
        self.stream = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("a+b")
        self.stream.seek(0, 2)
        if self.stream.tell() == 0:
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            self.stream = None
            raise RuntimeError("This data folder is already used by the running app or installer.")

    def close(self):
        if self.stream:
            self.stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
            self.stream.close()
            self.stream = None


def health(port: int) -> dict | None:
    try:
        with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
            result = json.load(response)
            return result if isinstance(result, dict) and result.get("product") == PRODUCT else None
    except HTTPError as exc:
        exc.close()
        return None
    except (OSError, ValueError, URLError):
        return None


def matching_instance(root: Path) -> tuple[int, dict] | None:
    """Trust an instance only when its saved identity and health agree."""
    try:
        info = json.loads((root / "instance.json").read_text(encoding="utf-8"))
        if not isinstance(info, dict) or not isinstance(info.get("instance_id"), str) or not info["instance_id"]:
            return None
        port = int(info["port"])
        if not 1 <= port <= 65535:
            return None
        existing = health(port)
        if existing and existing.get("instance_id") == info["instance_id"] \
                and Path(existing.get("data_directory", "")).resolve() == root.resolve() \
                and Path(existing.get("project_directory", "")).resolve() == PROJECT:
            return port, existing
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def source_summary(root: Path, running: tuple[int, dict] | None) -> dict | None:
    """Read saved report metadata without importing workbooks or creating a store."""
    report = None
    publication = {}
    if running:
        port, status = running
        publication = status.get("publication") or {}
        try:
            with urlopen(f"http://127.0.0.1:{port}/api/report", timeout=3) as response:
                report = json.load(response)
        except HTTPError as exc:
            exc.close()
        except (OSError, ValueError):
            pass
    if report is None:
        pointer = root / "current.json"
        if not pointer.exists():
            return None
        saved = json.loads(pointer.read_text(encoding="utf-8"))
        location = saved["publication"]
        if not isinstance(location, str):
            raise ValueError("Saved report pointer is invalid.")
        target = (root / location).resolve()
        if not target.is_relative_to(root.resolve()) or target == root.resolve():
            raise ValueError("Saved report pointer refers outside the data folder.")
        publication = json.loads(target.read_text(encoding="utf-8"))
        report = publication["report"]
    if not isinstance(report, dict) or not isinstance(report.get("coverage"), dict):
        raise ValueError("Saved report coverage is invalid.")
    return {
        "report_date": report.get("report_date"),
        "synthetic": bool(report.get("synthetic")),
        "coverage": report["coverage"],
        "latest_source_time": report.get("latest_source_time"),
        "published_at": publication.get("published_at"),
    }


def local_time(value) -> str:
    if not isinstance(value, str) or not value:
        return "Unavailable"
    try:
        from zoneinfo import ZoneInfo
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(ZoneInfo("America/Mexico_City")).isoformat(sep=" ", timespec="seconds") + " (America/Mexico_City)"
    except (ValueError, KeyError):
        return "Unavailable"


def occupied(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.2)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def check() -> int:
    problems = runtime_problems()
    if not (3, 12) <= sys.version_info[:2] < (3, 15):
        problems.append("Install Python 3.12, 3.13 or 3.14, then run INSTALL.bat.")
    for package, module in [("openpyxl", "openpyxl"), ("fastapi", "fastapi"), ("uvicorn", "uvicorn"), ("python-multipart", "python_multipart"), ("defusedxml", "defusedxml")]:
        try:
            __import__(module)
            print("PASS", package, importlib.metadata.version(package))
        except (ImportError, importlib.metadata.PackageNotFoundError):
            problems.append(package + " is missing; run INSTALL.bat.")
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo("America/Mexico_City")
        print("PASS business timezone")
    except Exception:
        problems.append("Timezone data is missing; run INSTALL.bat.")
    if not (PROJECT / "frontend" / "dist" / "index.html").exists():
        problems.append("The built browser interface is missing. Use the complete release folder.")
    target = data_root()
    existing = target
    while not existing.exists():
        existing = existing.parent
    if not os.access(existing, os.W_OK):
        problems.append("Data location is not writable; set CA_DATA_DIR to a private user folder.")
    print("Data location:", target)
    print("Python:", sys.version.split()[0], "at", sys.executable)
    port = int(os.environ.get("CA_PORT", "8505"))
    if not 1024 <= port <= 65515:
        raise ValueError("Set CA_PORT to a local port between 1024 and 65515.")
    running = matching_instance(target)
    if running:
        print("Running app:", f"http://127.0.0.1:{running[0]}")
        job = running[1].get("job") or {}
        print("Current task:", job.get("message", "Ready"))
    elif occupied(port):
        print("Port", port, "is used by another program; RUN will choose an available local port.")
    try:
        summary = source_summary(target, running)
        if summary:
            coverage = summary["coverage"]
            print("Saved report date:", summary["report_date"], "(synthetic demonstration)" if summary["synthetic"] else "(operational sources)")
            print("Source coverage:", coverage.get("status", "Unknown"))
            print("Baseline:", "Complete" if coverage.get("baseline_complete") else "Insufficient history")
            print("Complete / expected export days:", len(coverage.get("complete_days", [])), "/", len(coverage.get("expected_days", [])))
            print("Latest source:", local_time(summary["latest_source_time"]))
            print("Report published:", local_time(summary["published_at"]))
            missing = coverage.get("missing_baseline_days", [])
            if missing:
                print("Missing baseline days:", ", ".join(str(day) for day in missing))
            if not coverage.get("report_date_complete") or not coverage.get("baseline_complete"):
                problems.append("Supply accepted complete exports for the missing days. Missing days are not zero calls.")
        else:
            print("Source coverage: No saved report yet. RUN.bat prepares the demonstration on first start.")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        problems.append("Saved report metadata could not be read: " + str(exc))
    print("Installation log:", PROJECT / "runtime" / "install.log")
    print("Run log:", PROJECT / "runtime" / "run.log")
    for problem in problems:
        print("NEEDS ACTION:", problem)
    return 1 if problems else 0


def run(port: int, no_browser: bool, empty: bool) -> int:
    root = data_root()
    instance_path = root / "instance.json"
    existing = matching_instance(root)
    if existing:
        url = f"http://127.0.0.1:{existing[0]}"
        print("Already running:", url)
        run_event("reused", url=url, instance_id=existing[1]["instance_id"])
        if not no_browser:
            webbrowser.open(url)
        return 0
    run_event("start_requested", requested_port=port, python=sys.version.split()[0], data_directory=str(root))
    lock = InstanceLock(root / "runtime.lock")
    lock.acquire()
    shutdown = threading.Event()
    readiness_guard = threading.Lock()
    try:
        problems = runtime_problems()
        if problems:
            raise RuntimeError(" ".join(problems))
        from avoidance.webapp import create_app
        import uvicorn
        requested = port
        while occupied(port) and port < requested + 20:
            port += 1
        if occupied(port):
            raise RuntimeError("No free local port found. Set CA_PORT to another unused port.")
        instance_id = uuid.uuid4().hex
        from avoidance.store import atomic_json
        atomic_json(instance_path, {"port": port, "instance_id": instance_id, "pid": os.getpid(), "data_directory": str(root)})
        url = f"http://127.0.0.1:{port}"
        if port != requested:
            print(f"Port {requested} was busy. Using {port}.")
            run_event("port_changed", requested_port=requested, actual_port=port)
        print("Call review desk:", url)
        print("Leave this window open. Press Ctrl+C here to stop.")
        run_event("starting", url=url, instance_id=instance_id, pid=os.getpid())
        def open_when_ready():
            for _ in range(100):
                if shutdown.is_set():
                    return
                state = health(port)
                if state and state.get("instance_id") == instance_id and state.get("ready"):
                    with readiness_guard:
                        if shutdown.is_set():
                            return
                        run_event("ready", url=url, instance_id=instance_id)
                    if not no_browser and not shutdown.is_set():
                        webbrowser.open(url)
                    return
                if shutdown.wait(0.2):
                    return
            with readiness_guard:
                if shutdown.is_set():
                    return
                print("Browser could not confirm readiness. Inspect the errors in this window.")
                run_event("readiness_timeout", url=url, instance_id=instance_id)
        threading.Thread(target=open_when_ready, daemon=True).start()
        server = uvicorn.Server(uvicorn.Config(create_app(root, seed_demo=not empty, instance_id=instance_id), host="127.0.0.1", port=port, log_level="warning"))
        server.run()
        return 0
    finally:
        with readiness_guard:
            shutdown.set()
        try:
            instance_path.unlink(missing_ok=True)
        finally:
            lock.close()
            run_event("stopped", pid=os.getpid())


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description="Local Call Avoidance Detector")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--port", type=int, default=os.environ.get("CA_PORT", "8505"))
    run_parser.add_argument("--no-browser", action="store_true")
    run_parser.add_argument("--empty", action="store_true", help="Do not seed synthetic data on first start")
    sub.add_parser("check")
    sub.add_parser("test")
    demo_parser = sub.add_parser("demo")
    demo_parser.add_argument("--output", type=Path, default=PROJECT / "runtime" / "demo-input")
    import_parser = sub.add_parser("import")
    import_parser.add_argument("--input", required=True, type=Path)
    import_parser.add_argument("--report-date")
    args = parser.parse_args([a for a in sys.argv[1:] if a.lower() != "/nopause"])
    try:
        if args.command == "check":
            return check()
        if args.command == "test":
            return subprocess.call([sys.executable, "-m", "unittest", "discover", "-s", str(PROJECT / "tests"), "-v"], cwd=PROJECT)
        if args.command == "run":
            if not 1024 <= args.port <= 65515:
                raise ValueError("Choose a local port between 1024 and 65515.")
            return run(args.port, args.no_browser or os.environ.get("CA_NO_UI") == "1", args.empty)
        if args.command == "demo":
            from avoidance.fixtures import generate_demo
            generate_demo(args.output)
            print("Synthetic inputs created:", args.output.resolve())
            return 0
        from avoidance.store import LocalStore
        lock = InstanceLock(data_root() / "runtime.lock")
        lock.acquire()
        try:
            store = LocalStore(data_root())
            store.begin_job("Importing local files")
            report = store.run_job(store.import_folder, args.input, args.report_date)
            print(json.dumps({"report_date": report["report_date"], "publication": report["publication"], "overview": report.get("overview")}, indent=2))
            return 1 if store.status()["job"]["state"] == "failed" else 0
        finally:
            lock.close()
    except KeyboardInterrupt:
        print("App stopped. You can close this window.")
        return 0
    except (ValueError, RuntimeError, ImportError, OSError) as exc:
        print("Could not complete:", str(exc))
        if args.command == "run":
            run_event("error", error_type=type(exc).__name__, message=str(exc)[:2000])
        print("Run CHECK.bat for help; logs are in runtime/install.log and runtime/run.log.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

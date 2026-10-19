"""File-backed publications with immutable source copies and local reviews."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any

from .detector import DEFAULT_SETTINGS, ENGINE_VERSION, build_report
from .readers import PARSER_VERSION, read_dataset
from .cache import load_dataset, save_dataset

STORE_VERSION = "2"
REVIEW_STATES = {"Needs review", "Technical issue", "Legitimate interaction", "Coaching follow-up", "Escalated for authorized review"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def safe_relative(value: str) -> Path:
    if not isinstance(value, str):
        raise ValueError("Use a relative file path inside the input folder.")
    value = value.replace("\\", "/")
    parts = value.split("/")
    if not value or value.startswith("/") or any(part in ("", ".", "..") or ":" in part for part in parts):
        raise ValueError("Use a relative file path inside the input folder.")
    return Path(*parts)


def review_summary(record: dict) -> dict:
    """Keep immutable provenance on disk; send only review display fields."""
    fields = ("id", "evidence_id", "publication_id", "agent_id", "state", "reviewer", "note", "timestamp")
    return {key: record[key] for key in fields if key in record}


class LocalStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._dataset: dict | None = None
        self._transaction_index: dict | None = None
        self._publication: dict | None = None
        self._inspection_publication: dict | None = None
        self._inspection_dataset: dict | None = None
        self._inspection_transaction_index: dict | None = None
        self.job: dict = {"state": "idle", "message": "Ready", "updated_at": utc_now()}
        self.attempts: list[dict] = []
        self.settings = dict(DEFAULT_SETTINGS)
        settings_path = self.root / "settings.json"
        if settings_path.exists():
            self.settings.update(json.loads(settings_path.read_text(encoding="utf-8")))
        pointer = self.root / "current.json"
        if pointer.exists():
            try:
                location = safe_relative(json.loads(pointer.read_text(encoding="utf-8"))["publication"])
                self._publication = json.loads((self.root / location).read_text(encoding="utf-8"))
            except (OSError, ValueError, KeyError) as exc:
                self.job = {"state": "failed", "message": "Saved report could not be read: " + str(exc), "updated_at": utc_now()}

    def _event(self, name: str, value: dict) -> None:
        path = self.root / (name + ".jsonl")
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def status(self) -> dict:
        with self._lock:
            pub = self._publication
            return {"job": dict(self.job), "has_report": pub is not None,
                    "publication": {k: pub[k] for k in ("id", "published_at", "input_fingerprint", "import_seconds")} if pub else None,
                    "attempts": list(self.attempts[-8:]), "explanations": "computed", "data_directory": str(self.root)}

    def begin_job(self, message: str) -> None:
        with self._lock:
            if self.job["state"] == "running":
                raise ValueError("Another import or settings update is still running.")
            self.job = {"state": "running", "message": message, "updated_at": utc_now()}

    def run_job(self, function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as exc:
            with self._lock:
                self.job = {"state": "failed", "message": str(exc), "updated_at": utc_now()}
                self._event("attempts", dict(self.job))
            raise

    def _retain_sources(self, source: Path) -> tuple[Path, str]:
        source = source.resolve()
        if not source.is_dir():
            raise ValueError("The input folder does not exist.")
        if self.root.is_relative_to(source):
            raise ValueError("Choose the export folder itself; it must not contain this app's runtime data folder.")
        candidates = sorted(p for p in source.rglob("*") if p.is_file() and (p.suffix.lower() == ".xlsx" or p.name in {"manifest.json", "incidents.json"}))
        if not candidates:
            raise ValueError("No Excel workbooks or completeness manifest found in the input folder.")
        staging = self.root / "staging" / uuid.uuid4().hex
        staging.mkdir(parents=True)
        inventory = []
        try:
            for original in candidates:
                relative = original.relative_to(source)
                if original.is_symlink() or not original.resolve().is_relative_to(source):
                    raise ValueError("Input files must stay within their source folder.")
                target = staging / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original, target)
                digest = hashlib.sha256(target.read_bytes()).hexdigest()
                inventory.append({"file": relative.as_posix(), "sha256": digest})
            digest = fingerprint({"files": inventory, "parser_version": PARSER_VERSION, "store_version": STORE_VERSION})
            archive = self.root / "sources" / digest
            if archive.exists():
                shutil.rmtree(staging)
            else:
                archive.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staging, archive)
            return archive, digest
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def import_folder(self, source: Path, report_date: str | None = None) -> dict:
        started = time.perf_counter()
        archive, digest = self._retain_sources(source)
        cache = self.root / "normalized" / (digest + ".json")
        with self._lock:
            same_date = bool(self._publication) and (report_date == self._publication["report"]["report_date"] if report_date is not None else self._publication.get("requested_report_date") is None)
            if self._publication and self._publication["input_fingerprint"] == digest and same_date and self._publication["report"]["settings"] == self.settings and self._publication["report"].get("engine_version") == ENGINE_VERSION:
                self.job = {"state": "done", "message": "Report ready — unchanged input and rules reused", "updated_at": utc_now()}
                self._event("attempts", {**self.job, "publication_id": self._publication["id"], "input": digest, "reused_normalized": True, "import_seconds": round(time.perf_counter() - started, 4)})
                result = self.report()
                result["publication"] = {**result["publication"], "reused_normalized": True}
                return result
        reused = cache.exists()
        dataset = load_dataset(cache) if reused else read_dataset(archive)
        if not reused:
            save_dataset(cache, dataset)
        if not dataset.get("transactions") and not dataset.get("snapshots"):
            raise ValueError("No valid transactions or agent snapshots were imported. The previous report was preserved.")
        report = build_report(dataset, self.settings, report_date)
        with self._lock:
            if self._publication and bool(self._publication["report"].get("synthetic")) != bool(dataset.get("manifest", {}).get("synthetic")):
                raise ValueError("Keep synthetic and operational inputs in separate data folders. Configure CA_DATA_DIR for the other dataset.")
            # Failed replacements retain a known completed report, with the failed attempt visible.
            selected = report.get("report_date")
            errors = [i for i in dataset.get("issues", []) if i.get("severity") == "error"]
            if self._publication and errors and selected not in dataset.get("complete_days", []):
                attempt = {"state": "failed", "message": "The analyzed day's replacement is incomplete. Previous report preserved.", "issues": errors, "updated_at": utc_now()}
                self.attempts.append(attempt)
                self.job = attempt
                self._event("attempts", attempt)
                return self.report()
            publication_id = fingerprint({"input": digest, "engine_version": ENGINE_VERSION, "settings": self.settings, "report_date": selected})
            publication = {"id": publication_id, "published_at": utc_now(), "input_fingerprint": digest,
                           "requested_report_date": report_date,
                           "normalized": cache.relative_to(self.root).as_posix(), "sources": archive.relative_to(self.root).as_posix(),
                           "import_seconds": round(time.perf_counter() - started, 4), "reused_normalized": reused,
                           "report": report, "import_summary": dataset.get("import_summary", {}), "issues": dataset.get("issues", [])}
            location = self.root / "publications" / (publication_id + ".json")
            if self._publication and self._publication["id"] == publication_id:
                publication = self._publication
            else:
                atomic_json(location, publication)
                atomic_json(self.root / "current.json", {"publication": location.relative_to(self.root).as_posix()})
            self._publication, self._dataset = publication, dataset
            self._transaction_index = None
            self.job = {"state": "done", "message": "Report ready — unchanged workbooks reused" if reused else "Report ready", "updated_at": utc_now()}
            self._event("attempts", {**self.job, "publication_id": publication_id, "input": digest, "reused_normalized": reused})
            return self.report()

    def dataset(self) -> dict:
        with self._lock:
            if not self._publication:
                raise ValueError("No report has been published yet.")
            if self._dataset is None:
                self._dataset = self._load_publication_dataset(self._publication)
            return self._dataset

    def _recover_publication_dataset(self, publication: dict) -> dict:
        """Recover an unavailable cache in memory from unchanged retained inputs."""
        try:
            source = self.root / safe_relative(publication["sources"])
            if not source.is_dir():
                raise ValueError("Retained source folder is unavailable")
            restored = read_dataset(source)
            recorded = publication["report"]
            if recorded.get("engine_version") != ENGINE_VERSION:
                raise ValueError("The saved report uses another calculation version")
            verified = build_report(restored, recorded["settings"], recorded["report_date"])
            if set(verified["evidence"]) != set(recorded.get("evidence", {})):
                raise ValueError("Retained workbooks no longer match the saved evidence")
            return restored
        except (OSError, ValueError, KeyError) as exc:
            raise ValueError(
                "Saved source records are unavailable. Reload the latest report or import "
                "the original source folder again; the saved report and reviews are preserved. "
                f"({exc})"
            ) from exc

    def _load_publication_dataset(self, publication: dict) -> dict:
        try:
            return load_dataset(self.root / safe_relative(publication["normalized"]))
        except (OSError, ValueError, KeyError):
            return self._recover_publication_dataset(publication)

    def _inspection_context(self, publication_id: str | None) -> tuple[dict, dict, dict]:
        if not self._publication:
            raise ValueError("No report available.")
        current = self._publication
        if publication_id is None or publication_id == current["id"]:
            dataset = self.dataset()
            if self._transaction_index is None:
                self._transaction_index = {str(row["transaction_id"]): row for row in dataset.get("transactions", [])}
            return current, dataset, self._transaction_index
        if not isinstance(publication_id, str) or not re.fullmatch(r"[a-f0-9]{64}", publication_id):
            raise ValueError("Use the saved report identifier supplied by the review desk.")
        if not self._inspection_publication or self._inspection_publication["id"] != publication_id:
            try:
                path = self.root / "publications" / (publication_id + ".json")
                publication = json.loads(path.read_text(encoding="utf-8"))
                if publication.get("id") != publication_id or not isinstance(publication.get("report"), dict):
                    raise ValueError("Saved report identity disagrees with its file")
                dataset = self._load_publication_dataset(publication)
            except (OSError, ValueError, KeyError) as exc:
                raise KeyError(
                    "This saved report's source evidence is unavailable. Reload the latest "
                    "report or import the original source folder again."
                ) from exc
            self._inspection_publication = publication
            self._inspection_dataset = dataset
            self._inspection_transaction_index = {str(row["transaction_id"]): row for row in dataset.get("transactions", [])}
        return self._inspection_publication, self._inspection_dataset, self._inspection_transaction_index

    def reviews(self, evidence_id: str | None = None) -> list[dict]:
        with self._lock:
            path = self.root / "reviews.jsonl"
            result = []
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    if evidence_id is None or record.get("evidence_id") == evidence_id:
                        result.append(record)
            return result

    def report(self) -> dict:
        with self._lock:
            if self._publication is None:
                raise ValueError("The first report is still being prepared.")
            publication = self._publication
            result = dict(publication["report"])
            # Evidence stays on the server; each detail request is paginated.
            result.pop("evidence", None)
            result["publication"] = {k: publication[k] for k in ("id", "published_at", "import_seconds", "reused_normalized")}
            result["import_summary"] = publication["import_summary"]
            result["import_issues"] = publication["issues"]
            result["job"] = dict(self.job)
            latest = {}
            for review in self.reviews():
                latest[review["evidence_id"]] = review_summary(review)
            result["reviews"] = latest
            result["settings"] = self.settings
            return result

    def evidence(self, evidence_id: str, page: int = 1, page_size: int = 100, scope: str = "current",
                 publication_id: str | None = None, signals_only: bool = False) -> dict:
        with self._lock:
            if page < 1 or not 1 <= page_size <= 100:
                raise ValueError("Use a positive page and at most 100 rows.")
            publication, dataset, transaction_index = self._inspection_context(publication_id)
            evidence = publication["report"].get("evidence", {}).get(evidence_id)
            if evidence is None:
                raise KeyError("This evidence is unavailable in the selected report. Reload the latest report.")
            if scope not in {"current", "peer", "self"}:
                raise ValueError("Choose current, peer or self transaction evidence.")
            if scope != "current" and evidence.get("kind") != "daily":
                raise ValueError("Aggregate leads have no transaction baseline evidence.")
            baselines = evidence.get("baseline_transaction_ids", {})
            all_ids = evidence.get("transaction_ids", []) if scope == "current" else baselines.get(scope, [])
            if any(str(identifier) not in transaction_index for identifier in all_ids):
                dataset = self._recover_publication_dataset(publication)
                transaction_index = {str(row["transaction_id"]): row for row in dataset.get("transactions", [])}
                if publication["id"] == self._publication["id"]:
                    self._dataset, self._transaction_index = dataset, transaction_index
                else:
                    self._inspection_dataset, self._inspection_transaction_index = dataset, transaction_index
                if any(str(identifier) not in transaction_index for identifier in all_ids):
                    raise KeyError("Some saved transaction evidence is unavailable. Reload the latest report.")
            selected_ids = all_ids
            threshold = evidence.get("result", {}).get("short_handle_seconds")
            threshold_fraction = Fraction(str(threshold)) if threshold is not None else None
            def is_signal(row):
                return threshold_fraction is not None and Fraction(str(row["duration_seconds"])) <= threshold_fraction and row["transfers"] == 0
            if signals_only:
                if evidence.get("kind") != "daily":
                    raise ValueError("Aggregate leads have no per-transaction short-record evidence.")
                selected_ids = [identifier for identifier in all_ids if is_signal(transaction_index[str(identifier)])]
            ids = selected_ids[(page - 1) * page_size:page * page_size]
            rows = [transaction_index[str(identifier)] for identifier in ids]
            result = {key: value for key, value in evidence.items() if key not in {"sources", "baseline_transaction_ids", "signal_transactions"}}
            result.update({"id": evidence_id, "transactions": rows, "page": page, "page_size": page_size,
                           "scope": scope, "population_count": len(all_ids), "transaction_count": len(selected_ids),
                           "signals_only": signals_only,
                           "publication_id": publication["id"], "current_publication_id": self._publication["id"],
                           "is_current": publication["id"] == self._publication["id"],
                           "report_date": publication["report"]["report_date"],
                           "baseline_counts": {key: len(value) for key, value in baselines.items()},
                           "reviews": [review_summary(r) for r in self.reviews(evidence_id)]})
            if evidence.get("kind") == "daily":
                result["signal_transaction_ids"] = [row["transaction_id"] for row in rows if is_signal(row)]
                result["sources"] = [source for row in rows for source in row.get("sources", [])]
            if evidence.get("kind") == "intraday":
                original_sources = {}
                for snapshot in dataset.get("snapshots", []):
                    for agent in snapshot.get("agents", []):
                        if agent.get("agent_id") != evidence.get("agent_id"):
                            continue
                        for source in agent.get("sources", []):
                            key = tuple(source.get(k) for k in ("file", "sha256", "sheet", "row"))
                            original_sources[key] = source
                result["sources"] = [original_sources.get(tuple(source.get(k) for k in ("file", "sha256", "sheet", "row")), source) for source in evidence.get("sources", [])]
            result["annotations"] = publication["report"].get("annotations", [])
            # Earlier evidence decisions are context; they never become a review of the new evidence.
            agent_id = evidence.get("agent_id")
            result["earlier_reviews"] = [review_summary(r) for r in self.reviews() if agent_id and r.get("agent_id") == agent_id and r["evidence_id"] != evidence_id][-10:]
            return result

    def save_review(self, evidence_id: str, state: str, reviewer: str, note: str,
                    publication_id: str | None = None) -> dict:
        with self._lock:
            if publication_id is not None and (not self._publication or publication_id != self._publication["id"]):
                raise ValueError("The source report changed. Reload the latest report before saving this review.")
            if state not in REVIEW_STATES:
                raise ValueError("Choose a supported human review outcome.")
            if not reviewer.strip() or not note.strip():
                raise ValueError("Enter your reviewer label and an evidence-based note.")
            evidence = self.evidence(evidence_id)
            if evidence.get("kind") == "daily":
                reviewed_sources = [source for identifier in evidence["transaction_ids"] for source in self._transaction_index[str(identifier)].get("sources", [])]
            else:
                reviewed_sources = evidence.get("sources", [])
            source_fields = ("file", "sha256", "sheet", "row", "import_id")
            locators = [{key: source[key] for key in source_fields if key in source} for source in reviewed_sources]
            record = {"id": uuid.uuid4().hex, "evidence_id": evidence_id, "publication_id": self._publication["id"],
                      "agent_id": evidence.get("agent_id"), "state": state, "reviewer": reviewer.strip(), "note": note.strip(),
                      "timestamp": utc_now(), "transaction_ids": evidence.get("transaction_ids", []),
                      "sources": locators, "settings": self.settings}
            self._event("reviews", record)
            return record

    def update_settings(self, changes: dict) -> dict:
        with self._lock:
            unknown = set(changes) - set(DEFAULT_SETTINGS)
            if unknown:
                raise ValueError("Unknown settings: " + ", ".join(sorted(unknown)))
            if "version" in changes:
                raise ValueError("The rule version is assigned automatically when settings change.")
            proposed = {**self.settings, **changes}
            for key, value in proposed.items():
                if key == "version":
                    continue
                if key == "short_handle_seconds" and isinstance(value, dict):
                    if not value or any(not isinstance(k, str) for k in value) or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in value.values()):
                        raise ValueError("Call-type thresholds must be nonnegative numbers.")
                elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    raise ValueError(key + " must be a nonnegative number.")
            if proposed["daily_min_rate"] > 1 or proposed["rate_increase_pp"] > 100:
                raise ValueError("Rate must be 0–1; percentage-point change must be 0–100.")
            integer_keys = {"daily_min_transactions", "daily_min_signals", "baseline_days", "peer_min_transactions", "self_min_transactions", "self_min_active_days", "interval_min_transactions", "intraday_consecutive_intervals"}
            for key in integer_keys:
                if proposed[key] != int(proposed[key]) or proposed[key] < 1:
                    raise ValueError(key + " must be a positive integer.")
                proposed[key] = int(proposed[key])
            if proposed["interval_max_minutes"] < proposed["interval_min_minutes"]:
                raise ValueError("Maximum interval must be at least the minimum interval.")
            if proposed["baseline_days"] > 365:
                raise ValueError("The local demo supports at most 365 baseline days.")
            if not self._publication:
                raise ValueError("Load data before changing rules.")
            numeric_settings = {k: v for k, v in proposed.items() if k != "version"}
            proposed["version"] = "rules-" + fingerprint(numeric_settings)[:12]
            report = build_report(self.dataset(), proposed, self._publication["report"]["report_date"])
            new = {**self._publication, "settings": proposed, "report": report, "published_at": utc_now()}
            new["id"] = fingerprint({"input": new["input_fingerprint"], "engine_version": ENGINE_VERSION, "settings": proposed, "report_date": report["report_date"]})
            location = self.root / "publications" / (new["id"] + ".json")
            atomic_json(location, new)
            atomic_json(self.root / "settings.json", proposed)
            atomic_json(self.root / "current.json", {"publication": location.relative_to(self.root).as_posix()})
            self.settings, self._publication = proposed, new
            self._event("settings_history", {"timestamp": utc_now(), "settings": proposed, "publication_id": new["id"]})
            self.job = {"state": "done", "message": "Rules updated; review previous decisions against the new evidence", "updated_at": utc_now()}
            return self.report()

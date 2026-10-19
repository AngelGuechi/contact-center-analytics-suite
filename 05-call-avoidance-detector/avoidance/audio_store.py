"""Durable SQLite audio inventory and stage queue; immutable evidence artifacts.

Rollback journaling deliberately supports the core application's older bundled
SQLite. Audio inference never executes while a database transaction is open.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

from .store import REVIEW_STATES, atomic_json, fingerprint, utc_now

DEFAULT_POLICY = {"random_sample_size": 50, "sample_seed": "pilot-v1",
                  "candidate_source": "spreadsheet_short_patterns", "quiet_candidate_seconds": None,
                  "asr_language": "auto"}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


class AudioStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve() / "audio"
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "index.sqlite3"
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS imports(id TEXT PRIMARY KEY, publication_id TEXT NOT NULL,
                    synthetic INTEGER NOT NULL, created_at TEXT NOT NULL, csv_sha256 TEXT NOT NULL,
                    issues TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS import_files(import_id TEXT NOT NULL, filename TEXT NOT NULL,
                    entry TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending', recording_id TEXT,
                    PRIMARY KEY(import_id,filename));
                CREATE TABLE IF NOT EXISTS recordings(id TEXT PRIMARY KEY, publication_id TEXT NOT NULL,
                    filename TEXT NOT NULL, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL,
                    original TEXT NOT NULL, options TEXT NOT NULL, links TEXT NOT NULL,
                    synthetic INTEGER NOT NULL, candidate INTEGER NOT NULL, selection_reasons TEXT NOT NULL,
                    created_at TEXT NOT NULL, measurement_id TEXT, transcript_id TEXT, bundle_id TEXT);
                CREATE INDEX IF NOT EXISTS recording_publication ON recordings(publication_id,created_at,id);
                CREATE TABLE IF NOT EXISTS transaction_links(recording_id TEXT NOT NULL,
                    publication_id TEXT NOT NULL, transaction_id TEXT NOT NULL,
                    PRIMARY KEY(recording_id,publication_id,transaction_id));
                CREATE INDEX IF NOT EXISTS call_recordings ON transaction_links(publication_id,transaction_id);
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL,
                    operation TEXT NOT NULL, original TEXT NOT NULL, options TEXT NOT NULL,
                    state TEXT NOT NULL, message TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, started_at TEXT, completed_at TEXT,
                    owner TEXT, attempt INTEGER NOT NULL DEFAULT 0, result_id TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0, priority INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS queue_state ON jobs(state,operation,priority,created_at);
                CREATE TABLE IF NOT EXISTS recording_jobs(recording_id TEXT NOT NULL,job_id TEXT NOT NULL,
                    PRIMARY KEY(recording_id,job_id));
                CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY,operation TEXT NOT NULL,
                    path TEXT NOT NULL,created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS bundles(id TEXT PRIMARY KEY,recording_id TEXT NOT NULL,
                    publication_id TEXT NOT NULL,data TEXT NOT NULL,created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS reviews(id TEXT PRIMARY KEY,recording_id TEXT NOT NULL,
                    bundle_id TEXT NOT NULL,publication_id TEXT NOT NULL,data TEXT NOT NULL,created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS audio_reviews ON reviews(recording_id,created_at);
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS selections(publication_id TEXT NOT NULL,business_date TEXT NOT NULL,
                    policy_version TEXT NOT NULL,recording_id TEXT NOT NULL,reason TEXT NOT NULL,
                    PRIMARY KEY(publication_id,business_date,policy_version,recording_id,reason));
            """)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.database, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=15000")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def policy(self):
        with self.lock, self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key='policy'").fetchone()
            policy = {**DEFAULT_POLICY, **(json.loads(row[0]) if row else {})}
            policy["version"] = fingerprint(policy)[:16]
            return policy

    def set_policy(self, changes):
        import math
        if not isinstance(changes, dict) or set(changes) - set(DEFAULT_POLICY):
            raise ValueError("Use supported audio selection policy fields.")
        proposed = {**{k: v for k, v in self.policy().items() if k != "version"}, **changes}
        size = proposed["random_sample_size"]
        if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= 5000:
            raise ValueError("random_sample_size must be a whole number from 0 to 5,000.")
        seed = proposed["sample_seed"]
        if not isinstance(seed, str) or not seed.strip() or len(seed) > 200:
            raise ValueError("Enter a sample_seed of 1–200 characters.")
        threshold = proposed["quiet_candidate_seconds"]
        if threshold is not None and (isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold) or threshold <= 0):
            raise ValueError("quiet_candidate_seconds must be null (disabled) or a positive finite number.")
        if proposed["asr_language"] not in {"auto", "es", "en"} or proposed["candidate_source"] != "spreadsheet_short_patterns":
            raise ValueError("Use auto/es/en and candidate_source=spreadsheet_short_patterns.")
        with self.lock, self.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES('policy',?)", (_json(proposed),))
        return self.policy()

    def create_import(self, publication_id, synthetic, content, parsed):
        identifier = fingerprint({"publication_id": publication_id, "csv": hashlib.sha256(content).hexdigest()})
        with self.lock, self.connect() as db:
            db.execute("INSERT OR IGNORE INTO imports VALUES(?,?,?,?,?,?)", (identifier, publication_id, int(synthetic), utc_now(), hashlib.sha256(content).hexdigest(), _json(parsed["issues"])))
            for entry in parsed["files"]:
                db.execute("INSERT OR IGNORE INTO import_files(import_id,filename,entry) VALUES(?,?,?)", (identifier, entry["recording_file"], _json(entry)))
        return self.import_status(identifier)

    def import_status(self, identifier):
        with self.lock, self.connect() as db:
            row = db.execute("SELECT * FROM imports WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise KeyError("Recording import was not found.")
            files = [{"recording_file": f["filename"], "state": f["state"], "recording_id": f["recording_id"]}
                     for f in db.execute("SELECT * FROM import_files WHERE import_id=? ORDER BY filename", (identifier,))]
            return {"id": identifier, "publication_id": row["publication_id"], "synthetic": bool(row["synthetic"]),
                    "created_at": row["created_at"], "files": files, "issues": json.loads(row["issues"]),
                    "pending": sum(f["state"] == "pending" for f in files), "uploaded": sum(f["state"] == "uploaded" for f in files)}

    def import_entry(self, import_id, filename):
        with self.lock, self.connect() as db:
            row = db.execute("SELECT f.*,i.publication_id,i.synthetic FROM import_files f JOIN imports i ON i.id=f.import_id WHERE f.import_id=? AND f.filename=?", (import_id, filename)).fetchone()
            if not row:
                raise KeyError("Upload only a file listed by this import's recordings.csv.")
            return {**dict(row), "entry": json.loads(row["entry"])}

    def finish_import(self, identifier):
        """Explicitly leave missing files out; their CSV references remain visible."""
        batch = self.import_status(identifier)
        missing = [f['recording_file'] for f in batch['files'] if f['state'] == 'pending']
        if missing:
            issues = batch['issues'] + [{'code': 'missing_recording', 'file': name, 'message': 'Batch finished without this recording; it can be uploaded later.'} for name in missing]
            with self.lock, self.connect() as db:
                db.execute("UPDATE import_files SET state='skipped' WHERE import_id=? AND state='pending'", (identifier,))
                db.execute('UPDATE imports SET issues=? WHERE id=?', (_json(issues), identifier))
        return self.import_status(identifier)

    def register_recording(self, import_id, filename, sha256, size, original, candidate_ids):
        entry = self.import_entry(import_id, filename)
        identity = fingerprint({"publication": entry["publication_id"], "filename": filename, "sha256": sha256, "entry": entry["entry"]})
        links = entry["entry"]["links"]
        candidate = any(link["state"] == "matched" and set(link["transaction_ids"]) & candidate_ids for link in links)
        reasons = ["spreadsheet_review_candidate"] if candidate else []
        with self.lock, self.connect() as db:
            previous = db.execute("SELECT recording_id FROM import_files WHERE import_id=? AND filename=?", (import_id, filename)).fetchone()[0]
            if previous and previous != identity:
                raise ValueError("This import already retained different bytes for the file. Start a new CSV import to preserve its earlier evidence.")
            db.execute("INSERT OR IGNORE INTO recordings(id,publication_id,filename,sha256,bytes,original,options,links,synthetic,candidate,selection_reasons,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                       (identity, entry["publication_id"], filename, sha256, size, str(original.relative_to(self.root)), _json(entry["entry"]["options"]), _json(links), int(entry["synthetic"]), int(candidate), _json(reasons), utc_now()))
            for link in links:
                for transaction_id in link["transaction_ids"]:
                    db.execute("INSERT OR IGNORE INTO transaction_links VALUES(?,?,?)", (identity, entry["publication_id"], transaction_id))
            db.execute("UPDATE import_files SET state='uploaded',recording_id=? WHERE import_id=? AND filename=?", (identity, import_id, filename))
        return self.recording(identity)

    def _row(self, row):
        result = dict(row)
        for key in ("options", "links", "selection_reasons"):
            result[key] = json.loads(result[key])
        result["synthetic"], result["candidate"] = bool(result["synthetic"]), bool(result["candidate"])
        result["transaction_ids"] = sorted({identifier for link in result["links"] for identifier in link["transaction_ids"]})
        result["agent_ids"] = sorted({identifier for link in result["links"] for identifier in link["agent_ids"]})
        states = {link["state"] for link in result["links"]}
        result["link_state"] = next((state for state in ("ambiguous", "unmatched", "context", "matched") if state in states), "unmatched")
        result["issue"] = "; ".join(dict.fromkeys(link["issue"] for link in result["links"] if link.get("issue"))) or None
        result["media_url"] = f"/api/audio/recordings/{result['id']}/media"
        return result

    def recording(self, identifier):
        with self.lock, self.connect() as db:
            row = db.execute("SELECT * FROM recordings WHERE id=?", (identifier,)).fetchone()
            if not row:
                raise KeyError("Recording was not found.")
            return self._row(row)

    def original_path(self, identifier):
        path = (self.root / self.recording(identifier)["original"]).resolve()
        if not path.is_relative_to(self.root / "originals") or not path.is_file():
            raise KeyError("Retained recording bytes are unavailable.")
        return path

    def enqueue(self, recording_id, operation, options, priority=0):
        if operation not in {"measure", "transcribe", "preview"}:
            raise ValueError("Choose a supported audio stage.")
        recording = self.recording(recording_id)
        request_key = fingerprint({"audio_sha256": recording["sha256"], "operation": operation, "options": options})
        identifier = "job-" + request_key
        with self.lock, self.connect() as db:
            db.execute("INSERT OR IGNORE INTO jobs(id,request_key,operation,original,options,state,message,created_at,updated_at,priority) VALUES(?,?,?,?,?,'queued','Queued',?,?,?)",
                       (identifier, request_key, operation, recording["original"], _json(options), utc_now(), utc_now(), priority))
            db.execute("INSERT OR IGNORE INTO recording_jobs VALUES(?,?)", (recording_id, identifier))
            job = db.execute("SELECT * FROM jobs WHERE id=?", (identifier,)).fetchone()
            if job["state"] == "completed" and operation in {"measure", "transcribe"}:
                self._attach_result(db, recording_id, operation, job["result_id"])
        return self.job(identifier)

    def job(self, identifier):
        with self.lock, self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (identifier,)).fetchone()
            if not row:
                raise KeyError("Audio job was not found.")
            result = dict(row)
            result["options"] = json.loads(result["options"])
            result["cancel_requested"] = bool(result["cancel_requested"])
            return result

    def recording_jobs(self, identifier):
        with self.lock, self.connect() as db:
            return [self.job(row[0]) for row in db.execute("SELECT job_id FROM recording_jobs WHERE recording_id=? ORDER BY rowid", (identifier,))]

    def recover(self):
        with self.lock, self.connect() as db:
            db.execute("UPDATE jobs SET state=CASE WHEN cancel_requested=1 THEN 'cancelled' ELSE 'queued' END,owner=NULL,message='Interrupted worker recovered; retained results preserved',updated_at=? WHERE state='running'", (utc_now(),))

    def claim(self, owner, allow_transcribe, prefer_asr=False):
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            operations = "('measure','preview','transcribe')" if allow_transcribe else "('measure','preview')"
            ordering = "CASE WHEN operation='transcribe' THEN 0 WHEN operation='preview' THEN 1 ELSE 2 END" if prefer_asr else "CASE WHEN operation='preview' THEN 0 WHEN operation='measure' THEN 1 ELSE 2 END"
            row = db.execute(f"SELECT id FROM jobs WHERE state='queued' AND cancel_requested=0 AND operation IN {operations} ORDER BY {ordering},priority DESC,created_at LIMIT 1").fetchone()
            if not row:
                return None
            db.execute("UPDATE jobs SET state='running',owner=?,attempt=attempt+1,started_at=?,updated_at=?,message='Processing' WHERE id=? AND state='queued'", (owner, utc_now(), utc_now(), row[0]))
            identifier = row[0]
        return self.job(identifier)

    def progress(self, identifier, owner, message, progress=0):
        with self.lock, self.connect() as db:
            db.execute("UPDATE jobs SET message=?,progress=?,updated_at=? WHERE id=? AND owner=? AND state='running'", (str(message)[:1000], max(0, min(1, float(progress or 0))), utc_now(), identifier, owner))

    def _attach_result(self, db, recording_id, operation, result_id):
        field = "measurement_id" if operation == "measure" else "transcript_id"
        db.execute(f"UPDATE recordings SET {field}=? WHERE id=?", (result_id, recording_id))
        row = db.execute("SELECT * FROM recordings WHERE id=?", (recording_id,)).fetchone()
        data = {"recording_id": recording_id, "publication_id": row["publication_id"], "sha256": row["sha256"],
                "links": json.loads(row["links"]), "measurement_id": row["measurement_id"], "transcript_id": row["transcript_id"]}
        bundle_id = "bundle-" + fingerprint(data)
        db.execute("INSERT OR IGNORE INTO bundles VALUES(?,?,?,?,?)", (bundle_id, recording_id, row["publication_id"], _json(data), utc_now()))
        db.execute("UPDATE recordings SET bundle_id=? WHERE id=?", (bundle_id, recording_id))

    def complete(self, identifier, owner, result):
        job = self.job(identifier)
        result_id = "artifact-" + fingerprint({"request": job["request_key"], "result": result})
        location = self.root / "artifacts" / (result_id + ".json")
        atomic_json(location, result)
        with self.lock, self.connect() as db:
            row = db.execute("SELECT state,owner,cancel_requested FROM jobs WHERE id=?", (identifier,)).fetchone()
            if row["state"] != "running" or row["owner"] != owner or row["cancel_requested"]:
                return False  # Late output never publishes after cancellation/recovery.
            db.execute("INSERT OR IGNORE INTO artifacts VALUES(?,?,?,?)", (result_id, job["operation"], location.relative_to(self.root).as_posix(), utc_now()))
            db.execute("UPDATE jobs SET state='completed',result_id=?,owner=NULL,progress=1,message='Ready',completed_at=?,updated_at=? WHERE id=?", (result_id, utc_now(), utc_now(), identifier))
            if job["operation"] in {"measure", "transcribe"}:
                for recording in db.execute("SELECT recording_id FROM recording_jobs WHERE job_id=?", (identifier,)).fetchall():
                    self._attach_result(db, recording[0], job["operation"], result_id)
        return True

    def fail(self, identifier, owner, message, interrupted=False):
        with self.lock, self.connect() as db:
            state = "queued" if interrupted else "failed"
            db.execute("UPDATE jobs SET state=CASE WHEN cancel_requested=1 THEN 'cancelled' ELSE ? END,owner=NULL,message=?,updated_at=? WHERE id=? AND owner=? AND state='running'", (state, str(message)[:2000], utc_now(), identifier, owner))

    def cancel(self, identifier):
        with self.lock, self.connect() as db:
            db.execute("UPDATE jobs SET cancel_requested=1,state='cancelled',owner=NULL,message='Cancelled; source and completed evidence retained',updated_at=? WHERE id=? AND state IN ('queued','running')", (utc_now(), identifier))
        return self.job(identifier)

    def retry(self, identifier):
        if self.job(identifier)['attempt'] >= 3:
            raise ValueError('This stage failed three attempts. Correct the source or setup before creating a new analysis request.')
        with self.lock, self.connect() as db:
            db.execute("UPDATE jobs SET state='queued',cancel_requested=0,owner=NULL,message='Retry queued',updated_at=? WHERE id=? AND state IN ('failed','cancelled')", (utc_now(), identifier))
        return self.job(identifier)

    def artifact(self, identifier):
        if not identifier:
            return None
        with self.lock, self.connect() as db:
            row = db.execute("SELECT path FROM artifacts WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise KeyError("Audio analysis artifact was not found.")
        path = (self.root / row[0]).resolve()
        if not path.is_relative_to(self.root / "artifacts"):
            raise ValueError("Invalid saved audio artifact path.")
        return json.loads(path.read_text(encoding="utf-8"))

    def bundle(self, identifier):
        with self.lock, self.connect() as db:
            row = db.execute("SELECT data FROM bundles WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise KeyError("Saved audio bundle was not found.")
        return json.loads(row[0])

    def list_recordings(self, page=1, page_size=25, publication_id=None, transaction_id=None, search="", state=None):
        if page < 1 or not 1 <= page_size <= 100:
            raise ValueError("Use a positive page and at most 100 recordings.")
        conditions, values = [], []
        if publication_id:
            conditions.append("r.publication_id=?")
            values.append(publication_id)
        if transaction_id:
            conditions.append("EXISTS(SELECT 1 FROM transaction_links t WHERE t.recording_id=r.id AND t.publication_id=r.publication_id AND t.transaction_id=?)")
            values.append(str(transaction_id))
        if search:
            conditions.append("(r.filename LIKE ? OR EXISTS(SELECT 1 FROM transaction_links t WHERE t.recording_id=r.id AND t.transaction_id LIKE ?))")
            values += ["%" + search[:200] + "%"] * 2
        if state:
            if state not in {"queued", "running", "completed", "failed", "cancelled"}:
                raise ValueError("Choose a supported audio job state.")
            conditions.append("EXISTS(SELECT 1 FROM recording_jobs rj JOIN jobs j ON j.id=rj.job_id WHERE rj.recording_id=r.id AND j.state=?)")
            values.append(state)
        clause = " WHERE " + " AND ".join(conditions) if conditions else ""
        with self.lock, self.connect() as db:
            total = db.execute("SELECT COUNT(*) FROM recordings r" + clause, values).fetchone()[0]
            rows = db.execute("SELECT r.* FROM recordings r" + clause + " ORDER BY r.created_at DESC,r.id LIMIT ? OFFSET ?", values + [page_size, (page-1)*page_size]).fetchall()
        items = []
        for row in rows:
            item = self._row(row)
            jobs = self.recording_jobs(item["id"])
            for operation, field in (("measure", "measurement_state"), ("transcribe", "transcription_state")):
                own = [job for job in jobs if job["operation"] == operation]
                item[field] = own[-1]["state"] if own else "not_requested"
            measurement = self.artifact(item["measurement_id"])
            totals = (measurement or {}).get("conversation", {}).get("totals", {})
            item.update({"duration_seconds": (measurement or {}).get("scope", {}).get("duration_seconds"),
                         **{key: totals.get(key) for key in ("quiet_seconds", "no_speech_seconds", "longest_quiet_seconds")}})
            item.pop("original", None)
            items.append(item)
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def stage_status(self):
        stages = {operation: {state: 0 for state in ("queued", "running", "completed", "failed", "cancelled")} for operation in ("measure", "transcribe", "preview")}
        with self.lock, self.connect() as db:
            for row in db.execute("SELECT operation,state,COUNT(*) FROM jobs GROUP BY operation,state"):
                stages[row[0]][row[1]] = row[2]
            oldest = db.execute("SELECT created_at FROM jobs WHERE state='queued' ORDER BY created_at LIMIT 1").fetchone()
            recent = [dict(row) for row in db.execute("SELECT id,operation,state,message,progress,created_at,updated_at FROM jobs ORDER BY updated_at DESC LIMIT 12")]
            count = db.execute("SELECT COUNT(*) FROM recordings").fetchone()[0]
        return {"stages": stages, "recordings": count, "oldest_pending_at": oldest[0] if oldest else None, "recent_jobs": recent}

    def mark_selected(self, recording_id, reason, policy, business_date):
        recording = self.recording(recording_id)
        with self.lock, self.connect() as db:
            db.execute("INSERT OR IGNORE INTO selections VALUES(?,?,?,?,?)", (recording["publication_id"], business_date, policy["version"], recording_id, reason))
            reasons = list(dict.fromkeys(recording["selection_reasons"] + [reason]))
            db.execute("UPDATE recordings SET selection_reasons=?,candidate=CASE WHEN ?='audio_quiet_candidate' THEN 1 ELSE candidate END WHERE id=?", (_json(reasons), reason, recording_id))

    def ready_for_sample(self, publication_id):
        with self.lock, self.connect() as db:
            pending = db.execute("SELECT COUNT(*) FROM import_files f JOIN imports i ON i.id=f.import_id WHERE i.publication_id=? AND f.state='pending'", (publication_id,)).fetchone()[0]
            active = db.execute("SELECT COUNT(*) FROM jobs j JOIN recording_jobs rj ON rj.job_id=j.id JOIN recordings r ON r.id=rj.recording_id WHERE r.publication_id=? AND j.operation='measure' AND j.state IN ('queued','running')", (publication_id,)).fetchone()[0]
            return pending == 0 and active == 0

    def measured_recordings(self, publication_id):
        with self.lock, self.connect() as db:
            return [self._row(row) for row in db.execute("SELECT * FROM recordings WHERE publication_id=? AND measurement_id IS NOT NULL ORDER BY id", (publication_id,))]

    def save_review(self, recording_id, bundle_id, publication_id, current_publication_id, state, reviewer, note):
        if state not in REVIEW_STATES or not reviewer.strip() or not note.strip():
            raise ValueError("Choose a supported review state and enter your reviewer label and factual note.")
        with self.lock, self.connect() as db:
            row = db.execute("SELECT publication_id,bundle_id FROM recordings WHERE id=?", (recording_id,)).fetchone()
            if not row:
                raise KeyError("Recording was not found.")
            if publication_id != current_publication_id or row["publication_id"] != publication_id or row["bundle_id"] != bundle_id:
                raise ValueError("The report or audio analysis changed. Reload its latest evidence before saving this review.")
            bundle = self.bundle(bundle_id)
            record = {"id": uuid.uuid4().hex, "recording_id": recording_id, "bundle_id": bundle_id,
                      "publication_id": publication_id, "state": state, "reviewer": reviewer.strip(), "note": note.strip(),
                      "timestamp": utc_now(), "basis": bundle}
            db.execute("INSERT INTO reviews VALUES(?,?,?,?,?,?)", (record["id"], recording_id, bundle_id, publication_id, _json(record), record["timestamp"]))
            return {key: value for key, value in record.items() if key != "basis"}

    def reviews(self, recording_id):
        with self.lock, self.connect() as db:
            records = [json.loads(row[0]) for row in db.execute("SELECT data FROM reviews WHERE recording_id=? ORDER BY created_at,id", (recording_id,))]
        return [{key: value for key, value in record.items() if key != "basis"} for record in records]

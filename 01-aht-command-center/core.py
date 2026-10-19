"""Local AHT V3 data engine: validated interval imports and weighted metrics."""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import sqlite3
import tempfile
import threading
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel


GOAL_SECONDS = 640.0
BUSINESS_ZONE = ZoneInfo("America/Mexico_City")
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
FILE_NAME = re.compile(
    r"^Calls_(\d{4}-\d{2}-\d{2})_(\d{4})_(\d{4}-\d{2}-\d{2})_(\d{4})_r(\d+)\.xlsx$",
    re.IGNORECASE,
)
HEADERS = (
    "Transaction ID", "Login ID", "Agent Name", "Supervisor", "Team", "Queue",
    "Start Date Time", "End Date Time", "Talk Time", "Hold Time", "Wrap Time",
    "Media", "Direction",
)
COMPONENTS = ("talk_seconds", "hold_seconds", "wrap_seconds")


class ImportProblem(ValueError):
    """The new source file is invalid or conflicts with active source data."""


def business_today() -> date:
    return datetime.now(BUSINESS_ZONE).date()


def _utc_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _as_datetime(value: Any, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time())
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        parsed = from_excel(value)
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError as exc:
            raise ImportProblem(f"Invalid {label}: {value!r}") from exc
    else:
        raise ImportProblem(f"Missing or invalid {label}")
    if parsed.tzinfo is not None:
        raise ImportProblem(f"{label} includes a timezone; confirm the export timezone first")
    return parsed


def _seconds(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ImportProblem(f"Invalid {label}")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ImportProblem(f"Missing or invalid {label}") from exc
    if not math.isfinite(result) or result < 0:
        raise ImportProblem(f"Negative or nonfinite {label}")
    return result


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _interval(original_name: str, start: str | None, end: str | None, revision: int | None):
    original_name = Path(original_name or "download.xlsx").name
    if not original_name.lower().endswith(".xlsx") or original_name.startswith("~$"):
        raise ImportProblem("Upload a completed .xlsx export")
    match = FILE_NAME.fullmatch(original_name)
    if match:
        from_name = (
            datetime.strptime(f"{match[1]} {match[2]}", "%Y-%m-%d %H%M"),
            datetime.strptime(f"{match[3]} {match[4]}", "%Y-%m-%d %H%M"),
            int(match[5]),
        )
    else:
        from_name = None
    if not start or not end:
        if from_name is None:
            raise ImportProblem("Enter the export interval start and end; call times cannot define coverage")
        window_start, window_end = from_name[:2]
    else:
        window_start = _as_datetime(start, "interval start")
        window_end = _as_datetime(end, "interval end")
    if window_start.second or window_start.microsecond or window_end.second or window_end.microsecond:
        raise ImportProblem("Interval endpoints must be on whole minutes")
    if window_end <= window_start:
        raise ImportProblem("Interval end must be later than start")
    if revision is None:
        revision = from_name[2] if from_name else 1
    if not isinstance(revision, int) or not 1 <= revision <= 9999:
        raise ImportProblem("Revision must be an integer from 1 to 9999")
    if from_name and from_name != (window_start, window_end, revision):
        raise ImportProblem("Entered interval/revision does not match the file name")
    canonical = (
        f"Calls_{window_start:%Y-%m-%d_%H%M}_"
        f"{window_end:%Y-%m-%d_%H%M}_r{revision:02d}.xlsx"
    )
    return original_name, window_start, window_end, revision, canonical


def _parse_excel(content: bytes, start: datetime, end: datetime):
    if not content.startswith(b"PK"):
        raise ImportProblem("The file is not a readable .xlsx workbook")
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:
        raise ImportProblem(f"Cannot open Excel export: {exc}") from exc
    try:
        if "Sheet1" not in workbook:
            raise ImportProblem("Missing Sheet1 in the export")
        rows = workbook["Sheet1"].iter_rows(values_only=True)
        header_row = next(rows, None)
        if header_row is None:
            raise ImportProblem("The export is empty")
        headings = [_text(cell) for cell in header_row]
        if len(headings) != len(set(headings)):
            raise ImportProblem("The export has duplicate column names")
        missing = [name for name in HEADERS if name not in headings]
        if missing:
            raise ImportProblem("Missing required columns: " + ", ".join(missing))
        positions = {name: headings.index(name) for name in HEADERS}
        accepted = []
        excluded = 0
        seen_in_file = {}
        for row_number, values in enumerate(rows, start=2):
            if not any(value is not None and _text(value) for value in values):
                continue
            record = {name: values[index] if index < len(values) else None for name, index in positions.items()}
            if _text(record["Media"]) != "Voice":
                excluded += 1
                continue
            transaction_id = _text(record["Transaction ID"])
            agent_id = _text(record["Login ID"])
            if not transaction_id or not agent_id:
                raise ImportProblem(f"Row {row_number}: Transaction ID and Login ID are required")
            started = _as_datetime(record["Start Date Time"], f"row {row_number} start")
            ended = _as_datetime(record["End Date Time"], f"row {row_number} end")
            if not start <= started < end:
                raise ImportProblem(f"Row {row_number}: call start is outside the declared export window")
            if ended < started:
                raise ImportProblem(f"Row {row_number}: end is before start")
            talk = _seconds(record["Talk Time"], f"row {row_number} talk seconds")
            hold = _seconds(record["Hold Time"], f"row {row_number} hold seconds")
            wrap = _seconds(record["Wrap Time"], f"row {row_number} wrap seconds")
            item = {
                "row_number": row_number,
                "transaction_id": transaction_id,
                "started_at": started.isoformat(sep=" ", timespec="seconds"),
                "ended_at": ended.isoformat(sep=" ", timespec="seconds"),
                "call_date": started.date().isoformat(),
                "agent_id": agent_id,
                "agent_name": _text(record["Agent Name"]) or agent_id,
                "supervisor": _text(record["Supervisor"]) or "Unassigned",
                "team": _text(record["Team"]),
                "queue": _text(record["Queue"]) or "Unknown",
                "talk_seconds": talk,
                "hold_seconds": hold,
                "wrap_seconds": wrap,
                "handle_seconds": talk + hold + wrap,
            }
            signature_values = [item[key] for key in (
                "agent_id", "supervisor", "team", "queue", "started_at", "ended_at",
                "talk_seconds", "hold_seconds", "wrap_seconds",
            )]
            item["signature"] = json.dumps(signature_values, ensure_ascii=False, separators=(",", ":"))
            previous = seen_in_file.get(transaction_id)
            if previous and previous != item["signature"]:
                raise ImportProblem(f"Row {row_number}: contradictory Transaction ID {transaction_id}")
            if previous:
                excluded += 1
                continue
            seen_in_file[transaction_id] = item["signature"]
            accepted.append(item)
        return accepted, excluded
    finally:
        workbook.close()


def _metrics(count: int | None, talk: float | None, hold: float | None, wrap: float | None, handle: float | None):
    count = int(count or 0)
    talk, hold, wrap, handle = (float(value or 0) for value in (talk, hold, wrap, handle))
    aht = handle / count if count else None
    gap = aht - GOAL_SECONDS if aht is not None else None
    return {
        "calls": count, "talk_seconds": talk, "hold_seconds": hold,
        "wrap_seconds": wrap, "handle_seconds": handle,
        "aht_seconds": aht, "gap_seconds": gap,
        "excess_minutes": max(0.0, handle - GOAL_SECONDS * count) / 60,
        "avg_talk_seconds": talk / count if count else None,
        "avg_hold_seconds": hold / count if count else None,
        "avg_wrap_seconds": wrap / count if count else None,
    }


class AHTStore:
    def __init__(self, data_dir: str | Path | None = None):
        self.data_dir = Path(data_dir or os.getenv("AHT_V3_DATA_DIR") or Path(__file__).parent / "data").resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir = self.data_dir / "History"
        self.history_dir.mkdir(exist_ok=True)
        self.db_path = self.data_dir / "aht.sqlite3"
        self._lock = threading.Lock()
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self):
        with closing(self._connect()) as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT OR IGNORE INTO meta(key,value) VALUES ('published_version','0');
                CREATE TABLE IF NOT EXISTS source_batches (
                    id INTEGER PRIMARY KEY, interval_start TEXT NOT NULL, interval_end TEXT NOT NULL,
                    revision INTEGER NOT NULL, original_name TEXT NOT NULL, canonical_name TEXT NOT NULL,
                    sha256 TEXT NOT NULL, source_path TEXT NOT NULL, received_at TEXT NOT NULL,
                    accepted_rows INTEGER NOT NULL, excluded_rows INTEGER NOT NULL,
                    UNIQUE(interval_start, interval_end, revision)
                );
                CREATE TABLE IF NOT EXISTS source_rows (
                    batch_id INTEGER NOT NULL REFERENCES source_batches(id), row_number INTEGER NOT NULL,
                    transaction_id TEXT NOT NULL, signature TEXT NOT NULL, call_date TEXT NOT NULL,
                    started_at TEXT NOT NULL, ended_at TEXT NOT NULL, agent_id TEXT NOT NULL,
                    agent_name TEXT NOT NULL, supervisor TEXT NOT NULL, team TEXT NOT NULL,
                    queue TEXT NOT NULL, talk_seconds REAL NOT NULL, hold_seconds REAL NOT NULL,
                    wrap_seconds REAL NOT NULL, handle_seconds REAL NOT NULL,
                    PRIMARY KEY(batch_id,row_number)
                );
                CREATE INDEX IF NOT EXISTS ix_source_transaction ON source_rows(transaction_id);
                CREATE TABLE IF NOT EXISTS accepted_calls (
                    transaction_id TEXT PRIMARY KEY, batch_id INTEGER NOT NULL, row_number INTEGER NOT NULL,
                    call_date TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT NOT NULL,
                    agent_id TEXT NOT NULL, agent_name TEXT NOT NULL, supervisor TEXT NOT NULL,
                    team TEXT NOT NULL, queue TEXT NOT NULL, talk_seconds REAL NOT NULL,
                    hold_seconds REAL NOT NULL, wrap_seconds REAL NOT NULL, handle_seconds REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_calls_date ON accepted_calls(call_date);
                CREATE INDEX IF NOT EXISTS ix_calls_agent_date ON accepted_calls(agent_id,call_date);
                CREATE TABLE IF NOT EXISTS daily_metrics (
                    call_date TEXT NOT NULL, agent_id TEXT NOT NULL, agent_name TEXT NOT NULL,
                    supervisor TEXT NOT NULL, team TEXT NOT NULL, queue TEXT NOT NULL,
                    calls INTEGER NOT NULL, talk_seconds REAL NOT NULL, hold_seconds REAL NOT NULL,
                    wrap_seconds REAL NOT NULL, handle_seconds REAL NOT NULL,
                    PRIMARY KEY(call_date,agent_id,supervisor,team,queue)
                );
                CREATE INDEX IF NOT EXISTS ix_daily_supervisor ON daily_metrics(supervisor,call_date);
                CREATE TABLE IF NOT EXISTS ingestion_runs (
                    id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, completed_at TEXT,
                    status TEXT NOT NULL, file_name TEXT NOT NULL, message TEXT NOT NULL DEFAULT '',
                    published_version INTEGER, accepted_rows INTEGER NOT NULL DEFAULT 0,
                    excluded_rows INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS recommendation_feedback (
                    evidence_id TEXT PRIMARY KEY, state TEXT NOT NULL, note TEXT NOT NULL,
                    reviewed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ai_cache (
                    published_version INTEGER NOT NULL, evidence_id TEXT NOT NULL,
                    model TEXT NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(published_version,evidence_id,model)
                );
            """)

    def _version(self, db):
        return int(db.execute("SELECT value FROM meta WHERE key='published_version'").fetchone()[0])

    def import_bytes(self, content: bytes, original_name: str, start: str | None = None,
                     end: str | None = None, revision: int | None = None) -> dict:
        if len(content) > MAX_UPLOAD_BYTES:
            raise ImportProblem("File exceeds the 25 MB local upload limit")
        original_name, window_start, window_end, revision, canonical = _interval(original_name, start, end, revision)
        digest = hashlib.sha256(content).hexdigest()
        with self._lock, closing(self._connect()) as db:
            run_id = db.execute(
                "INSERT INTO ingestion_runs(started_at,status,file_name) VALUES (?,?,?)",
                (_utc_now(), "validating", original_name),
            ).lastrowid
            destination = None
            created_destination = False
            try:
                existing = db.execute(
                    "SELECT sha256 FROM source_batches WHERE interval_start=? AND interval_end=? AND revision=?",
                    (window_start.isoformat(), window_end.isoformat(), revision),
                ).fetchone()
                if existing:
                    if existing["sha256"] != digest:
                        raise ImportProblem("This interval/revision already exists with different data; use a higher revision")
                    db.execute(
                        "UPDATE ingestion_runs SET status='duplicate',completed_at=?,message=?,published_version=? WHERE id=?",
                        (_utc_now(), "Exact file already published", self._version(db), run_id),
                    )
                    return {"status": "duplicate", "calls": self.total_calls(db), "published_version": self._version(db)}
                latest = db.execute(
                    "SELECT MAX(revision) FROM source_batches WHERE interval_start=? AND interval_end=?",
                    (window_start.isoformat(), window_end.isoformat()),
                ).fetchone()[0]
                if latest is not None and revision < latest:
                    raise ImportProblem(f"Revision {revision} is older than active r{latest:02d}")
                parsed, excluded = _parse_excel(content, window_start, window_end)
                incoming_demo = bool(parsed) and all(row["transaction_id"].startswith("DEMO-") for row in parsed)
                existing_demo = db.execute(
                    "SELECT COUNT(*) AS total, SUM(CASE WHEN transaction_id LIKE 'DEMO-%' THEN 1 ELSE 0 END) AS demo FROM accepted_calls"
                ).fetchone()
                if existing_demo["total"] and parsed and bool(existing_demo["demo"] == existing_demo["total"]) != incoming_demo:
                    raise ImportProblem("Synthetic demo and operational calls cannot share one database; use a clean data folder")
                folder = self.history_dir / window_start.strftime("%Y") / window_start.strftime("%m") / window_start.strftime("%d")
                destination = folder / canonical
                if destination.exists():
                    raise ImportProblem(f"History already contains {canonical}")
                db.execute("BEGIN IMMEDIATE")
                relative_path = destination.relative_to(self.data_dir).as_posix()
                batch_id = db.execute(
                    """INSERT INTO source_batches(interval_start,interval_end,revision,original_name,canonical_name,
                       sha256,source_path,received_at,accepted_rows,excluded_rows) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (window_start.isoformat(), window_end.isoformat(), revision, original_name, canonical,
                     digest, relative_path, _utc_now(), len(parsed), excluded),
                ).lastrowid
                db.executemany(
                    """INSERT INTO source_rows(batch_id,row_number,transaction_id,signature,call_date,
                       started_at,ended_at,agent_id,agent_name,supervisor,team,queue,talk_seconds,
                       hold_seconds,wrap_seconds,handle_seconds)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    [(batch_id, row["row_number"], row["transaction_id"], row["signature"], row["call_date"],
                      row["started_at"], row["ended_at"], row["agent_id"], row["agent_name"],
                      row["supervisor"], row["team"], row["queue"], row["talk_seconds"],
                      row["hold_seconds"], row["wrap_seconds"], row["handle_seconds"]) for row in parsed],
                )
                active_rows = db.execute("""
                    SELECT r.* FROM source_rows r JOIN source_batches b ON b.id=r.batch_id
                    JOIN (SELECT interval_start,interval_end,MAX(revision) AS revision
                          FROM source_batches GROUP BY interval_start,interval_end) latest
                    ON latest.interval_start=b.interval_start AND latest.interval_end=b.interval_end
                       AND latest.revision=b.revision
                    ORDER BY b.interval_start,b.id,r.row_number
                """).fetchall()
                unique = {}
                for row in active_rows:
                    prior = unique.get(row["transaction_id"])
                    if prior and prior["signature"] != row["signature"]:
                        raise ImportProblem(f"Contradictory active Transaction ID {row['transaction_id']}")
                    unique.setdefault(row["transaction_id"], row)
                db.execute("DELETE FROM accepted_calls")
                db.executemany(
                    """INSERT INTO accepted_calls(transaction_id,batch_id,row_number,call_date,started_at,
                       ended_at,agent_id,agent_name,supervisor,team,queue,talk_seconds,hold_seconds,
                       wrap_seconds,handle_seconds) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    [(r["transaction_id"], r["batch_id"], r["row_number"], r["call_date"], r["started_at"],
                      r["ended_at"], r["agent_id"], r["agent_name"], r["supervisor"], r["team"],
                      r["queue"], r["talk_seconds"], r["hold_seconds"], r["wrap_seconds"],
                      r["handle_seconds"]) for r in unique.values()],
                )
                db.execute("DELETE FROM daily_metrics")
                db.execute("""INSERT INTO daily_metrics(call_date,agent_id,agent_name,supervisor,team,queue,
                    calls,talk_seconds,hold_seconds,wrap_seconds,handle_seconds)
                    SELECT call_date,agent_id,MAX(agent_name),supervisor,team,queue,COUNT(*),
                           SUM(talk_seconds),SUM(hold_seconds),SUM(wrap_seconds),SUM(handle_seconds)
                    FROM accepted_calls GROUP BY call_date,agent_id,supervisor,team,queue""")
                check = db.execute("""SELECT (SELECT COUNT(*) FROM accepted_calls) AS detail_calls,
                    (SELECT COALESCE(SUM(calls),0) FROM daily_metrics) AS daily_calls,
                    (SELECT COALESCE(SUM(handle_seconds-talk_seconds-hold_seconds-wrap_seconds),0)
                     FROM daily_metrics) AS difference""").fetchone()
                if check["detail_calls"] != check["daily_calls"] or abs(check["difference"]) > 0.00001:
                    raise ImportProblem("Call or component reconciliation failed")
                version = self._version(db) + 1
                db.execute("UPDATE meta SET value=? WHERE key='published_version'", (str(version),))
                folder.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(mode="wb", dir=folder, prefix=".incoming-", delete=False) as temp:
                    temp.write(content)
                    temp.flush()
                    os.fsync(temp.fileno())
                    temporary_path = Path(temp.name)
                try:
                    os.replace(temporary_path, destination)
                    created_destination = True
                finally:
                    temporary_path.unlink(missing_ok=True)
                db.execute(
                    """UPDATE ingestion_runs SET status='published',completed_at=?,message=?,published_version=?,
                       accepted_rows=?,excluded_rows=? WHERE id=?""",
                    (_utc_now(), "Validated and published", version, len(parsed), excluded, run_id),
                )
                db.commit()
                return {"status": "published", "batch_id": batch_id, "accepted_rows": len(parsed),
                        "excluded_rows": excluded, "calls": len(unique), "published_version": version,
                        "history_path": relative_path}
            except Exception as exc:
                if db.in_transaction:
                    db.rollback()
                if created_destination and destination is not None:
                    destination.unlink(missing_ok=True)
                db.execute(
                    "UPDATE ingestion_runs SET status='failed',completed_at=?,message=?,published_version=? WHERE id=?",
                    (_utc_now(), str(exc), self._version(db), run_id),
                )
                if isinstance(exc, ImportProblem):
                    raise
                raise ImportProblem(f"Import failed: {exc}") from exc

    def total_calls(self, db=None):
        if db is not None:
            return db.execute("SELECT COUNT(*) FROM accepted_calls").fetchone()[0]
        with closing(self._connect()) as connection:
            return self.total_calls(connection)

    def status(self):
        with closing(self._connect()) as db:
            count = self.total_calls(db)
            demo = db.execute("SELECT COUNT(*) FROM accepted_calls WHERE transaction_id LIKE 'DEMO-%'").fetchone()[0]
            latest = db.execute("""SELECT MAX(interval_end) FROM source_batches b
                WHERE revision=(SELECT MAX(revision) FROM source_batches x
                                WHERE x.interval_start=b.interval_start AND x.interval_end=b.interval_end)""").fetchone()[0]
            latest_call = db.execute("SELECT MAX(call_date) FROM accepted_calls").fetchone()[0]
            windows = db.execute("""SELECT interval_start,interval_end,accepted_rows FROM source_batches b
                WHERE revision=(SELECT MAX(revision) FROM source_batches x
                                WHERE x.interval_start=b.interval_start AND x.interval_end=b.interval_end)
                ORDER BY interval_start""").fetchall()
            gaps, overlaps, empty = [], [], []
            previous_end = None
            for window in windows:
                start, end = window["interval_start"], window["interval_end"]
                if previous_end and start[:10] == previous_end[:10]:
                    if start > previous_end:
                        gaps.append({"from": previous_end, "to": start})
                    elif start < previous_end:
                        overlaps.append({"from": start, "to": previous_end})
                if window["accepted_rows"] == 0:
                    empty.append({"from": start, "to": end})
                previous_end = max(previous_end, end) if previous_end else end
            last_run = db.execute("SELECT * FROM ingestion_runs ORDER BY id DESC LIMIT 1").fetchone()
            return {
                "published_version": self._version(db), "total_calls": count,
                "data_mode": "empty" if not count else "synthetic demo" if demo == count else "mixed" if demo else "operational",
                "latest_interval_end": latest, "latest_call_date": latest_call,
                "last_run": dict(last_run) if last_run else None,
                "coverage": {"observed_gaps": gaps[-20:], "overlaps": overlaps[-20:],
                             "empty_windows": empty[-20:], "active_windows": len(windows)},
                "business_today": business_today().isoformat(),
                "ai_configured": bool(os.getenv("AZURE_OPENAI_ENDPOINT") and os.getenv("AZURE_OPENAI_API_KEY")),
            }

    @staticmethod
    def _where(start: str, end: str, supervisor=None, agent=None, queue=None):
        clauses = ["call_date>=?", "call_date<=?"]
        args: list[Any] = [start, end]
        for column, value in (("supervisor", supervisor), ("agent_id", agent), ("queue", queue)):
            if value:
                clauses.append(f"{column}=?")
                args.append(value)
        return " AND ".join(clauses), args

    def _aggregate(self, db, start: str, end: str, supervisor=None, agent=None, queue=None):
        where, args = self._where(start, end, supervisor, agent, queue)
        row = db.execute(f"""SELECT COALESCE(SUM(calls),0) AS calls,
            COALESCE(SUM(talk_seconds),0) AS talk, COALESCE(SUM(hold_seconds),0) AS hold,
            COALESCE(SUM(wrap_seconds),0) AS wrap, COALESCE(SUM(handle_seconds),0) AS handle
            FROM daily_metrics WHERE {where}""", args).fetchone()
        return _metrics(row["calls"], row["talk"], row["hold"], row["wrap"], row["handle"])

    def dashboard(self, report_date: str | None = None, supervisor=None, agent=None, queue=None,
                  rank_period: str = "today"):
        day = date.fromisoformat(report_date) if report_date else business_today()
        if rank_period not in ("today", "yesterday", "mtd"):
            raise ValueError("rank_period must be today, yesterday, or mtd")
        yesterday = day - timedelta(days=1)
        month_start = day.replace(day=1)
        periods = {
            "today": (day.isoformat(), day.isoformat()),
            "yesterday": (yesterday.isoformat(), yesterday.isoformat()),
            "mtd": (month_start.isoformat(), day.isoformat()),
        }
        with closing(self._connect()) as db:
            cards = {key: self._aggregate(db, *window, supervisor, agent, queue)
                     for key, window in periods.items()}
            where, args = self._where(*periods[rank_period], supervisor, agent, queue)
            rankings = {}
            for kind, group in (("agents", "agent_id,supervisor"), ("supervisors", "supervisor")):
                rows = db.execute(f"""SELECT {group}, MAX(agent_name) AS agent_name,
                    SUM(calls) AS calls, SUM(talk_seconds) AS talk, SUM(hold_seconds) AS hold,
                    SUM(wrap_seconds) AS wrap, SUM(handle_seconds) AS handle
                    FROM daily_metrics WHERE {where} GROUP BY {group}""", args).fetchall()
                items = []
                for row in rows:
                    item = dict(row)
                    item.update(_metrics(row["calls"], row["talk"], row["hold"], row["wrap"], row["handle"]))
                    items.append(item)
                items.sort(key=lambda item: (item["excess_minutes"], item["gap_seconds"] or -1e9, item["calls"]), reverse=True)
                rankings[kind] = items
            history_where, history_args = self._where((day - timedelta(days=29)).isoformat(), day.isoformat(), supervisor, agent, queue)
            history_rows = db.execute(f"""SELECT call_date, SUM(calls) AS calls, SUM(talk_seconds) AS talk,
                SUM(hold_seconds) AS hold, SUM(wrap_seconds) AS wrap, SUM(handle_seconds) AS handle
                FROM daily_metrics WHERE {history_where} GROUP BY call_date ORDER BY call_date""", history_args).fetchall()
            history = [{"date": row["call_date"], **_metrics(row["calls"], row["talk"], row["hold"], row["wrap"], row["handle"])}
                       for row in history_rows]
            queues = db.execute(f"""SELECT queue,SUM(calls) AS calls,SUM(talk_seconds) AS talk,
                SUM(hold_seconds) AS hold,SUM(wrap_seconds) AS wrap,SUM(handle_seconds) AS handle
                FROM daily_metrics WHERE {where} GROUP BY queue ORDER BY handle DESC""", args).fetchall()
            queue_rows = [{"queue": row["queue"], **_metrics(row["calls"], row["talk"], row["hold"], row["wrap"], row["handle"])}
                          for row in queues]
            return {
                "report_date": day.isoformat(), "rank_period": rank_period,
                "goal_seconds": GOAL_SECONDS, "cards": cards, "rankings": rankings,
                "history": history, "queues": queue_rows,
                "filters": {"supervisors": [r[0] for r in db.execute("SELECT DISTINCT supervisor FROM daily_metrics ORDER BY supervisor")],
                            "agents": [dict(r) for r in db.execute("SELECT agent_id,MAX(agent_name) AS agent_name FROM daily_metrics GROUP BY agent_id ORDER BY agent_name")],
                            "queues": [r[0] for r in db.execute("SELECT DISTINCT queue FROM daily_metrics ORDER BY queue")]},
                "published_version": self._version(db),
                "latest_interval_end": db.execute("SELECT MAX(interval_end) FROM source_batches").fetchone()[0],
            }

    def recommendations(self, report_date: str | None = None, supervisor=None, rank_period: str = "today"):
        day = date.fromisoformat(report_date) if report_date else business_today()
        if rank_period not in ("today", "mtd"):
            raise ValueError("Recommendations support today or mtd")
        start = day.isoformat() if rank_period == "today" else day.replace(day=1).isoformat()
        baseline_start = (day - timedelta(days=28)).isoformat()
        baseline_end = (day - timedelta(days=1)).isoformat()
        with closing(self._connect()) as db:
            where, args = self._where(start, day.isoformat(), supervisor=supervisor)
            agent_rows = db.execute(f"""SELECT agent_id,MAX(agent_name) AS agent_name,supervisor,
                SUM(calls) AS calls,SUM(talk_seconds) AS talk,SUM(hold_seconds) AS hold,
                SUM(wrap_seconds) AS wrap,SUM(handle_seconds) AS handle
                FROM daily_metrics WHERE {where} GROUP BY agent_id,supervisor""", args).fetchall()
            version = self._version(db)
            results = []
            for row in agent_rows:
                performance = _metrics(row["calls"], row["talk"], row["hold"], row["wrap"], row["handle"])
                if performance["gap_seconds"] is None or performance["gap_seconds"] <= 0:
                    continue
                evidence_id = f"metric-v{version}-{day.isoformat()}-{rank_period}-{row['agent_id']}-{hashlib.sha1(row['supervisor'].encode()).hexdigest()[:6]}"
                item = {"evidence_id": evidence_id, "agent_id": row["agent_id"],
                        "agent_name": row["agent_name"], "supervisor": row["supervisor"],
                        "period": rank_period, "date": day.isoformat(), **performance}
                if performance["calls"] < 20:
                    item.update({"status": "insufficient_sample", "reason": "Fewer than 20 calls in this period"})
                    results.append(item)
                    continue
                mixes = db.execute("""SELECT queue,SUM(calls) AS calls FROM daily_metrics
                    WHERE call_date>=? AND call_date<=? AND agent_id=? AND supervisor=?
                    GROUP BY queue""", (start, day.isoformat(), row["agent_id"], row["supervisor"])).fetchall()
                comparison = {key: 0.0 for key in COMPONENTS}
                comparison_calls = 0
                insufficient_queue = None
                for mix in mixes:
                    benchmark = db.execute("""SELECT COALESCE(SUM(calls),0) AS calls,
                        COALESCE(SUM(talk_seconds),0) AS talk_seconds,
                        COALESCE(SUM(hold_seconds),0) AS hold_seconds,
                        COALESCE(SUM(wrap_seconds),0) AS wrap_seconds
                        FROM daily_metrics WHERE call_date>=? AND call_date<=? AND queue=? AND agent_id<>?""",
                        (baseline_start, baseline_end, mix["queue"], row["agent_id"])).fetchone()
                    if benchmark["calls"] < 100:
                        insufficient_queue = mix["queue"]
                        break
                    comparison_calls += benchmark["calls"]
                    for component in COMPONENTS:
                        comparison[component] += mix["calls"] / performance["calls"] * benchmark[component] / benchmark["calls"]
                if insufficient_queue:
                    item.update({"status": "insufficient_baseline", "reason": f"Not enough prior same-queue calls for {insufficient_queue}"})
                    results.append(item)
                    continue
                differences = {component: performance[f"avg_{component.replace('_seconds','')}_seconds"] - comparison[component]
                               for component in COMPONENTS}
                driver = max(differences, key=differences.get)
                driver_name = driver.replace("_seconds", "")
                actions = {
                    "talk": "Review a permitted call sample for call structure and queue complexity; test a focused coaching example without rushing customers.",
                    "hold": "Review hold reasons and knowledge access with the supervisor; test a quick-reference or escalation path.",
                    "wrap": "Review the after-call note workflow and approved templates, then check quality alongside AHT.",
                }
                if differences[driver] <= 0:
                    driver_name = "queue-wide"
                    action = "Review the queue's shared process and policy friction before assigning individual coaching."
                else:
                    action = actions[driver_name]
                item.update({
                    "status": "ready", "driver": driver_name,
                    "driver_difference_seconds": max(0.0, differences[driver]),
                    "comparison_calls": comparison_calls,
                    "comparison_component_seconds": comparison,
                    "observation": (f"{row['agent_name']} averaged {performance['aht_seconds']:.1f}s over "
                                    f"{performance['calls']} calls, {performance['gap_seconds']:+.1f}s to goal."),
                    "recommended_action": action,
                    "caveat": "The component difference is a comparison, not proof of cause or guaranteed savings.",
                })
                feedback = db.execute("SELECT state,note,reviewed_at FROM recommendation_feedback WHERE evidence_id=?", (evidence_id,)).fetchone()
                if feedback:
                    item["feedback"] = dict(feedback)
                results.append(item)
            results.sort(key=lambda item: item["excess_minutes"], reverse=True)
            return {"published_version": version, "report_date": day.isoformat(), "period": rank_period,
                    "recommendations": results}

    def review_recommendation(self, evidence_id: str, state: str, note: str):
        if state not in ("accepted", "rejected", "needs_review"):
            raise ValueError("state must be accepted, rejected, or needs_review")
        if len(note) > 1000:
            raise ValueError("Feedback note is too long")
        match = re.match(r"^metric-v(\d+)-(\d{4}-\d{2}-\d{2})-(today|mtd)-", evidence_id)
        if not match or int(match[1]) != self.status()["published_version"]:
            raise ValueError("Evidence ID is not from the current published report")
        current = self.recommendations(match[2], rank_period=match[3])["recommendations"]
        if not any(row["evidence_id"] == evidence_id and row["status"] == "ready" for row in current):
            raise ValueError("Evidence ID is not a current reviewable recommendation")
        with closing(self._connect()) as db:
            db.execute("""INSERT INTO recommendation_feedback(evidence_id,state,note,reviewed_at)
                VALUES (?,?,?,?) ON CONFLICT(evidence_id) DO UPDATE SET
                state=excluded.state,note=excluded.note,reviewed_at=excluded.reviewed_at""",
                (evidence_id, state, note, _utc_now()))
        return {"evidence_id": evidence_id, "state": state, "note": note}

    def recent_runs(self, limit=20):
        with closing(self._connect()) as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM ingestion_runs ORDER BY id DESC LIMIT ?", (min(max(limit, 1), 100),)
            )]

    def cached_ai(self, version: int, evidence_id: str, model: str):
        with closing(self._connect()) as db:
            row = db.execute("SELECT result_json FROM ai_cache WHERE published_version=? AND evidence_id=? AND model=?",
                             (version, evidence_id, model)).fetchone()
            return json.loads(row[0]) if row else None

    def save_ai(self, version: int, evidence_id: str, model: str, result: dict):
        with closing(self._connect()) as db:
            db.execute("INSERT OR REPLACE INTO ai_cache VALUES (?,?,?,?,?)",
                       (version, evidence_id, model, json.dumps(result), _utc_now()))

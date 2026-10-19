"""Recording CSV validation and explicit, publication-bound call links.

This module deliberately imports no optional audio packages.
"""
from __future__ import annotations

import csv
import io
import math
from datetime import datetime
from pathlib import Path

from .store import safe_relative

MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_RECORDINGS = 10000
MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024
SUPPORTED_SUFFIXES = {".wav", ".mp3"}


def _seconds(value: str, field: str):
    if not value.strip():
        return None
    try:
        result = float(value)
    except ValueError:
        raise ValueError(f"{field} must be a nonnegative number") from None
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{field} must be a nonnegative number")
    return result


def _channel(value: str, field: str):
    if not value.strip():
        return None
    if not value.isdigit():
        raise ValueError(f"{field} uses zero-based channel numbers")
    return int(value)


def parse_csv(content: bytes, dataset: dict, publication_id: str) -> dict:
    """Retain unresolved links as issues; never guess from names or nearest time."""
    if len(content) > MAX_CSV_BYTES:
        raise ValueError("The recording CSV must be smaller than 5 MB.")
    if content.startswith((b'PK\x03\x04', b'RIFF', b'RF64', b'ID3')):
        raise ValueError('This file is not a recording map CSV. Select the Excel call folder and audio folder; recordings.csv is optional inside the audio folder.')
    try:
        if content.startswith((b'\xff\xfe', b'\xfe\xff')):
            text = content.decode('utf-16')
        else:
            try:
                text = content.decode('utf-8-sig')
            except UnicodeDecodeError:
                text = content.decode('cp1252')
    except UnicodeDecodeError:
        raise ValueError('The recording map cannot be read. Supported formats are UTF-8, Excel UTF-16 and Windows CSV.') from None
    if '\x00' in text or any(ord(char) < 32 and char not in '\r\n\t' for char in text):
        raise ValueError('This is not a readable text CSV. Choose the call exports folder and the recordings folder.')
    delimiter = ','
    if text.lower().startswith('sep='):
        first, _, text = text.partition('\n')
        delimiter = first.strip()[4:]
        if delimiter not in {',', ';', '\t'}:
            raise ValueError('Use comma, semicolon or tab separated CSV.')
    else:
        try:
            delimiter = csv.Sniffer().sniff(text[:4096], delimiters=',;\t').delimiter
        except csv.Error:
            pass
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=delimiter)
    if reader.fieldnames:
        reader.fieldnames = [name.strip().lower() for name in reader.fieldnames]
    required = {"recording_file", "call_id", "call_id_type", "recording_scope"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError("CSV needs recording_file, call_id, call_id_type and recording_scope columns.")
    transactions = {str(row["transaction_id"]): row for row in dataset.get("transactions", [])}
    connections = {}
    for row in transactions.values():
        connections.setdefault(str(row["connection_id"]), []).append(row)
    files, issues = {}, []
    for number, row in enumerate(reader, 2):
        if number > MAX_RECORDINGS + 1:
            raise ValueError("Import at most 10,000 CSV rows per batch; split larger batches.")
        if not any(str(value or "").strip() for value in row.values()):
            continue
        filename = str(row.get("recording_file") or "").strip()
        try:
            relative = safe_relative(filename)
            filename = relative.as_posix()
            if relative.suffix.lower() not in SUPPORTED_SUFFIXES:
                raise ValueError("Initial recording import accepts WAV and MP3 files")
            if None in row:
                raise ValueError("CSV row has more cells than its header")
            identifier = str(row.get("call_id") or "").strip()
            kind = str(row.get("call_id_type") or "").strip()
            scope = str(row.get("recording_scope") or "").strip()
            if not identifier:
                raise ValueError("call_id is required and must be text")
            if kind not in {"transaction", "connection"}:
                raise ValueError("call_id_type must be transaction or connection")
            if scope not in {"transaction_leg", "whole_connection", "partial"}:
                raise ValueError("recording_scope must be transaction_leg, whole_connection or partial")
            start = _seconds(str(row.get("audio_start_seconds") or ""), "audio_start_seconds")
            end = _seconds(str(row.get("audio_end_seconds") or ""), "audio_end_seconds")
            if end is not None and end <= (start or 0):
                raise ValueError("audio_end_seconds must exceed audio_start_seconds")
            wall_clock = str(row.get("recording_start_at") or "").strip()
            if wall_clock:
                timestamp = datetime.fromisoformat(wall_clock.replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    raise ValueError("recording_start_at requires a timezone offset")
            layout = str(row.get("channel_layout") or "unknown").strip()
            if layout not in {"mono", "separate_roles", "unknown"}:
                raise ValueError("channel_layout must be mono, separate_roles or unknown")
            agent_channel = _channel(str(row.get("agent_channel") or ""), "agent_channel")
            customer_channel = _channel(str(row.get("customer_channel") or ""), "customer_channel")
            if layout == "separate_roles" and (agent_channel is None or customer_channel is None or agent_channel == customer_channel):
                raise ValueError("Separate roles require distinct verified agent_channel and customer_channel")
            if layout != "separate_roles" and (agent_channel is not None or customer_channel is not None):
                raise ValueError("Channel roles require channel_layout=separate_roles")
            matched = [transactions[identifier]] if kind == "transaction" and identifier in transactions else connections.get(identifier, []) if kind == "connection" else []
            link_state = "matched" if matched else "unmatched"
            message = None
            if not matched:
                message = "Call ID was not found in the selected workbook publication."
            elif kind == "connection" and len(matched) > 1 and scope != "whole_connection":
                link_state = "ambiguous"
                message = "Connection contains several transaction legs; supply a transaction ID and explicit audio span."
            elif scope == "whole_connection":
                link_state = "context"
                message = "Whole-connection audio is context; its quiet duration is not assigned to each agent."
            link = {"publication_id": publication_id, "call_id": identifier, "call_id_type": kind,
                    "recording_scope": scope, "recording_start_at": wall_clock or None,
                    "audio_start_seconds": start, "audio_end_seconds": end,
                    "channel_layout": layout, "agent_channel": agent_channel, "customer_channel": customer_channel,
                    "state": link_state, "issue": message, "csv_row": number,
                    "transaction_ids": [str(item["transaction_id"]) for item in matched],
                    "agent_ids": sorted({str(item["agent_id"]) for item in matched}),
                    "business_dates": sorted({item["business_date"] for item in matched}),
                    "expected_duration_seconds": matched[0]["duration_seconds"] if len(matched) == 1 else None}
            options = {"start_seconds": start or 0, "end_seconds": end, "recording_scope": scope, "channel_layout": layout,
                       "agent_channel": agent_channel, "customer_channel": customer_channel}
            previous = files.get(filename.casefold())
            if previous and (previous["recording_file"] != filename or previous["options"] != options):
                raise ValueError("Repeated recording path has conflicting casing, scope offsets or channel settings")
            entry = files.setdefault(filename.casefold(), {"recording_file": filename, "options": options, "links": []})
            if link not in entry["links"]:
                entry["links"].append(link)
            if message:
                issues.append({"file": filename, "row": number, "code": link_state, "message": message})
        except (ValueError, TypeError) as exc:
            issues.append({"file": filename, "row": number, "code": "invalid_csv_row", "message": str(exc)})
    if not files:
        raise ValueError("The CSV has no valid recording paths. Fix its rows before uploading audio.")
    return {"files": list(files.values()), "issues": issues}


def folder_csv(paths):
    """An exact filename stem is an explicit candidate ID, never a time guess.

    Unknown names are retained as unmatched through normal CSV validation.
    Default partial/unknown roles avoids claiming full coverage or speakers.
    """
    if not isinstance(paths, list) or not paths or len(paths) > MAX_RECORDINGS:
        raise ValueError('Select an audio folder with 1–10,000 WAV or MP3 recordings.')
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['recording_file', 'call_id', 'call_id_type', 'recording_scope', 'channel_layout'])
    seen = set()
    for value in sorted(paths):
        if not isinstance(value, str):
            raise ValueError('Recording paths must be text.')
        path = safe_relative(value)
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise ValueError('Audio folder import accepts WAV and MP3 recordings.')
        if path.as_posix().casefold() in seen:
            raise ValueError('The audio folder contains duplicate recording paths.')
        seen.add(path.as_posix().casefold())
        writer.writerow([path.as_posix(), path.stem, 'transaction', 'partial', 'unknown'])
    return output.getvalue().encode('utf-8')


def validate_signature(path: Path) -> None:
    """Reject obvious non-audio input; full decode validation is a queued stage."""
    with path.open("rb") as stream:
        header = stream.read(16)
    if path.suffix.lower() == ".wav":
        valid = len(header) >= 12 and header[:4] in {b"RIFF", b"RF64"} and header[8:12] == b"WAVE"
    else:
        valid = header.startswith(b"ID3") or (len(header) >= 2 and header[0] == 255 and header[1] & 224 == 224)
    if not valid:
        raise ValueError("File content does not match a WAV/MP3 recording; original workbook data was preserved.")

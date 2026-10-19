"""Lossless normalized persistence with shared native cell descriptors.

The public dataset/API stays unchanged. On disk, each source's complete
raw_cells mapping is represented by an ordered header schema and cell-pool IDs.
Original values, Python/Excel types, number formats and source locators survive.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

CACHE_VERSION = "cells-pool-1"
_LOCATOR_KEYS = ("file", "sha256", "sheet", "row", "import_id")
_SHARED_STRINGS = {"file", "sha256", "sheet", "import_id", "agent_id", "login_id",
    "call_type", "business_date", "queue_code", "started_at", "ended_at", "supervisor",
    "manager", "name", "status", "parser_version", "type", "number_format"}


def _freeze(value):
    if isinstance(value, dict):
        return (dict, tuple((key, _freeze(item)) for key, item in sorted(value.items())))
    if isinstance(value, list):
        return (list, tuple(_freeze(item) for item in value))
    return type(value), value


def save_dataset(path: Path, dataset: dict) -> None:
    """Atomically stream a compact cache without mutating the caller's dataset."""
    cells, cell_keys, cell_objects, schemas, schema_keys = [], {}, {}, [], {}

    def encode_raw(raw):
        headers = tuple(raw)
        schema_id = schema_keys.get(headers)
        if schema_id is None:
            schema_id = len(schemas)
            schema_keys[headers] = schema_id
            schemas.append(headers)
        ids = []
        for descriptor in raw.values():
            object_id = id(descriptor)
            cell_id = cell_objects.get(object_id)
            if cell_id is None:
                key = _freeze(descriptor)
                cell_id = cell_keys.get(key)
                if cell_id is None:
                    cell_id = len(cells)
                    cells.append(descriptor)
                    cell_keys[key] = cell_id
                cell_objects[object_id] = cell_id
            ids.append(cell_id)
        return {"schema": schema_id, "cells": ids}

    def encode(value):
        if isinstance(value, dict):
            if "raw_cells" in value and all(key in value for key in _LOCATOR_KEYS):
                return {key: encode_raw(item) if key == "raw_cells" else encode(item)
                    for key, item in value.items()}
            return {key: encode(item) for key, item in value.items()}
        if isinstance(value, list):
            return [encode(item) for item in value]
        return value

    encoded = encode(dataset)
    # Serialization does not need the lookup maps, which can otherwise retain
    # a second copy of every unique descriptor's hash key until the final write.
    cell_keys.clear()
    cell_objects.clear()
    schema_keys.clear()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            def write(value):
                # The C encoder handles one bounded record at a time. This
                # avoids millions of individual Python token writes and avoids
                # materializing the complete cache as a second giant string.
                stream.write(json.dumps(value, ensure_ascii=False,
                    separators=(",", ":"), allow_nan=False))

            def array(records):
                stream.write("[")
                for index, record in enumerate(records):
                    if index:
                        stream.write(",")
                    write(record)
                stream.write("]")

            stream.write('{"cache_format":')
            write(CACHE_VERSION)
            stream.write(',"schemas":')
            array(schemas)
            stream.write(',"cells":')
            array(cells)
            stream.write(',"dataset":{')
            for index, (key, value) in enumerate(encoded.items()):
                if index:
                    stream.write(",")
                write(key)
                stream.write(":")
                array(value) if isinstance(value, list) else write(value)
            stream.write("}}")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_dataset(path: Path) -> dict:
    """Restore the original mappings; also read existing plain JSON publications."""
    with Path(path).open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload, dict):
        raise ValueError("Normalized cache must contain an object")
    if "cache_format" not in payload:
        return payload  # Legacy normalized caches remain readable after restart.
    if payload["cache_format"] != CACHE_VERSION:
        raise ValueError("Unsupported normalized cache version")
    cells, schemas, dataset = payload.get("cells"), payload.get("schemas"), payload.get("dataset")
    if not isinstance(cells, list) or not isinstance(schemas, list) or not isinstance(dataset, dict):
        raise ValueError("Invalid normalized cache structure")
    if any(not isinstance(schema, list) or any(not isinstance(header, str) for header in schema)
        or len(set(schema)) != len(schema) for schema in schemas):
        raise ValueError("Invalid normalized header schema")
    if any(not isinstance(cell, dict) for cell in cells):
        raise ValueError("Invalid normalized cell descriptor")
    strings = {}

    def share_string(key, value):
        if key in _SHARED_STRINGS and isinstance(value, str):
            return strings.setdefault(value, value)
        return value

    for cell in cells:
        for key in ("type", "number_format"):
            if key in cell:
                cell[key] = share_string(key, cell[key])

    def decode(value):
        if isinstance(value, dict):
            if "raw_cells" in value and all(key in value for key in _LOCATOR_KEYS):
                raw = value["raw_cells"]
                if not isinstance(raw, dict):
                    raise ValueError("Invalid normalized source cells")
                schema_id, ids = raw.get("schema"), raw.get("cells")
                if isinstance(schema_id, bool) or not isinstance(schema_id, int) or not 0 <= schema_id < len(schemas):
                    raise ValueError("Invalid normalized schema reference")
                headers = schemas[schema_id]
                if not isinstance(ids, list) or len(ids) != len(headers) or any(
                    isinstance(cell_id, bool) or not isinstance(cell_id, int) or not 0 <= cell_id < len(cells)
                    for cell_id in ids):
                    raise ValueError("Invalid normalized cell reference")
                value["raw_cells"] = dict(zip(headers, (cells[cell_id] for cell_id in ids)))
                for key in value:
                    if key != "raw_cells":
                        value[key] = share_string(key, value[key])
                        decode(value[key])
            else:
                for key in value:
                    value[key] = share_string(key, value[key])
                    decode(value[key])
        elif isinstance(value, list):
            for item in value:
                decode(item)

    decode(dataset)
    return dataset

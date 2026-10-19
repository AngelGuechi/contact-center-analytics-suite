"""Four cumulative, reproducible stages of the synthetic demonstration."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .fixtures import generate_demo
from .store import atomic_json


def replay_folder(root: Path, step: int) -> Path:
    if step not in {1, 2, 3, 4}:
        raise ValueError("Choose replay stage 1, 2, 3 or 4.")
    reference = root / "demo-input"
    if not (reference / "manifest.json").exists():
        generate_demo(reference)
    destination = root / "replay-input" / str(step)
    if (destination / "manifest.json").exists():
        return destination
    manifest = json.loads((reference / "manifest.json").read_text(encoding="utf-8"))
    day = manifest["report_date"]
    snapshot_limit = {1: "09:00:00", 2: "09:30:00", 3: "10:00:00", 4: "23:59:59"}[step]
    files = []
    for descriptor in manifest["files"]:
        if descriptor["kind"] == "tool2" and descriptor["business_date"] == day and step < 4:
            continue
        if descriptor["kind"] == "tool1":
            # Native demo descriptors use local ISO timestamps.
            clock = descriptor["captured_at"][11:19]
            if clock > snapshot_limit:
                continue
        files.append(descriptor)
    manifest["files"] = files
    if step < 4:
        manifest["complete_days"] = [date for date in manifest["complete_days"] if date != day]
    manifest["replay_stage"] = step
    destination.mkdir(parents=True, exist_ok=True)
    paths = [manifest["admin_file"], "incidents.json", *[entry["file"] for entry in files]]
    for relative in paths:
        source = reference / relative
        if source.exists():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    # Publish the manifest last; an interrupted preparation can be repeated.
    atomic_json(destination / "manifest.json", manifest)
    return destination

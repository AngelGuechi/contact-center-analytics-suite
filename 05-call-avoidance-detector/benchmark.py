r"""Reproducible local fixture benchmark; creates only runtime/benchmark outputs.

Run: .venv\Scripts\python.exe benchmark.py --scale 17
The source fixture is unchanged; each worker has an isolated process/store.
"""
from __future__ import annotations
import argparse
import ctypes
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time as clock
from datetime import time, timedelta
from pathlib import Path

from openpyxl import load_workbook

PROJECT = Path(__file__).resolve().parent
BASE = PROJECT / "runtime" / "benchmark"


def peak_memory_mb():
    if os.name == "nt":
        class Counters(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        ctypes.windll.kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        query = ctypes.windll.psapi.GetProcessMemoryInfo
        query.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        if query(ctypes.windll.kernel32.GetCurrentProcess(),
                ctypes.byref(counters), counters.cb):
            return round(counters.PeakWorkingSetSize / 1024 ** 2, 1)
    else:
        import resource
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 ** 2 if sys.platform == "darwin" else 1024), 1)
    return None


def physical_ram_gb():
    if os.name != "nt":
        return None
    class Memory(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
            *[(field, ctypes.c_ulonglong) for field in ("total_physical", "available_physical",
                "total_pagefile", "available_pagefile", "total_virtual", "available_virtual", "extended")]]
    memory = Memory()
    memory.length = ctypes.sizeof(memory)
    return round(memory.total_physical / 1024 ** 3, 1) if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)) else None


def scale_inputs(destination, factor):
    shutil.copytree(PROJECT / "fixtures", destination)
    for path in sorted(destination.rglob("*.xlsx")):
        if path.name.startswith("tool2_"):
            book = load_workbook(path)
            sheet = book.active
            originals = [[(cell.value, cell.number_format) for cell in row]
                for row in sheet.iter_rows(min_row=2) if row[0].value is not None]
            sheet.delete_rows(2, sheet.max_row)
            row_number = 1
            for replicate in range(factor):
                for original in originals:
                    values = [item[0] for item in original]
                    values[0] = int(values[0]) + replicate * 1000000
                    values[5] = f"B{replicate:02d}{str(values[5])[-13:]}"
                    sheet.append(values)
                    row_number += 1
                    for index, (_, number_format) in enumerate(original, 1):
                        sheet.cell(row_number, index).number_format = number_format
            book.save(path)
            book.close()
        elif path.name.startswith("tool1_"):
            book = load_workbook(path)
            sheet = book["LiveAgentData"]
            for row in sheet.iter_rows(min_row=2):
                if row[0].value is None or not str(row[0].value).startswith("00"):
                    continue
                for column in (17, 20, 21, 22, 24):
                    value = row[column - 1].value
                    if isinstance(value, time):
                        value = timedelta(hours=value.hour, minutes=value.minute, seconds=value.second,
                            microseconds=value.microsecond)
                    row[column - 1].value = value * factor
            book.save(path)
            book.close()
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["benchmark_replication_factor"] = factor
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def worker(mode, source, store_path):
    from avoidance.store import LocalStore
    started = clock.perf_counter()
    store = LocalStore(store_path)
    if mode in ("cold", "warm"):
        report = store.import_folder(source)
    else:
        report = store.report()
    elapsed = clock.perf_counter() - started
    ana = next(row for row in report["daily"]["slices"] if row["agent_id"] == "123654")
    samples = []
    for _ in range(25):
        started = clock.perf_counter()
        store.evidence(ana["evidence_id"], page=1, page_size=100)
        samples.append((clock.perf_counter() - started) * 1000)
    result = dict(mode=mode, elapsed_seconds=round(elapsed, 4),
        transactions=report["import_summary"]["transactions"], issues=len(report["import_issues"]),
        evidence_page_median_ms=round(statistics.median(samples), 3),
        evidence_page_p95_ms=round(sorted(samples)[23], 3),
        evidence_first_ms=round(samples[0], 3), peak_memory_mb=peak_memory_mb())
    print(json.dumps(result))


def http_worker(store_path):
    """Measure a full owned localhost backend against an existing saved report."""
    import socket
    import threading
    from urllib.request import urlopen
    import uvicorn
    from avoidance.webapp import create_app

    started = clock.perf_counter()
    app = create_app(store_path, seed_demo=False)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    base_url = "http://127.0.0.1:" + str(listener.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        while not server.started:
            if not thread.is_alive() or clock.perf_counter() - started > 15:
                raise RuntimeError("Owned benchmark backend did not become ready")
            clock.sleep(0.01)
        ready_ms = (clock.perf_counter() - started) * 1000

        def get(path):
            began = clock.perf_counter()
            with urlopen(base_url + path, timeout=30) as response:
                body = response.read()
            return json.loads(body), dict(milliseconds=round((clock.perf_counter() - began) * 1000, 3),
                response_bytes=len(body))

        report, report_metrics = get("/api/report")
        ana = next(row for row in report["daily"]["slices"] if row["agent_id"] == "123654")
        evidence_path = "/api/evidence/" + ana["evidence_id"] + "?page=1&page_size=100&scope="
        current, current_metrics = get(evidence_path + "current")
        peer, peer_metrics = get(evidence_path + "peer")
        result = dict(mode="http", startup_ready_ms=round(ready_ms, 3),
            transactions=report["import_summary"]["transactions"], publication_id=report["publication"]["id"],
            report=report_metrics, first_current_page={**current_metrics, "rows": len(current["transactions"])},
            first_peer_page={**peer_metrics, "rows": len(peer["transactions"])},
            peak_memory_mb=peak_memory_mb(), browser_included=False)
        print(json.dumps(result))
        BASE.mkdir(parents=True, exist_ok=True)
        (BASE / "latest_http_results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scale", type=int, default=17)
    parser.add_argument("--inputs-run", type=Path, help="Reuse a prior runtime/benchmark run's generated inputs")
    parser.add_argument("--worker", choices=("cold", "warm", "reload", "http"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--store", type=Path)
    args = parser.parse_args()
    if args.worker:
        http_worker(args.store) if args.worker == "http" else worker(args.worker, args.source, args.store)
        return
    if not 1 <= args.scale <= 25:
        parser.error("Scale must be 1–25 to keep native transaction IDs eight digits")
    run = BASE / ("run-" + str(clock.time_ns()))
    run.mkdir(parents=True)
    records = []
    for factor in dict.fromkeys((1, args.scale)):
        source = (args.inputs_run if args.inputs_run else run) / f"inputs-{factor}x"
        scaling_started = clock.perf_counter()
        if args.inputs_run:
            if not source.is_dir():
                parser.error("The prior run has no matching generated input folder")
        else:
            scale_inputs(source, factor)
        storage = run / f"store-{factor}x"
        record = dict(replication_factor=factor, fixture_generation_seconds=round(clock.perf_counter() - scaling_started, 3))
        for mode in ("cold", "warm", "reload"):
            completed = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker", mode,
                "--source", str(source), "--store", str(storage)], text=True, capture_output=True)
            if completed.returncode:
                raise RuntimeError(completed.stderr)
            record[mode] = json.loads(completed.stdout)
            print(json.dumps(dict(replication_factor=factor, **record[mode])), flush=True)
        record["normalized_cache_mb"] = round(sum(path.stat().st_size for path in (storage / "normalized").glob("*.json")) / 1024 ** 2, 2)
        records.append(record)
    result = dict(measured_utc=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        python=platform.python_version(), os=platform.platform(), cpu=platform.processor(),
        logical_cpus=os.cpu_count(), physical_ram_gb=physical_ram_gb(),
        storage_type="Not measured", measurements=records)
    (run / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (BASE / "latest_results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("Saved " + str(run / "results.json"), flush=True)


if __name__ == "__main__":
    main()

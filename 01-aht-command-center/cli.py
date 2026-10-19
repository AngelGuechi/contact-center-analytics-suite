"""Batch import existing interval exports into the local prototype."""

import argparse
from pathlib import Path

from core import AHTStore, ImportProblem


def main():
    parser = argparse.ArgumentParser(description="AHT Command Center V3 local data utilities")
    sub = parser.add_subparsers(dest="command", required=True)
    importer = sub.add_parser("import-dir", help="Import completed Calls_*.xlsx files recursively")
    importer.add_argument("folder", type=Path)
    sub.add_parser("status")
    args = parser.parse_args()
    store = AHTStore()
    if args.command == "status":
        print(store.status())
        return
    if not args.folder.is_dir():
        parser.error(f"Folder not found: {args.folder}")
    paths = sorted(args.folder.rglob("Calls_*.xlsx"))
    if not paths:
        parser.error("No Calls_*.xlsx files found")
    failed = 0
    for path in paths:
        try:
            result = store.import_bytes(path.read_bytes(), path.name)
            print(f"{result['status']:9} {path.name}")
        except ImportProblem as exc:
            failed += 1
            print(f"FAILED    {path.name}: {exc}")
    print(f"Files: {len(paths)}; failures: {failed}; accepted calls: {store.total_calls()}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

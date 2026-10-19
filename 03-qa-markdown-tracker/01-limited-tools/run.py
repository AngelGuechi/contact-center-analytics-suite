from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from qa_shared.core import DataError, build_report, load_sources, CATALOG
from qa_shared.paths import source_paths, report_path
from qa_shared.excel_report import write_report


def controls(data, options):
    """A small standard-library form; Excel and Python remain the only tools."""
    import tkinter as tk
    from tkinter import ttk, messagebox
    window = tk.Tk()
    window.title("Update QA")
    window.geometry("510x420")
    window.resizable(False, False)
    frame = ttk.Frame(window, padding=24)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Choose your QA report", font=("Arial", 16)).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 16))
    labels = {"report_date": "Report date (YYYY-MM-DD)", "start_date": "Markdown start date (optional)",
              "supervisor": "Supervisor", "manager": "Manager", "call_type": "Call type", "markdown": "Markdown"}
    values = {}
    for index, (name, label) in enumerate(labels.items(), 1):
        ttk.Label(frame, text=label).grid(row=index, column=0, sticky="w", pady=9)
        variable = tk.StringVar(value=options.get(name) or ("All" if name in ("supervisor", "manager", "call_type", "markdown") else ""))
        if name in ("report_date", "start_date"):
            field = ttk.Entry(frame, textvariable=variable, width=27)
        else:
            choices = list(CATALOG) if name == "markdown" else sorted({a[name] for a in data["audits"]})
            field = ttk.Combobox(frame, textvariable=variable, values=["All", *choices], state="readonly", width=25)
        field.grid(row=index, column=1, sticky="ew", padx=(16, 0))
        values[name] = variable
    result = {}

    def submit():
        proposed = {k: v.get().strip() for k, v in values.items()}
        try:
            build_report(data, proposed["report_date"] or None, {k: proposed[k] for k in ("supervisor", "manager", "call_type", "markdown")},
                         proposed["start_date"] or None)
        except (DataError, ValueError) as exc:
            messagebox.showerror("Check the report dates", str(exc))
            return
        result.update(proposed)
        window.destroy()

    ttk.Button(frame, text="Create QA workbook", command=submit).grid(row=8, column=0, columnspan=2, sticky="ew", pady=20)
    window.mainloop()
    return result or None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Create the QA review workbook from Excel exports.")
    parser.add_argument("--input", type=Path, help="Private input folder with Audits.xlsx and Roster.xlsx")
    parser.add_argument("--demo", action="store_true", help="Use separate, labelled synthetic audits")
    parser.add_argument("--date", dest="report_date")
    parser.add_argument("--start-date")
    parser.add_argument("--supervisor")
    parser.add_argument("--manager")
    parser.add_argument("--call-type")
    parser.add_argument("--markdown", choices=list(CATALOG))
    parser.add_argument("--sample", type=Path)
    parser.add_argument("--output", type=Path, default=report_path('01-limited-tools'))
    parser.add_argument("--interactive", action="store_true")
    args = parser.parse_args(argv)
    try:
        folder, sample = source_paths(args.input, args.sample, demo=args.demo)
        data = load_sources(folder, sample)
        default_date = args.report_date or max((a["date"] for a in data["audits"]), default=None)
        options = {**vars(args), "report_date": default_date or ""}
        if args.interactive:
            options = controls(data, options)
            if options is None:
                print("Update cancelled. The previous workbook is unchanged.")
                return 0
        report = build_report(data, options.get("report_date") or None,
                              {k: options.get(k) for k in ("supervisor", "manager", "call_type", "markdown")},
                              options.get("start_date"))
        write_report(report, args.output)
        report_file = args.output.with_suffix(".json")
        report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Created: {args.output}")
        print(f"{report['mode']}. Report date: {report['report_date']}. Audits MTD: {report['audit_count']}.")
        print(report["summary"])
        return 0
    except PermissionError:
        print("Close QA_Review.xlsx in Excel and run Update QA again. The previous workbook was preserved.", file=sys.stderr)
        return 1
    except (DataError, ValueError, OSError) as exc:
        print(f"QA update stopped: {exc}. The previous workbook was preserved.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

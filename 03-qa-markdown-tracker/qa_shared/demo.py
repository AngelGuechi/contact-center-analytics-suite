"""Synthetic audits. The importer uses supplied names when the sample is available.

Scores, transactions, teams and coaching remain simulated and labelled as examples.
"""
from datetime import date, datetime, timedelta
from pathlib import Path
import json
import random
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED

from openpyxl import Workbook

from .core import CATALOG


def ensure_sample(path):
    """Generate an anonymous call list when a clean checkout has no attachment.

    Distinct sample IDs deliberately do not match simulated audit transactions.
    The resulting file contains no source names, recordings or customer details.
    """
    path = Path(path)
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    namespaces = {
        'office': 'urn:oasis:names:tc:opendocument:xmlns:office:1.0',
        'table': 'urn:oasis:names:tc:opendocument:xmlns:table:1.0',
        'text': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0',
    }
    for prefix, uri in namespaces.items():
        ET.register_namespace(prefix, uri)
    def tag(prefix, name):
        return '{' + namespaces[prefix] + '}' + name
    root = ET.Element(tag('office', 'document-content'), {tag('office', 'version'): '1.2'})
    body = ET.SubElement(root, tag('office', 'body'))
    spreadsheet = ET.SubElement(body, tag('office', 'spreadsheet'))
    table = ET.SubElement(spreadsheet, tag('table', 'table'), {tag('table', 'name'): 'Selected Calls'})
    def row(values):
        element = ET.SubElement(table, tag('table', 'table-row'))
        for value in values:
            cell = ET.SubElement(element, tag('table', 'table-cell'), {tag('office', 'value-type'): 'string'})
            ET.SubElement(cell, tag('text', 'p')).text = value
    row(['Transaction', 'Agent', 'Login ID', 'Date Time', 'Duration Normalized', 'Recording Type', 'Sample Category'])
    for agent in range(1, 43):
        for call in range(1, 37):
            row([f'EXAMPLE-CALL-{agent:03}-{call:03}', f'Example person {agent:02}',
                 f'EXAMPLE{agent:03}', f'2026-08-{3 + (call - 1) % 15:02}T10:00:00',
                 '00:05:00', 'Voice and screen', 'Synthetic example'])
    with ZipFile(path, 'w', compression=ZIP_DEFLATED) as archive:
        archive.writestr('mimetype', 'application/vnd.oasis.opendocument.spreadsheet', compress_type=ZIP_STORED)
        archive.writestr('content.xml', ET.tostring(root, encoding='utf-8', xml_declaration=True))
        archive.writestr('META-INF/manifest.xml', '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"><manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.spreadsheet"/><manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/></manifest:manifest>')
    return path


def write_table(path, headers, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = path.stem
    ws.append(headers)
    for row in rows:
        ws.append(row)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    wb.save(path)


def ensure_demo(path):
    path = Path(path)
    if (path / "SYNTHETIC-DEMO.json").exists():
        return path
    if path.exists() and any(path.iterdir()):
        raise ValueError("Demo generator will not replace an existing input folder")
    path.mkdir(parents=True, exist_ok=True)
    rng = random.Random(579)
    roster = [[f"DEMO{i:03}", f"Demo agent {i:02}", f"Team {(i - 1) // 7 + 1}",
               f"Manager {(i - 1) // 21 + 1}", "Demo site"] for i in range(1, 43)]
    call_types = ["Credit", "NEM", "CBB", "LPC", "MIMO", "General Billing"]
    comments = {"OIR": "The resolution was not checked with the customer before closing the call.",
                "Silence": "The evaluator noted an unexplained pause while the agent reviewed the account.",
                "Mailing Address": "The approved mailing-address confirmation was missed.",
                "TPS": "The approved three-point script wording was incomplete.",
                "Notes": "The notes did not capture the action and agreed outcome."}
    headers = ["Audit ID", "Revision", "Audit Date", "Transaction ID", "Login ID", "Evaluator", "Call Type",
               "Final QA Score", *CATALOG, *(m + " Points Lost" for m in CATALOG), "Comments"]
    audits, snom = [], []
    cursor, index = date(2026, 7, 1), 0
    while cursor <= date(2026, 8, 31):
        if cursor.weekday() < 4:
            for i in range(1, 43):
                # Some agents improve, some worsen, and others remain broadly steady.
                late = cursor >= date(2026, 8, 18)
                probabilities = [0.08, 0.10, 0.06, 0.05, 0.10]
                if i % 3 == 1:
                    probabilities[0] = 0.04 if late else 0.30
                elif i % 3 == 2:
                    probabilities[1] = 0.32 if late else 0.06
                marks = [rng.random() < p for p in probabilities]
                remaining, points = 100, []
                for md, triggered in zip(CATALOG, marks):
                    loss = min(remaining, CATALOG[md]["impact"]) if triggered else 0
                    points.append(loss)
                    remaining -= loss
                index += 1
                aid, txn, login = f"DEMO-AUD-{index:05}", f"DEMO-TXN-{index:05}", f"DEMO{i:03}"
                comment = " ".join(comments[m] for m, yes in zip(CATALOG, marks) if yes) or "The reviewed call met the recorded QA checks."
                audits.append([aid, 1, datetime.combine(cursor, datetime.min.time()), txn, login,
                               f"Demo evaluator {i % 3 + 1}", call_types[(i + cursor.day) % 6],
                               remaining, *("Yes" if m else "No" for m in marks), *points, comment])
                for md, yes in zip(CATALOG, marks):
                    if yes:
                        snom.append([txn, login, md, CATALOG[md]["category"], "Demo recorded finding", "Yes"])
        cursor += timedelta(days=1)
    write_table(path / "Audits.xlsx", headers, audits)
    write_table(path / "Roster.xlsx", ["Login ID", "Agent", "Supervisor", "Manager", "Site"], roster)
    write_table(path / "SNOM3.xlsx", ["Transaction ID", "User ID", "Markdown", "L1", "L2", "Screen Recording"], snom)
    coaching = [[f"DEMO{i:03}", datetime(2026, 8, 17), "OIR", f"Team {(i - 1) // 7 + 1}",
                 "Review ownership and confirm resolution using the approved rubric.", datetime(2026, 9, 1)]
                for i in range(1, 43) if i % 3 == 1]
    write_table(path / "Coaching.xlsx", ["Login ID", "Coaching Date", "Markdown", "Supervisor", "Agreed Action", "Follow-up Date"], coaching)
    (path / "SYNTHETIC-DEMO.json").write_text(json.dumps({"synthetic": True, "agents": 42,
        "audit_rows": len(audits), "period": "2026-07-01 to 2026-08-31",
        "note": "Invented demo audits on DEMO-TXN identifiers. They are not audits of the supplied selected calls."}, indent=2), encoding="utf-8")
    return path

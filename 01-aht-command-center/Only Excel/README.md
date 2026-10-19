# AHT Excel Workflow Sources

This folder preserves the alternative AHT calculation backend and Excel refresh scripts from the local workspace.

- `backend/`: Python calculation and validation modules, using the NPS demo roster and call-context sidecars.
- `Update/`: Windows refresh scripts for a compatible Excel review workbook.

The original workbook and its cached data/connections are excluded from this portfolio edition. The updater requires a compatible workbook supplied separately; it is not a ready-to-run spreadsheet demo here. The browser-based AHT demo in the parent folder is self-contained.

For the Python backend, use Python 3.14 and the dependencies in `backend/pyproject.toml`. Generate the fictional NPS sample and sidecars first. The paths in this edition point to that synthetic sample rather than the original attachment.

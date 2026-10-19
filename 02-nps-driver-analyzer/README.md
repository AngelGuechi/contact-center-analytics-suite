# NPS & Survey Analytics Backend

Python backend for call/survey data contracts, exact NPS calculations, pooled team rollups, controllability rules, redaction, and synthetic survey generation. A complete hosted dashboard and live survey feed are outside this source edition.

Use Python 3.14. From `backend/`, create a virtual environment and install dependencies:

```text
python -m pip install polars fastexcel xlsxwriter openpyxl pytest tzdata
```

Set `PYTHONPATH` to `src` for the following module commands (PowerShell: `$env:PYTHONPATH="src"`). Then run:

```text
python demo_seed.py
python -m nps_pipeline.inputs
python -m nps_pipeline.synthetic
python -m pytest tests/test_nps.py tests/test_periods.py tests/test_redact.py tests/test_catalog.py
```

The seed command creates an entirely fictional 42-agent call sample. The next commands build the matching roster, call context, survey events, and answer key. Generated files stay ignored by Git.

Some original integration tests assert the shape of an excluded source attachment. Those tests are retained for traceability but are not part of the portable verification command above.

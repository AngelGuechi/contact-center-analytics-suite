# QA Analytics & AI Coaching

Excel/Python reporting and a Streamlit review interface for audit scores, markdown frequency and points lost, trends, and recorded coaching actions. Calculations come from code; optional AI drafts explain a masked evidence packet and require human review.

From this folder, with Python 3.12:

```text
python -m pip install -r requirements.txt
python launch.py limited
python launch.py ai
```

The limited command creates an Excel report. The AI interface opens at http://127.0.0.1:8503. With no source attachment or configured input folder, the application generates fictional agents, audits, and coaching examples. Optional AI generation requires the user's own configured key; the calculated reports remain usable without it.

Run the existing checks with `python launch.py test`. Existing operational files and the original call sample are excluded from this edition. Shared deployment and company sign-in are future pilot work.

# AHT Command Center

Local FastAPI/SQLite dashboard for weighted average handle time, interval validation, duplicate detection, full-window revisions, history, agent/supervisor drill-downs, and evidence-based recommendations. Optional Azure OpenAI explains calculated evidence; it does not calculate the KPI.

From this folder:

```text
python -m pip install -r requirements.txt
python demo_seed.py
python -m uvicorn webapp:app --host 127.0.0.1 --port 8765
```

Open http://127.0.0.1:8765. The seed command generates fictional calls for five dates relative to the current day and imports them into the local store. Use an empty data folder for a separate dataset; never mix demo and operational inputs.

Core verification: `python -m unittest discover -s tests -v`.

This is a local prototype, with no company sign-in or unattended integration.

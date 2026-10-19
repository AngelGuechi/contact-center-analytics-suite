# Contact Center Analytics & Applied AI

An end-to-end portfolio suite by **Angel Guechi** connecting operational exports to validated KPIs, reviewable evidence, and optional AI explanations.

## Projects

| Project | What is implemented | Start here |
|---|---|---|
| AHT Command Center | Excel ingestion, SQLite history, weighted average handle time, revision handling, drill-downs, and evidence-based coaching | [AHT application](01-aht-command-center/) |
| NPS & Survey Analytics | Survey/event data contracts, deterministic NPS, controllability rules, team rollups, redaction, synthetic generation, and backend tests | [NPS backend](02-nps-driver-analyzer/) |
| QA Analytics & Coaching | Excel reports, a Streamlit review interface, calculated markdowns, persisted coaching, and optional evidence-grounded AI drafts | [QA applications](03-qa-markdown-tracker/) |
| Call Review & Speech Analytics | FastAPI/React review desk, peer/personal baselines, source evidence, human decisions, and optional local speech analysis | [Call review application](05-call-avoidance-detector/) |
| Complex Call Assistant | Design concept only | [Concept](04-complex-call-assistant/) |
| Move-out Date Validation | Design concept only | [Concept](06-move-out-end-dating/) |

The NPS folder is a backend prototype, not a deployed live survey dashboard. The two concept folders contain no implemented application.

## Business focus

- Turn repeated operational exports into consistent calculations and reports.
- Help supervisors find performance gaps and inspect the records behind them.
- Separate deterministic arithmetic from AI-written explanations.
- Keep human review in coaching and call-review workflows.

```text
Synthetic exports -> validation and normalization -> KPI/history store
                 -> dashboard or Excel report -> evidence -> human review
                                               -> optional AI explanation
```

## Run locally

Each project has its own requirements and commands. AHT, QA, and call review use Python 3.12 or a compatible version. The NPS backend specifies Python 3.14. Install only the requirements for the project you want to inspect. No live model credentials are needed for the deterministic demo paths.

The call-review folder includes its built React interface. Node.js is only needed to rebuild that interface. Optional local transcription downloads model files separately; they are not bundled here.

## Portfolio edition

This is a curated source edition of the local development workspace. It contains application code, interface assets, tests, launchers, and synthetic-data generators. Original client attachments, operational spreadsheets, existing databases, operational recordings, private briefs, credentials, generated presentations, and Git history are excluded. Workbook demo inputs are generated locally from fictional records. Ten synthetic audio recordings are included with generator metadata and verified hashes.

These are local prototypes. Live company identity, scheduled integrations, shared deployment, and business impact require separate validation. Synthetic demonstrations and review signals are not evidence of an employee's intent or misconduct.

[Portfolio](https://github.com/AngelGuechi) | [LinkedIn](https://www.linkedin.com/in/angel-guechi)

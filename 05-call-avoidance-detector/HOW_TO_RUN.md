# How to run the local Call Avoidance Detector

The Windows-first demonstration uses FastAPI + React and rule-based explanations. The workbook workflow has no model downloads. Optional audio transcription uses a local model installed once; see [Audio setup and usage](AUDIO_HOW_TO_RUN.md). There are no model fees or API keys. Browser assets are included. First setup needs internet; everyday use runs locally.

## Start on Windows

1. Extract the complete `05-call-avoidance-detector` folder to a writable location. Do not launch inside a ZIP.
2. Install **64-bit Python 3.12 or 3.14** if needed from [python.org](https://www.python.org/downloads/windows/), including its Python launcher. Python 3.12 is preferred. The installer accepts 3.12–3.14; 3.13 has not been separately validated.
3. Double-click **INSTALL.bat** once. Wait for “Installation complete.” It creates this computer's `.venv` and installs pinned packages.
4. Double-click **RUN.bat**. The browser opens when the local server is ready. First start prepares the synthetic fixture; later starts load the saved report.
5. Leave the launch window open. Press **Ctrl+C** there to stop.

The preferred address is `http://127.0.0.1:8505`. If occupied, RUN chooses an available nearby port and displays the actual address. A second RUN reuses the matching instance. INSTALL refuses to change an environment while the app uses that data store.

Excel, Node, Codex, Docker, a GPU and AI software are **not needed for everyday use**. Use a modern Edge or Chrome browser. Windows 11 x64 with Python 3.12.9 and 3.14.6 was tested; other platforms/architectures are unverified. Minimum laptop RAM is still to be confirmed. See [measured performance](BENCHMARK_RESULTS.md).

## First walkthrough

The analyzed day is October 6, 2026, with 14 complete prior days. Synthetic records are invented.

1. In **Daily patterns**, inspect Synthetic Ana Ruiz: **6 signals / 30 transactions = 20%**, versus peer **56 / 2,800 = 2%** and personal **14 / 700 = 2%**. Both comparisons qualify under default rules.
2. Open **Inspect**. Read the plain-language finding and the Today / Team history / Agent history comparison. The original file, sheet and row are visible beside each record. **Short records only** opens automatically for a flagged pattern; switch to **All records** to inspect the full denominator. Switch between **Today**, **Team history** and **Agent history**; lists use 25 records per page. Expand **Original cells & file details** for the exact cell values, types, Excel formats and file fingerprint.
3. Choose an outcome, enter a reviewer label/note and **Save local review**. It saves locally without changing the calculated flag.
4. In **Intraday leads**, inspect Synthetic Bruno Mora. Adjacent intervals add five transactions each, with mean aggregate talk of **24s** and **30s**. Inspect the three original snapshot rows.
5. In **Rules**, change a value and save. New evidence requires a fresh review; previous decisions remain under **Reviewed earlier evidence**.

These measurements require human review. Supplied exports cannot establish ghost calls or intent. Missing history, low samples, zero transactions and unavailable signals remain visible.

## Appearance and presenting a finding

Use the **Dark mode** switch in the top bar to change between light and dark. The browser remembers your choice; the first visit follows its system preference.

Inside **Inspect**, use **Copy summary** to copy the finding, rates and next step in plain text. **Print / save PDF** opens the browser's print dialog with a clean finding and source-record layout. Navigation, review forms and technical controls are excluded from printing. Your browser chooses the printer or PDF destination.

An inspection stays tied to the report you opened. If sources or rules change, a **saved report** notice appears and its original evidence remains available. Use **Reload latest report** before saving a new decision. A zero-transaction agent shows **No records to inspect**.

## Replay evidence arriving

In **Imports**, use the synthetic replay buttons in order:

| Stage | Available evidence | Expected with default rules |
|---|---|---|
| 1 Start snapshot | 09:00 snapshot and prior history | No lead; daily incomplete |
| 2 Next snapshot | Adds 09:30 | One qualifying interval; no lead |
| 3 Lead arrives | Adds 10:00 | One weak lead; daily incomplete |
| 4 Complete day | Final snapshot and complete daily export | One daily pattern and one weak lead |

Active rules apply; reviews/publications are retained. **Load demonstration** restores the complete fixture without resetting rules or deleting reviews. Restore defaults in [spec.md](spec.md) if edited rules change the expected answer key.

## Import a dataset

In **Imports**, choose the folder containing Admin, Tool 1 snapshots, Tool 2 exports and `manifest.json`, then **Validate & import**. Relative subfolders are preserved. **Refresh report** reads the latest saved report; it does not rescan the original folder.

The bundled [data folder](data/README.md) contains records with ordinary names and filenames: a roster, 15 daily exports and four snapshots. Start **RUN.bat**, open **Imports**, click **Choose folder**, select `05-call-avoidance-detector/data`, then **Validate & import**. Select the whole `data` folder so its manifest and history are included. The records are generated; their origin is recorded in the manifest. Compare the imported report with `data/expected_results.json` using the default rules.

Each import is a complete input set, including required history. It replaces the active report rather than appending a lone export. Workbooks are copied unchanged, hashed and parsed from retained copies. Identical inputs reuse normalization. Invalid files, duplicates, mapping issues and missing dates appear in Imports. An invalid replacement of the analyzed day preserves the previous dated report.

Supported layouts are the native synthetic Tool 1 `LiveAgentData`, Tool 2 42-column export and Admin roster described in the spec. This is not a generic Excel uploader. Confirm actual export semantics before operational use.

Use [fixtures/manifest.json](fixtures/manifest.json) as the completeness schema. Required fields include `schema_version`, `synthetic`, `report_date`, `server_timezone`, `admin_file`, `expected_days`, `complete_days` and `files`. Each Tool 2 descriptor has relative `file`, `kind: tool2`, `business_date`, `required` and `complete`; Tool 1 descriptors use `kind: tool1` and a local ISO `captured_at` with timezone offset. List every required prior date/file. Declare completeness only from an agreed authority; filenames do not prove completeness. Optional manifest `annotations` provide human incident context without changing counts/rules.

Upload ceilings are 1,000 files, 50 MB per file and 500 MB per batch. They are not performance guarantees.

## Separate approved operational trials

The default store is `runtime/data`. Synthetic and operational inputs cannot mix in one store. Use a new private data folder for approved masked/operational trials. From a Command Prompt in the app folder:

```bat
set "CA_DATA_DIR=%LOCALAPPDATA%\CallAvoidanceTrial"
INSTALL.bat /nopause
RUN.bat --empty
```

`--empty` prevents first-start synthetic seeding. Use Imports to load the full dataset. Repeat the same `CA_DATA_DIR` when starting/checking that store. Do not use a shared network folder or run two servers against one store. This localhost demonstration has no login; production identity, access and retention are undecided.

## Copy, update and back up

Stop the app and copy/extract the entire source release. For a clean demo, **exclude `.venv`, `frontend/node_modules` and `runtime`**. Run INSTALL on every destination computer; virtual environments are not portable. Moving the app also requires INSTALL again. Environment repair preserves data/reviews.

To transfer reviews deliberately, copy the entire stopped data store to a new empty private location and set `CA_DATA_DIR` there. Keep `sources`, `normalized`, `publications`, `current.json`, `settings.json` and all `.jsonl` logs together. Back up before maintenance; do not merge stores by hand. A stale `instance.json` or persistent `runtime.lock` file does not itself indicate a running process: RUN checks actual ownership.

Source updates are manual. After replacing release files, stop the app and rerun INSTALL if requirements changed.

## Offline setup and options

Installed operation uses bundled assets and localhost, with no model calls. First-time offline setup also needs compatible Python and matching wheels prepared on an internet-connected computer:

```bat
.venv\Scripts\python.exe -m pip download --only-binary=:all: -r requirements.txt -d wheelhouse
INSTALL.bat --offline --wheel-dir "D:\CallReviewWheels"
```

Prepare wheels for the destination's Windows architecture/Python version. A 3.12 wheel folder may not work for 3.14. The source release does not include Python or offline wheels.

| Option | Purpose |
|---|---|
| `CA_DATA_DIR` | Writable private store; relative paths resolve from the app folder |
| `CA_PORT` | Preferred local port, 1024–65515 |
| `CA_NO_UI=1` or `RUN.bat --no-browser` | Start without opening a browser |
| `CA_PYTHON` | Full supported `python.exe` path for INSTALL, without arguments |
| `INSTALL.bat --repair` | Recreate only `.venv`, preserving data; stop the app first |
| `/nopause` | Unattended shortcut mode with an exit code |

`config.example.json` is a defaults reference, not a loaded configuration file. Use these environment variables and the Rules page.

## Troubleshooting

Double-click **CHECK.bat**. It checks runtime, packages, timezone, interface, data location and running-instance information without installing/importing anything.

| Symptom | Action |
|---|---|
| Python missing/unsupported | Install 64-bit 3.12/3.14 or set `CA_PYTHON`, then INSTALL |
| Download fails | Check internet or supply matching offline wheels |
| Environment incomplete/moved | Stop app, rerun INSTALL; use `--repair` when needed |
| Browser does not open | Use the actual local URL in the launch window |
| Data folder locked | Stop its app/installer; do not delete files to bypass the lock |
| Data path not writable | Choose private `CA_DATA_DIR` outside `.venv` |
| Incomplete / Insufficient history | Supply accepted exports and completeness; missing dates are not zero calls |
| Mixing refused | Start a separate store with `--empty` |
| Import fails | Inspect Imports; the prior publication remains visibly dated |

Logs: `runtime/install.log`, `runtime/run.log`, and data-store `attempts.jsonl`, `settings_history.jsonl`, `reviews.jsonl`. Originals, caches and publications also stay in the local data store.

## Developer checks

After INSTALL, run `.venv\Scripts\python.exe launch.py test` and `.venv\Scripts\python.exe benchmark.py`. React development requires Node, followed by `npm ci` and `npm run build` inside `frontend`. Ship the resulting `frontend/dist`; everyday users do not run frontend commands.

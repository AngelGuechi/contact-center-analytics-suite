# Run on another device

Keep the complete `03-qa-markdown-tracker` folder together. It can be inside a GitHub clone, a downloaded ZIP or a folder with a different name. No drive letters or user names need editing.

| Device | How to use it |
| --- | --- |
| Windows, Mac or Linux computer | Install Python and run either solution using the commands below. |
| Phone, tablet or Chromebook | Open the AI dashboard's web address after it is running on an accessible computer or server. These devices do not need Python or an API key installed. |
| Excel desktop on Windows or Mac | Open the limited solution's workbook. Use a current Excel version for native PivotTable filters and drill-down. |
| Other spreadsheet viewers | Read the saved results. Native PivotTable controls depend on the viewer; use the browser Pivot Tables page when needed. |

Uploading files to GitHub stores the code. It does not start the dashboard. An accessible server is required for a shared browser address. Company hosting, sign-in and access permissions remain a deployment step before sharing operational data.

## Install once

### Windows: two double-click files

1. Double-click **portable.bat** once to install both solutions. It finds Python or installs Python 3.12 with Windows Package Manager when available, then creates the project's `.venv` and installs the required packages. The first installation needs internet access. If Windows Package Manager is unavailable, it explains how to install Python manually.
2. Double-click **run.bat** and choose **AI dashboard**, **Excel report**, **presentations** or **check installation**. The dashboard opens in your browser; leave its console window open while using it. No OpenAI key is needed for the reports and dashboard views.

Keep the whole project folder together. When copying to another computer, run portable.bat on that computer once; Python environments cannot simply be carried between different machines. Re-running the installer preserves your source files, reports and coaching. Installation details are saved in `runtime/install.log` and `runtime/install-errors.log`.

Optional commands are `run.bat ai`, `run.bat limited`, `run.bat presentations`, `run.bat check` and `run.bat test`. For unattended installation use `portable.bat /nopause`. `QA_NO_UI=1` suppresses automatic browser/file opening during checks. `QA_PORT` can select a different dashboard port when 8503 is already in use. Python installation uses the official Windows Package Manager [install command](https://learn.microsoft.com/en-us/windows/package-manager/winget/install).

### Python commands on any desktop operating system

Install Python 3.12, then open a terminal in `03-qa-markdown-tracker` and run:

```text
python setup.py
```

On Mac or Linux, use `python3 setup.py` if the `python` command is unavailable. On Windows, `py -3.12 setup.py` also works. Linux may require its `python3-venv` package. Setup downloads the required packages into this folder's `.venv`; neither Codex nor Excel is needed to start the browser version.

Activate that environment:

| Terminal | Command |
| --- | --- |
| Windows PowerShell | `.\.venv\Scripts\Activate.ps1` |
| Windows Command Prompt | `.venv\Scripts\activate.bat` |
| Mac or Linux terminal | `source .venv/bin/activate` |

If PowerShell does not allow activation, skip activation and use `.\.venv\Scripts\python.exe` wherever the instructions below say `python`. On Mac or Linux the equivalent is `.venv/bin/python`.

## Start either solution

```text
python launch.py doctor
python launch.py limited --demo
python launch.py ai
```

The limited command creates `01-limited-tools/output/QA_Review.xlsx`. Open it in Excel. For a desktop filter form, add `--interactive`; that optional form needs Tkinter and a graphical desktop. The command without the form also runs on headless servers.

The AI command keeps running until you stop it with Ctrl+C. On the same computer, open `http://localhost:8503`. The report, filters, Pivot Tables and coaching work without an OpenAI key. To request AI drafts, supply your key in Settings or through the server's `OPENAI_API_KEY` environment variable. Keep the key on the server; never put it in GitHub or a browser URL.

Windows double-click shortcuts still work after setup and automatically find `.venv`. The Python commands work on all three desktop operating systems.

To review both HTML presentations:

```text
python launch.py presentations
```

Open `http://localhost:8803/limited/` or `http://localhost:8803/ai/`. Static `presentation.html` files can also be opened directly in a browser. Workbook links work after that solution has generated its report.

## Keep your own files and names

Your source names are retained. If the supplied ODS remains in the project folder, the importer finds it automatically. A fresh checkout without private attachments creates anonymous example calls so every demo view can still be reviewed. Example scores stay labelled as simulated.

For actual data, configure the private paths on the computer running the solution:

| Optional setting | Purpose |
| --- | --- |
| `QA_INPUT_FOLDER` | Private folder with `Audits*.xlsx`, `Roster.xlsx` and optional `SNOM3.xlsx` / `Coaching.xlsx`. |
| `QA_SAMPLE_FILE` | Full path to the supplied ODS call sample. A configured missing path produces a clear error. |
| `QA_DATA_DIR` | Writable location for generated examples, reports and the dashboard database. Defaults to the project folder. |
| `QA_STORE_PATH` | Override the dashboard database file location. |
| `OPENAI_API_KEY` | Optional OpenAI connection, used only when requesting an AI draft. |

The limited solution also accepts `--input`, `--sample` and `--output` paths. Put paths containing spaces in quotes. Do not use `--demo` when you intend to import actual audits.

## Phones and tablets

For a demo on a trusted local network, run `python launch.py ai --host 0.0.0.0` and open `http://SERVER-IP:8503` on the other device. Use the server's network address, replacing `SERVER-IP`; `localhost` always refers to the device opening the page. The computer's firewall must allow the connection. Demo examples are the appropriate data for this unauthenticated network preview.

Filters and page navigation use the browser's responsive layout. Wide evidence tables scroll horizontally. The Excel workflow remains a desktop workflow; the dashboard is the way to use QA views on mobile devices.

For company use across networks, deploy behind company sign-in and HTTPS. Keep the default local binding until that deployment is ready. Do not share the demo's unauthenticated address with operational data or a server API key.

## Optional Docker setup

With Docker and Compose installed, run from this folder:

```text
docker compose up --build --detach
```

Open `http://localhost:8503`. The named `qa-data` volume keeps coaching, usage and imported snapshots across container restarts. A local `.env` can supply `OPENAI_API_KEY` using `.env.example`; it is excluded from Git and the image. Docker does not automatically use an ODS on your desktop: mount the private input location and set its container paths if you want actual data and names. The default image uses anonymous examples.

The same image can create the limited workbook without Excel:

```text
docker compose run --rm qa limited --demo
```

Its workbook stays in the named data volume. To copy it into this folder for review:

```text
docker compose cp qa:/data/01-limited-tools/output/QA_Review.xlsx QA_Review.xlsx
```

The copy command needs the running `qa` service from `docker compose up`. Stop services with `docker compose down`; the named volume is retained. Docker is an optional packaging method, not required for Python installation.

## Checks before the GitHub commit

```text
python launch.py test
```

Tests use anonymous temporary data and fake AI responses; they do not need private attachments or an OpenAI key. The repository workflow runs these checks on Windows, macOS and Linux with Python 3.12 and 3.13, and builds and checks the Docker image on Linux. Those remote checks run after the workflow is committed; adding the file does not mean the remote checks have already passed.

The workflow follows the official [checkout](https://github.com/actions/checkout) and [Python setup](https://github.com/actions/setup-python) instructions. Container settings follow the [Docker Compose documentation](https://docs.docker.com/reference/compose-file/services/).

Generated reports, databases, `.env`, source spreadsheets and private folders are ignored. **The originally supplied ODS was already tracked before these changes. Ignore rules do not remove an already tracked file or its history.** Before publishing, confirm whether it is approved masked data; otherwise remove it from the publishable repository and address any existing remote history separately. It remains on disk here so your names are preserved.

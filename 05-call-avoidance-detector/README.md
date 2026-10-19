# Call Review & Speech Analytics

A local FastAPI/React review desk for call exports, peer and personal baselines, visible source evidence, and saved human review decisions. Optional audio tools add silence measurements and CPU transcription with faster-whisper.

## Run

With Python 3.12, from this folder:

```text
python -m pip install -r requirements.txt
python -m uvicorn avoidance.webapp:create_app --factory --host 127.0.0.1 --port 8766
```

Open http://127.0.0.1:8766. On first startup the app generates and imports fictional 15-day demo workbooks under its ignored runtime folder. The built React interface is included. For Windows setup and diagnostics, the existing INSTALL.bat, RUN.bat, and CHECK.bat launchers are retained.

## Optional audio

Run INSTALL_AUDIO.bat to prepare local audio dependencies. Ten locally generated fictional recordings are included; their hashes were checked against the synthetic generator manifest before publication. Operational recordings and model binaries are excluded. Model downloads happen separately.

## Rebuild the interface

From `frontend/`: `npm ci`, then `npm run build`.

## Verification and scope

Run `python prepare_demo.py`, then `python -m unittest discover -s tests -v`. The setup command generates fictional workbooks for the retained test suite. Optional audio-engine tests require the additional audio environment; see VALIDATION.md for the checks actually run on this curated edition.

This is a local pilot. Short-handle signals and aggregate leads do not establish intent or misconduct. Reviewers inspect the source evidence and record their decisions. No business impact or accuracy claim is made from synthetic data.

# Curated portfolio edition - validation

Checked on Windows, October 19, 2026. The source workspace was copied into a separate directory before checks; original operational attachments and source history were excluded.

| Component | Result |
|---|---|
| AHT local-store tests | 3 passed |
| Alternative AHT/Excel backend calculation, headers, and period tests | 28 passed |
| NPS calculation, period, redaction, and catalog tests | 94 passed, 3 skipped |
| QA calculation, AI-transport mocks, dashboard, Excel pivots, and portability tests | 56 passed |
| Call-review rules, import, persistence, HTTP, launch/setup, and audio-workflow tests | 137 passed, 11 skipped |
| **Total** | **318 passed, 14 skipped** |

The 11 skipped call-review checks require the optional audio-engine environment. Other audio store, recording-map, and HTTP workflow checks passed. The NPS result includes three existing skips in that selected test set. No live model API quality or hosted deployment is established by these tests.

## Demo checks

- AHT: generated and imported 720 fictional calls across 20 intervals.
- NPS: generated 20,160 fictional call rows for 42 demo agents; built roster/context sidecars and 1,492 survey events, including 73 detractors, across August 3-17, 2026.
- QA: the portability tests exercised generated anonymous inputs without the original attachment.
- Call review: generated native-format synthetic workbook inputs for the test suite. Ten included fictional recordings match the synthetic generator manifest hashes.

## Reproduce

Use each component's README and requirements. The AHT/QA/call-review checks used Python 3.12; NPS and the alternative AHT backend used Python 3.14. The NPS portable check used Polars 2.0.0, fastexcel 0.21.0, and openpyxl 3.1.5.

Generate call-review test workbooks with `python prepare_demo.py` before running its tests. NPS integration tests tied to the excluded original call attachment are retained but are outside the selected portable check. The original Excel workbook and model binaries are not included. Complex-call assistance and move-out date validation remain design concepts.

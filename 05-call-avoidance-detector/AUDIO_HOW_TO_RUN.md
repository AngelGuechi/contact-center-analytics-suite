# Local call audio: how to run

This adds call playback, silence measurements, a frequency spectrum and English/Spanish transcription to case 05. Processing stays local. There are no model fees, accounts or API keys.

## Windows setup

1. Install **64-bit Python 3.12**, including the Python launcher, if necessary.
2. Run **INSTALL.bat** for the base application.
3. Close the application. Run **INSTALL_AUDIO.bat** once. This creates `.venv-audio`, installs pinned CPU packages and downloads the pinned multilingual **base** model (about 145 MB for its weights). Allow additional space for packages and recordings.
4. Run **CHECK_AUDIO.bat** to verify the packages and model hashes without downloading anything.
5. Run **RUN.bat**, then open **Recordings**.

After installation the worker uses local model files with Hugging Face offline mode. A GPU, paid provider, Excel and Node are unnecessary for everyday use. The audio profile is CPU/int8 with two inference threads. The tested audio environment is Windows x64 / Python 3.12.9. Other operating systems are not yet verified; the Python implementation includes POSIX environment paths, but the shortcuts are Windows files.

Copy the source folder to another computer and install there. Do not copy Python environments. A relocated or changed audio environment must be reinstalled and checked. If Python's `py` launcher is unavailable, run `python audio_setup.py` using 64-bit Python 3.12. Close the app before setup; setup shares the base application's runtime lock.

For a prepared offline computer, supply the exact pinned wheels and all four model files listed in `audio_model.source.json`, then run `python audio_setup.py --offline --wheel-dir C:\path\to\wheels`. Offline packages are not included in the source ZIP.

## Try the included calls

1. Load the generated workbook dataset from **Imports** (the included `data` folder), or use the existing generated demonstration.
2. Open **Recordings → Add included audio calls**.
3. Wait for the measurement queue and selected transcriptions to finish. There are **10 invented recordings**, with spoken Spanish and English, music, long pauses, separate channels, an opposite-phase recording and one all-zero recording.
4. Choose **Inspect**. Play the call, jump to a quiet interval, choose a start time and **Show next 30 seconds** to view the waveform and spectrum.
5. Read the transcript and listen to verify it. You can request English, Spanish or automatic language detection. If another result completes while you inspect an earlier version, choose **Load latest evidence** before saving a review.

The files are in `recordings/Calls`; `recordings.csv` maps them to workbook transaction IDs. `scripts.json` and `manifest.json` describe exactly what was synthesized. They are reference scripts, not promised transcription output. Short fixtures are for functionality checks; they do not establish real-call accuracy or daily production capacity.

## Import your recordings

Open **Recordings → Import call and recording folders**:

1. Choose **Excel call exports — all days**. Select the parent folder containing daily exports and subfolders, including the roster/coverage files used by the existing workbook import. The importer includes all `.xlsx` files plus manifest/incident files; it does not require picking a single Excel file.
2. Choose **Recordings folder**, including nested day folders with WAV or MP3 files.
3. Choose **Import both folders**. Excel validation finishes first, then recordings are linked to the resulting report and uploaded separately.

You can leave the Excel selector empty to use the report already loaded. With no mapping CSV, `70003501.wav` links to the exact Excel **transaction** ID `70003501`. Leading zeroes are retained. Other filenames remain visibly unmatched; the app does not guess from dates or names. Automatic mapping conservatively marks coverage as partial and speaker roles unknown.

If names differ from transaction IDs, or channel/span mappings are needed, put one **recordings.csv** inside the selected recordings folder. It is detected automatically; there is no separate CSV selection step. Excel UTF-16 CSV, Windows-1252 CSV, UTF-8, comma/semicolon/tab separators and Excel `sep=` prefixes are supported. Binary Excel/audio files are rejected with a file-type message rather than a misleading UTF-8 message.

Repeat the same selection to resume a partially uploaded batch. If files are missing, select **Finish without missing files** to close it explicitly; missing references remain as issues and can be supplied later. Automatic sampling waits until the batch is complete or explicitly finished.

For an optional mapping file, UTF-8 is preferred. Use these columns:

```csv
recording_file,call_id,call_id_type,recording_scope,channel_layout,agent_channel,customer_channel,audio_start_seconds,audio_end_seconds
Calls/000123.wav,000123,transaction,transaction_leg,mono,,,,
Calls/000124.mp3,000124,transaction,partial,unknown,,,,
Calls/000125.wav,000125,transaction,partial,separate_roles,0,1,10,90
```

- `recording_file`: path inside the selected folder, including subfolders; WAV or MP3. No absolute paths or parent-directory traversal.
- `call_id`: text matching the workbook ID; retain leading zeroes.
- `call_id_type`: `transaction` or `connection`.
- `recording_scope`: `transaction_leg`, `partial` or `whole_connection`. A multi-leg connection needs explicit transaction-level mapping before agent attribution. Whole-connection audio remains context.
- `channel_layout`: `mono`, `unknown`, or `separate_roles`. Supply distinct zero-based `agent_channel` / `customer_channel` only when verified. Unknown/mixed audio does not identify the silent party.
- `audio_start_seconds`, `audio_end_seconds`: optional original-file span. Playback and analysis timestamps use the original recording timeline.
- `recording_start_at`: optional ISO timestamp including timezone. It is retained as context; it does not resolve ambiguous call links automatically.

Initial limits: 10,000 CSV rows per batch; 5 MB CSV; 2 GB per recording; mono/stereo at 8–192 kHz; maximum decoded duration two hours. Damaged files, timestamp discontinuities and inconsistent durations do not publish a measurement. Original bytes and earlier successful results remain available. Check recording sizes/free disk space before a daily import.

Generated audio is accepted only in a generated workbook store. Keep operational and generated inputs in separate `CA_DATA_DIR` folders, as described in HOW_TO_RUN.md.

## Understand the measurements

**Quiet** requires both low audio volume and no detected speech. Defaults use 20 ms RMS windows, a 10 ms hop, entry at −45 dBFS and exit at −40 dBFS, plus Silero voice detection. **Other audio without speech** can contain music or noise and is displayed separately. Transcript gaps do not measure silence. Entirely zero recordings raise a recording-system warning.

The spectrum uses NumPy FFT, with bounded previews of up to 30 seconds. The top **5 dominant frequency bins** for each preview time slice are diagnostic values; they never classify silence or avoidance. Darkness represents low energy; bright areas represent stronger energy. The table displays sampled slices from the calculated values.

Verified separate channels allow independent measurements and customer-speech/agent-no-speech intervals. Listening during customer speech is ordinary behavior; the measurement does not prove ghosting. Identical or opposite-phase channels warn that separation needs verification. Partial excerpts and unknown roles remain explicit.

Transcription uses local faster-whisper, multilingual base/int8, beam size 1, voice filtering and word alignment. It processes 120-second owned windows with two seconds of surrounding context. Word ownership prevents publishing look-ahead twice; alignment and words near window boundaries remain estimates requiring listening. Code-switching and noisy telephone audio can reduce accuracy. Text and timestamps are machine estimates, not ground truth.

## Selection, queue and capacity

Every imported recording gets silence analysis. Once a batch is measured, matched spreadsheet review candidates and a deterministic quality sample are transcribed. The initial sample is up to **50 noncandidate recordings per business day**, adjustable in the screen; the included dataset therefore transcribes all ten. An additional longest-quiet threshold is **disabled** until calibrated; the policy API can configure it. No audio measurement changes the workbook flag or creates a disciplinary decision.

Use Cancel / Retry beside a stage. Interrupted jobs resume when the application restarts; completed work is reused. A stage permits at most three attempts before its cause needs correction. New analysis creates immutable evidence versions; a review can only save against the latest recording bundle and current workbook publication.

Import one complete daily cohort before sampling. Repeating an identical CSV/upload is idempotent. Adding more recordings later or changing policy may add selections; already selected/completed work is retained. An unfinished CSV with missing files blocks automatic sampling for that publication until those files arrive or the batch is explicitly finished. Manual transcription remains available.

**5,000 × 640 seconds = about 889 audio hours daily.** This release is a local pilot, not a verified daily-capacity guarantee. Measure representative real calls on the slowest Core i5/16 GB laptop before choosing sample size, completion deadline or laptop count. Record measurement speed, candidate percentage, transcription accuracy, RAM and storage. The queue reports stages and failures; it does not yet predict daily completion time. Start with the sample policy and reduce it if backlog accumulates. See AUDIO_VALIDATION.md for measurements and remaining production checks.

Audio, SQLite metadata, immutable artifacts and review notes are stored below the selected data directory's `audio` folder. No automatic retention/deletion runs. Models are in `runtime/models`; installer environments are machine-specific. The source package excludes imported recordings, runtime stores and reviews.


To benchmark this laptop, run `.venv-audio\Scripts\python.exe audio_benchmark.py C:\path\to\representative-calls`. Add `--transcribe --language es` for a selected transcription cohort. Results save locally under runtime; the benchmark never uploads recordings.

### Voice activity, sound waves and frequency values

Open **Recordings → Inspect**. The voice activity timeline shows detected speech, quiet without speech, and other audio without speech, for all channels and each separate channel. Click the timeline or use its listening slider to seek the original recording. This uses the retained Silero/RMS measurements, not transcript gaps.

Sound waves and the spectrum load automatically for the first available 30 seconds after measurement. Choose another start time or channel, then **Show next 30 seconds**. Choose **K frequencies** (1, 3, 5, 10 or 20; default 5) to control the number of frequency bins. The frequency time slider shows **Top K** (strongest) and **Min K** (weakest) at that slice, with frequency, level and share of non-DC power. Zero-energy slices show no frequency ranking. Equal-power bins are ordered by frequency. Levels use Hann-window FFT power, floored at -100 dB; they are not calibrated loudness readings.

The waveform is bounded to 600 points, spectrum to 192 time slices and 96 display rows; ranking uses the full non-DC FFT bins. These are listening aids; quiet and avoidance are not classified using frequency rankings. Restart RUN.bat after updating the app to load the new preview endpoint.

"""Local-only faster-whisper transcription, bounded original-time windows."""
from __future__ import annotations

import os
import time
from pathlib import Path

from .audio_decode import (AudioError, AnalysisResampler, StrictDecoder, crop_block,
                           file_hash, recording_scope)

_MODEL = None
_MODEL_KEY = None
_MODEL_SHA = None


def local_model(path, threads=2):
    global _MODEL, _MODEL_KEY, _MODEL_SHA
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    path = Path(path).resolve()
    if not all((path / name).is_file() for name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")):
        raise AudioError("The local multilingual model is incomplete. Run INSTALL_AUDIO.bat; daily use never downloads a model.")
    key = str(path), threads
    if _MODEL_KEY != key:
        import json
        manifest_path = Path(__file__).resolve().parents[1] / 'audio_model.source.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        for name, expected in manifest['files'].items():
            if file_hash(path / name) != expected['sha256']:
                raise AudioError('Local model integrity check failed. Run CHECK_AUDIO.bat.')
        from faster_whisper import WhisperModel
        _MODEL = WhisperModel(str(path), device="cpu", compute_type="int8", cpu_threads=threads,
                              num_workers=1, local_files_only=True)
        _MODEL_KEY = key
        _MODEL_SHA = manifest['files']['model.bin']['sha256']
    return _MODEL


def transcribe(path, options=None, progress=None):
    import numpy as np
    from importlib.metadata import version
    options = options or {}
    language = options.get("language", "auto")
    if language not in {"auto", "en", "es"}:
        raise AudioError("Choose automatic, English or Spanish transcription")
    model_path = Path(options.get("model_path") or Path(__file__).resolve().parents[1] / "runtime/models/whisper-base")
    threads = options.get("cpu_threads", 2)
    if isinstance(threads, bool) or not isinstance(threads, int) or not 1 <= threads <= 4:
        raise AudioError("Use 1–4 CPU threads")
    model = local_model(model_path, threads)
    decoder = StrictDecoder(path)
    buffers = resampler = history = None
    segments, detected = [], []
    cursor = 0
    # Two seconds of context on each side; only this window's words publish.
    owned, lookahead = 120 * 16000, 2 * 16000
    started = time.perf_counter()
    scope_start = float(options.get("start_seconds", 0))

    def process(final=False):
        nonlocal buffers, cursor, history
        while buffers and (len(buffers[0]) >= owned + lookahead or final and len(buffers[0])):
            length = min(len(buffers[0]), owned + lookahead)
            take = min(owned, length)
            for channel, buffer in enumerate(buffers):
                preceding = len(history[channel])
                input_audio = np.concatenate((history[channel], buffer[:length]))
                found, info = model.transcribe(np.ascontiguousarray(input_audio), task="transcribe",
                                              language=None if language == "auto" else language,
                                              beam_size=1, vad_filter=True, word_timestamps=True, condition_on_previous_text=False)
                detected.append({"channel": channel, "start_seconds": scope_start + cursor/16000,
                                 "language": info.language, "probability": info.language_probability})
                role = "unknown"
                if options.get("channel_layout") == "separate_roles":
                    role = "agent" if channel == options.get("agent_channel") else "customer" if channel == options.get("customer_channel") else "unknown"
                for segment in found:
                    # Own words by midpoint, excluding look-ahead from this window.
                    # Word alignment is also more useful for jumping to speech
                    # than Whisper's sometimes early segment boundary estimates.
                    words = [word for word in (segment.words or []) if preceding / 16000 <= (word.start + word.end) / 2 < (preceding + take) / 16000]
                    if not words:
                        continue
                    groups = []
                    for word in words:
                        if not groups or word.start - groups[-1][-1].end > 1:
                            groups.append([])
                        groups[-1].append(word)
                    for group in groups:
                        text = ''.join(word.word for word in group).strip()
                        if not text:
                            continue
                        segments.append({"start_seconds": scope_start + cursor/16000 + max(0, group[0].start - preceding/16000),
                                         "end_seconds": scope_start + cursor/16000 + min(group[-1].end - preceding/16000, take/16000),
                                         "text": text, "channel": channel, "role": role,
                                         "avg_logprob": segment.avg_logprob, "no_speech_probability": segment.no_speech_prob,
                                         "language": info.language})
            history = [buffer[max(0, take-lookahead):take].copy() for buffer in buffers]
            buffers = [buffer[take:] for buffer in buffers]
            cursor += take
            if progress:
                progress("Transcribing selected speech locally", .5)

    for position, block in decoder:
        rate, channels = decoder.source["sample_rate"], decoder.source["channels"]
        if resampler is None:
            resampler = AnalysisResampler(rate, channels)
            buffers = [np.empty(0, dtype=np.float32) for _ in range(channels)]
            history = [np.empty(0, dtype=np.float32) for _ in range(channels)]
        cropped = crop_block(position, block, options, rate)
        for array in resampler.feed(cropped):
            buffers = [np.concatenate((buf, array[index])) for index, buf in enumerate(buffers)]
            process()
    scope = recording_scope(decoder.source, options)
    for array in resampler.finish():
        buffers = [np.concatenate((buf, array[index])) for index, buf in enumerate(buffers)]
    process(final=True)
    for segment in segments:
        segment["end_seconds"] = min(scope["end_seconds"], segment["end_seconds"])
    segments = sorted((s for s in segments if s["end_seconds"] > s["start_seconds"]), key=lambda s: (s["start_seconds"], s["channel"]))
    return {"schema_version": 1, "source": decoder.source, "scope": scope, "segments": segments,
            "text": " ".join(s["text"] for s in segments), "language_requested": language,
            "language_detection": detected, "model": "base", "compute_type": "int8", "cpu_threads": threads,
            "model_sha256": _MODEL_SHA, "engine_version": version("faster-whisper"),
            "processing_seconds": time.perf_counter() - started,
            "notice": "Generated transcript; verify by listening. Empty text does not establish silence."}

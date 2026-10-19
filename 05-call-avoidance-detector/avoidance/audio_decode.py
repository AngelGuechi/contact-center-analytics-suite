"""Strict, bounded audio decoding. Optional numerical dependencies load on use."""
from __future__ import annotations

import hashlib
import math
import struct
from fractions import Fraction
from pathlib import Path

DECODER_VERSION = "strict-pyav-1"
MAX_DURATION_SECONDS = 7200


class AudioError(ValueError):
    """An audio operation cannot produce trustworthy evidence."""


def finite_number(value, name, *, minimum=0, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AudioError(f"{name} must be a finite number")
    if not math.isfinite(value) or value < minimum or (maximum is not None and value > maximum):
        raise AudioError(f"{name} is outside its allowed range")
    return float(value)


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class StrictDecoder:
    """Yield (native start sample, channels-by-samples float32) blocks.

    Recording time zero is the first decoded sample. Original stream PTS origin
    is retained separately. No damaged frame, discontinuity, rate or channel
    change is skipped. A result may only be published after exhausting this
    iterator: its final source duration and integrity checks are then known.
    """

    def __init__(self, path, *, block_seconds=4, max_duration_seconds=MAX_DURATION_SECONDS,
                 max_bytes=2 * 1024**3):
        self.path = Path(path)
        self.block_seconds = finite_number(block_seconds, "block_seconds", minimum=.05, maximum=30)
        self.max_duration = finite_number(max_duration_seconds, "max_duration_seconds", minimum=.1,
                                          maximum=24 * 3600)
        self.max_bytes = int(max_bytes)
        self.source = {}
        self.complete = False

    def __iter__(self):
        try:
            import av
            import numpy as np
        except ImportError as exc:
            raise AudioError("Audio runtime is missing. Run INSTALL_AUDIO.bat first.") from exc
        if not self.path.is_file():
            raise AudioError("The retained recording is missing")
        initial = self.path.stat()
        if initial.st_size <= 0 or initial.st_size > self.max_bytes:
            raise AudioError("Recording size is outside the configured limit")
        with self.path.open('rb') as handle:
            header = handle.read(48)
        # FFmpeg can silently shorten a truncated PCM WAV's reported duration.
        # Check its container length independently before decoding any samples.
        if header[:4] == b'RIFF' and header[8:12] == b'WAVE':
            declared_bytes = struct.unpack('<I', header[4:8])[0] + 8
            if declared_bytes > initial.st_size:
                raise AudioError('Truncated WAV container; declared bytes are missing')
        if header[:4] == b'RF64' and header[12:16] == b'ds64' and len(header) >= 28:
            if struct.unpack('<Q', header[20:28])[0] + 8 > initial.st_size:
                raise AudioError('Truncated RF64 container; declared bytes are missing')
        sha256 = file_hash(self.path)
        rate = count = samples = emitted = 0
        origin = None
        pending = None
        converter = None
        try:
            with av.open(str(self.path), mode="r") as container:
                streams = list(container.streams.audio)
                if len(streams) != 1:
                    raise AudioError("Exactly one audio stream is required")
                stream = streams[0]
                declared = (float(stream.duration * stream.time_base)
                            if stream.duration is not None and stream.time_base else None)
                for frame in container.decode(stream):
                    if getattr(frame, "is_corrupt", False):
                        raise AudioError("Corrupt audio frame; duration scoring is unavailable")
                    if frame.pts is None or frame.time_base is None:
                        raise AudioError("Audio frame timestamps are missing; continuity cannot be verified")
                    frame_rate = int(frame.sample_rate)
                    frame_channels = len(frame.layout.channels)
                    if not rate:
                        rate, count = frame_rate, frame_channels
                        if rate < 8000 or rate > 192000 or count not in (1, 2):
                            raise AudioError("Only mono/stereo audio at 8–192 kHz is supported")
                        origin = Fraction(frame.pts) * frame.time_base
                        converter = av.AudioResampler(format="fltp", layout=frame.layout.name, rate=rate)
                        pending = np.empty((count, 0), dtype=np.float32)
                        self.source = {"sha256": sha256, "sample_rate": rate, "channels": count,
                                       "codec": stream.codec_context.name,
                                       "timeline_origin_seconds": float(origin),
                                       "declared_duration_seconds": declared}
                    if frame_rate != rate or frame_channels != count:
                        raise AudioError("Audio rate/channel layout changes inside the recording")
                    expected = origin + Fraction(samples, rate)
                    observed = Fraction(frame.pts) * frame.time_base
                    tolerance = max(Fraction(2, rate), Fraction(frame.time_base))
                    if abs(observed - expected) > tolerance:
                        raise AudioError("Audio timestamp gap/overlap; duration scoring is unavailable")
                    if frame.samples <= 0:
                        raise AudioError("Audio frame contains no usable samples")
                    converted = converter.resample(frame)
                    for output in converted:
                        data = output.to_ndarray()
                        if data.shape[0] != count or not np.isfinite(data).all():
                            raise AudioError("Audio contains invalid sample values")
                        pending = np.concatenate((pending, data), axis=1)
                    samples += frame.samples
                    if samples / rate > self.max_duration:
                        raise AudioError("Recording exceeds the configured duration limit")
                    block = max(1, round(self.block_seconds * rate))
                    while pending.shape[1] >= block:
                        yield emitted, np.ascontiguousarray(pending[:, :block])
                        emitted += block
                        pending = pending[:, block:]
                if not rate:
                    raise AudioError("Recording contains no decodable audio")
                for output in converter.resample(None):
                    pending = np.concatenate((pending, output.to_ndarray()), axis=1)
                if emitted + pending.shape[1] != samples:
                    raise AudioError("Native sample conversion changed the recording duration")
                if pending.shape[1]:
                    yield emitted, np.ascontiguousarray(pending)
                duration = samples / rate
                # Encoded formats may include encoder delay/padding in metadata.
                tolerance = 2 / rate if self.source["codec"].startswith("pcm_") else .25
                if declared is not None and abs(declared - duration) > tolerance:
                    raise AudioError("Declared and decoded audio durations disagree")
                self.source.update(samples=samples, duration_seconds=duration)
        except AudioError:
            raise
        except Exception as exc:
            raise AudioError(f"Audio could not be decoded without errors: {exc}") from exc
        final = self.path.stat()
        if (final.st_size, final.st_mtime_ns) != (initial.st_size, initial.st_mtime_ns):
            raise AudioError("Recording changed during analysis")
        self.complete = True


def requested_samples(options, rate):
    start = finite_number(options.get("start_seconds", 0), "start_seconds")
    end = options.get("end_seconds")
    end = finite_number(end, "end_seconds") if end is not None else None
    if end is not None and end <= start:
        raise AudioError("Selected recording range must have positive duration")
    return round(start * rate), round(end * rate) if end is not None else None


def crop_block(start, data, options, rate):
    first, last = requested_samples(options, rate)
    stop = data.shape[1] + start
    left, right = max(first, start), min(stop, last if last is not None else stop)
    return data[:, max(0, left - start):max(0, right - start)] if right > left else data[:, :0]


def recording_scope(source, options):
    first, last = requested_samples(options, source["sample_rate"])
    total = source["samples"]
    last = total if last is None else last
    if first >= last or first >= total or last > total:
        raise AudioError("Selected recording range exceeds the available audio")
    rate = source["sample_rate"]
    return {"start_seconds": first / rate, "end_seconds": last / rate,
            "duration_seconds": (last - first) / rate, "start_sample": first,
            "end_sample": last, "samples": last - first,
            "partial": first != 0 or last != total or options.get("recording_scope") == "partial",
            "call_coverage": "not_inferred"}


class AnalysisResampler:
    """Bounded per-channel 16 kHz copy; its time zero is the selected span."""

    def __init__(self, source_rate, channels, target_rate=16000):
        import av
        self.av = av
        self.rate, self.channels, self.target = source_rate, channels, target_rate
        self.samples = 0
        self.layout = "mono" if channels == 1 else "stereo"
        self.resampler = av.AudioResampler(format="fltp", layout=self.layout, rate=target_rate)

    def feed(self, data):
        if not data.shape[1]:
            return []
        frame = self.av.AudioFrame.from_ndarray(data, format="fltp", layout=self.layout)
        frame.sample_rate = self.rate
        frame.pts = self.samples
        frame.time_base = Fraction(1, self.rate)
        self.samples += data.shape[1]
        return [result.to_ndarray() for result in self.resampler.resample(frame)]

    def finish(self):
        return [result.to_ndarray() for result in self.resampler.resample(None)]

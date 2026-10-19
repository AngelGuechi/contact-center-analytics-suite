"""Bounded, original-timeline energy and voice measurements; no ASR dependency."""
from __future__ import annotations

import math
import time
from pathlib import Path

from .audio_decode import (AudioError, AnalysisResampler, StrictDecoder, crop_block,
                           file_hash, finite_number, recording_scope)

VERSION = "audio-measurement-1"
DEFAULTS = {"quiet_enter_dbfs": -45.0, "quiet_exit_dbfs": -40.0,
            "vad_threshold": .5, "vad_gap_ms": 100, "frame_ms": 20, "hop_ms": 10}


def merge(intervals):
    output = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if output and start <= output[-1][1]:
            output[-1][1] = max(end, output[-1][1])
        else:
            output.append([int(start), int(end)])
    return output


def intersect(a, b):
    a, b = merge(a), merge(b)
    out, i, j = [], 0, 0
    while i < len(a) and j < len(b):
        left, right = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if right > left:
            out.append([left, right])
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return merge(out)


def complement(intervals, end):
    result, previous = [], 0
    for start, stop in merge(intervals):
        start, stop = max(0, start), min(end, stop)
        if start > previous:
            result.append([previous, start])
        previous = max(previous, stop)
    if previous < end:
        result.append([previous, end])
    return result


class EnergyFrames:
    """Hop ownership avoids double counting overlapping RMS windows."""
    def __init__(self, rate, config):
        import numpy as np
        self.rate, self.config = rate, config
        self.window = max(1, round(rate * config["frame_ms"] / 1000))
        self.hop = max(1, round(rate * config["hop_ms"] / 1000))
        self.pending = np.empty(0, dtype=np.float32)
        self.cursor = self.total = 0
        self.quiet, self.intervals = False, []
        self.zero_samples = self.clipped_samples = 0

    def feed(self, data, final=False):
        import numpy as np
        self.total += len(data)
        self.zero_samples += int(np.count_nonzero(data == 0))
        self.clipped_samples += int(np.count_nonzero(np.abs(data) >= .999))
        self.pending = np.concatenate((self.pending, data))
        # Bound every call to one decoder block. Vectorized RMS, sequential hysteresis.
        n = max(0, (len(self.pending) - self.window) // self.hop + 1)
        if n:
            windows = np.lib.stride_tricks.sliding_window_view(self.pending, self.window)[::self.hop][:n]
            rms = np.sqrt(np.mean(np.square(windows, dtype=np.float64), axis=1))
            levels = 20 * np.log10(np.maximum(rms, 1e-6))
            for level in levels:
                self._frame(float(level), self.hop)
            consumed = n * self.hop
            self.pending = self.pending[consumed:]
        if final:
            while len(self.pending):
                rms = math.sqrt(float(np.mean(np.square(self.pending[:self.window], dtype=np.float64))))
                length = min(self.hop, len(self.pending))
                self._frame(20 * math.log10(max(rms, 1e-6)), length)
                self.pending = self.pending[length:]

    def _frame(self, dbfs, length):
        if dbfs <= self.config["quiet_enter_dbfs"]:
            self.quiet = True
        elif dbfs >= self.config["quiet_exit_dbfs"]:
            self.quiet = False
        if self.quiet:
            if self.intervals and self.intervals[-1][1] == self.cursor:
                self.intervals[-1][1] += length
            else:
                self.intervals.append([self.cursor, self.cursor + length])
        self.cursor += length


class StreamingVAD:
    """Stateful Silero v6 adapter. Model states and 64-sample context cross chunks.

    Boundary rules follow faster-whisper's MIT-licensed no-pad segmentation;
    model state is reset only at construction (one adapter per recording/channel).
    """
    def __init__(self, config):
        import numpy as np
        from faster_whisper.vad import get_vad_model
        self.session = get_vad_model().session
        self.config = config
        self.h = np.zeros((1, 1, 128), dtype=np.float32)
        self.c = np.zeros_like(self.h)
        self.context = np.zeros(64, dtype=np.float32)
        self.pending = np.empty(0, dtype=np.float32)
        self.cursor = self.total = 0
        self.start = self.temp_end = None
        self.intervals = []

    def feed(self, data, final=False):
        import numpy as np
        self.total += len(data)
        self.pending = np.concatenate((self.pending, data))
        count = len(self.pending) // 512
        if final and len(self.pending) % 512:
            self.pending = np.pad(self.pending, (0, 512 - len(self.pending) % 512))
            count += 1
        if count:
            windows = self.pending[:count * 512].reshape(count, 512)
            contexts = np.vstack((self.context, windows[:-1, -64:]))
            inputs = np.ascontiguousarray(np.concatenate((contexts, windows), axis=1))
            probabilities, self.h, self.c = self.session.run(None, {"input": inputs, "h": self.h, "c": self.c})
            self.context = windows[-1, -64:].copy()
            for probability in np.asarray(probabilities).reshape(-1):
                p = float(probability)
                if p >= self.config["vad_threshold"]:
                    self.temp_end = None
                    if self.start is None:
                        self.start = self.cursor
                elif p < max(.01, self.config["vad_threshold"] - .15) and self.start is not None:
                    if self.temp_end is None:
                        self.temp_end = self.cursor
                    if self.cursor - self.temp_end >= self.config["vad_gap_ms"] * 16:
                        if self.temp_end > self.start:
                            self.intervals.append([self.start, self.temp_end])
                        self.start = self.temp_end = None
                self.cursor += 512
            self.pending = self.pending[count * 512:]
        if final and self.start is not None:
            if self.total > self.start:
                self.intervals.append([self.start, self.total])
            self.start = self.temp_end = None


def settings(options):
    config = {**DEFAULTS, **{key: options[key] for key in DEFAULTS if key in options}}
    for key in ("quiet_enter_dbfs", "quiet_exit_dbfs"):
        finite_number(config[key], key, minimum=-120, maximum=0)
    if config["quiet_exit_dbfs"] <= config["quiet_enter_dbfs"]:
        raise AudioError("Quiet exit level must exceed its entry level")
    finite_number(config["vad_threshold"], "vad_threshold", minimum=.01, maximum=.99)
    finite_number(config["vad_gap_ms"], "vad_gap_ms", minimum=32, maximum=2000)
    # Fixed ownership convention is part of VERSION; do not accept arbitrary frame shapes.
    if config["frame_ms"] != 20 or config["hop_ms"] != 10:
        raise AudioError("This measurement version uses 20 ms frames and a 10 ms hop")
    return config


def public_intervals(intervals, rate, offset, total):
    return [{"start_sample": a, "end_sample": b,
             "start_seconds": offset + a / rate, "end_seconds": offset + b / rate,
             "duration_seconds": (b - a) / rate,
             "position": "leading" if a == 0 else "trailing" if b == total else "internal"}
            for a, b in merge(intervals)]


def metrics(speech, low_energy, total, rate, offset):
    speech = intersect(speech, [[0, total]])
    no_speech = complement(speech, total)
    quiet = intersect(no_speech, low_energy)
    other = intersect(no_speech, complement(quiet, total))
    duration = total / rate
    totals = {"duration_seconds": duration}
    sets = {"speech": speech, "no_speech": no_speech, "quiet": quiet, "other_audio": other}
    result = {}
    for name, intervals in sets.items():
        seconds = sum(b - a for a, b in intervals) / rate
        totals[name + "_seconds"] = seconds
        totals[name + "_ratio"] = seconds / duration if duration else None
        totals["longest_" + name + "_seconds"] = max((b-a for a,b in intervals), default=0) / rate
        result[name + "_intervals"] = public_intervals(intervals, rate, offset, total)
    return {"totals": totals, **result}


def measure(path, options=None, progress=None):
    import numpy as np
    import av, onnxruntime
    from importlib.metadata import version
    from faster_whisper.utils import get_assets_path
    options = options or {}
    config = settings(options)
    started = time.perf_counter()
    decoder = StrictDecoder(path)
    energies = vads = resampler = None
    cross = np.zeros(3, dtype=np.float64)
    for _, data in decoder:
        rate, channels = decoder.source["sample_rate"], decoder.source["channels"]
        if energies is None:
            if options.get("channel_layout") == "mono" and channels != 1:
                raise AudioError("CSV declares mono but the recording has two channels")
            energies = [EnergyFrames(rate, config) for _ in range(channels)]
            vads = [StreamingVAD(config) for _ in range(channels)]
            resampler = AnalysisResampler(rate, channels)
        cropped = crop_block(_, data, options, rate)
        for index, energy in enumerate(energies):
            energy.feed(cropped[index])
        if channels == 2 and cropped.size:
            cross += [np.dot(cropped[0].astype(np.float64), cropped[0]),
                      np.dot(cropped[1].astype(np.float64), cropped[1]),
                      np.dot(cropped[0].astype(np.float64), cropped[1])]
        for block in resampler.feed(cropped):
            for index, vad in enumerate(vads):
                vad.feed(block[index])
        if progress:
            progress("Measuring speech and quiet periods", min(.95, (_ + data.shape[1]) / rate / max(1, decoder.source.get("declared_duration_seconds") or 7200)))
    scope = recording_scope(decoder.source, options)
    total, rate, offset = scope["samples"], decoder.source["sample_rate"], scope["start_seconds"]
    for block in resampler.finish():
        for index, vad in enumerate(vads):
            vad.feed(block[index])
    speech_sets, energy_sets, channel_results = [], [], []
    for index, (energy, vad) in enumerate(zip(energies, vads)):
        energy.feed(np.empty(0, dtype=np.float32), final=True)
        vad.feed(np.empty(0, dtype=np.float32), final=True)
        speech = merge([[round(a * rate / 16000), min(total, round(b * rate / 16000))] for a,b in vad.intervals])
        speech_sets.append(speech)
        energy_sets.append(energy.intervals)
        role = "unknown"
        if options.get("channel_layout") == "separate_roles":
            if index == options.get("agent_channel"):
                role = "agent"
            elif index == options.get("customer_channel"):
                role = "customer"
        channel_results.append({"channel": index, "role": role, "digital_zero_samples": energy.zero_samples,
                                "clipped_sample_ratio": energy.clipped_samples / total,
                                **metrics(speech, energy.intervals, total, rate, offset)})
    low = energy_sets[0]
    for intervals in energy_sets[1:]:
        low = intersect(low, intervals)
    conversation = metrics(merge([item for intervals in speech_sets for item in intervals]), low, total, rate, offset)
    warnings = []
    if all(item["digital_zero_samples"] == total for item in channel_results):
        warnings.append("All samples are digitally zero; check the recording system before interpreting quiet.")
    if any(item["clipped_sample_ratio"] > .01 for item in channel_results):
        warnings.append("Clipping affects more than 1% of samples on a channel.")
    if len(energy_sets) == 2 and cross[0] > 0 and cross[1] > 0:
        correlation = float(cross[2] / math.sqrt(cross[0] * cross[1]))
        if abs(correlation) > .995:
            warnings.append("Channels are nearly identical or opposite-phase; verify speaker separation.")
    roles = options.get("channel_layout") == "separate_roles"
    if roles:
        agent, customer = options.get("agent_channel"), options.get("customer_channel")
        if agent not in range(len(vads)) or customer not in range(len(vads)) or agent == customer:
            raise AudioError("Verified channel roles do not match available distinct channels")
        intervals = intersect(speech_sets[customer], complement(speech_sets[agent], total))
        conversation["customer_speech_agent_no_speech_intervals"] = public_intervals(intervals, rate, offset, total)
        warnings.append("Agent absence during customer speech can be ordinary listening; roles depend on the supplied channel map.")
    else:
        warnings.append("Speaker roles are unknown; recording-level quiet cannot identify which party stayed silent.")
    totals = conversation["totals"]
    return {"schema_version": 1, "algorithm_version": VERSION, "source": decoder.source, "scope": scope,
            "settings": config, "channels": channel_results, "conversation": conversation,
            "warnings": warnings, "roles_verified_by_import": roles,
            "explanation": f"In the available {total/rate:.1f} seconds, {totals['quiet_seconds']:.1f} seconds were quiet with no detected speech. {totals['other_audio_seconds']:.1f} seconds contained other audio without detected speech. These measurements require listening and review.",
            "provenance": {"numpy": np.__version__, "av": av.__version__, "onnxruntime": onnxruntime.__version__,
                           "faster_whisper": version("faster-whisper"),
                           "vad_sha256": file_hash(Path(get_assets_path()) / "silero_vad_v6.onnx")},
            "processing_seconds": time.perf_counter() - started}


def preview(path, options=None, progress=None):
    """At most 30 seconds of spectrum, 192 columns and 96 rows, plus waveform."""
    import numpy as np
    options = options or {}
    k = options.get("preview_k", 5)
    if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= 20:
        raise AudioError("Choose K between 1 and 20")
    start = finite_number(options.get("preview_start", 0), "preview_start")
    end = finite_number(options.get("preview_end", start + 30), "preview_end")
    if not start < end <= start + 30.001:
        raise AudioError("Choose a preview range of at most 30 seconds")
    channel = options.get("preview_channel", 0)
    if isinstance(channel, bool) or not isinstance(channel, int) or not 0 <= channel <= 1:
        raise AudioError("Choose Channel 1 or Channel 2")
    decoder = StrictDecoder(path)
    pieces = []
    for position, block in decoder:
        if channel >= block.shape[0]:
            raise AudioError("This recording does not have that channel")
        data = crop_block(position, block, {"start_seconds": start, "end_seconds": end}, decoder.source["sample_rate"])
        if data.size:
            pieces.append(data[channel])
    scope = recording_scope(decoder.source, {"start_seconds": start, "end_seconds": end})
    audio = np.concatenate(pieces)
    rate = decoder.source["sample_rate"]
    slices = np.array_split(audio, min(600, len(audio)))
    waveform = [[float(np.min(chunk)), float(np.max(chunk))] for chunk in slices]
    window = min(2048, max(256, 2**int(math.ceil(math.log2(rate * .032)))))
    hann = np.hanning(window)
    positions = np.linspace(0, max(0, len(audio)-window), min(192, max(1, len(audio)//window)), dtype=int)
    rows = 96
    frequency_indices = np.linspace(1, window//2, rows, dtype=int)
    spectrum, top_k, min_k = [], [], []
    for position in positions:
        chunk = audio[position:position+window]
        if len(chunk) < window:
            chunk = np.pad(chunk, (0, window-len(chunk)))
        power = np.abs(np.fft.rfft(chunk * hann, norm="forward")) ** 2
        db = np.maximum(-100, 10*np.log10(np.maximum(power, 1e-10)))
        spectrum.append(db[frequency_indices].round(1).tolist())
        total = float(np.sum(power[1:]))
        for target, direction in ((top_k, -1), (min_k, 1)):
            ranked = sorted(range(1, len(power)), key=lambda i: (direction*float(power[i]), i))[:k] if total > 0 else []
            target.append({"time_seconds": start + int(position)/rate,
                           "frequencies_hz": [round(i*rate/window, 1) for i in ranked],
                           "levels_db": [round(float(db[i]), 1) for i in ranked],
                           "power_ratio": float(sum(power[i] for i in ranked)/total) if total > 0 else None})
    return {"source_sha256": decoder.source['sha256'], "start_seconds": scope["start_seconds"], "end_seconds": scope["end_seconds"],
            "channel": channel, "waveform": waveform, "spectrum": spectrum,
            "frequencies_hz": [round(int(i)*rate/window, 1) for i in frequency_indices],
            "db_min": -100, "db_max": 0, "k": k, "top_k": top_k, "min_k": min_k,
            "note": "Dominant frequencies are a listening aid, not a silence or avoidance classifier."}

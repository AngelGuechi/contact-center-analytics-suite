"""Run in .venv-audio; base test runs explicitly skip optional inference."""
import importlib.util
import tempfile
import unittest
import wave
import json
import subprocess
import sys
from pathlib import Path

from avoidance.audio_decode import AudioError, StrictDecoder
from avoidance.audio_analysis import EnergyFrames, DEFAULTS, measure, preview

AVAILABLE = all(importlib.util.find_spec(name) for name in ('numpy', 'av', 'onnxruntime', 'faster_whisper'))
PROJECT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(AVAILABLE, 'Optional audio environment required')
class AudioEngineTests(unittest.TestCase):
    def test_digital_zero_exact_duration_and_no_speech(self):
        result = measure(PROJECT / 'recordings/Calls/70003503.wav')
        self.assertEqual(result['conversation']['totals']['quiet_seconds'], 10)
        self.assertEqual(result['conversation']['totals']['speech_seconds'], 0)
        self.assertTrue(any('digitally zero' in w for w in result['warnings']))

    def test_music_has_other_audio_and_is_not_all_quiet(self):
        result = measure(PROJECT / 'recordings/Calls/70003511.wav')
        totals = result['conversation']['totals']
        self.assertGreater(totals['other_audio_seconds'], 10)
        self.assertLess(totals['quiet_seconds'], totals['no_speech_seconds'] - 10)
        self.assertAlmostEqual(totals['speech_seconds'] + totals['quiet_seconds'] + totals['other_audio_seconds'], 45, places=4)

    def test_opposite_phase_stereo_keeps_speech(self):
        result = measure(PROJECT / 'recordings/Calls/70003513.wav')
        self.assertGreater(result['conversation']['totals']['speech_seconds'], 3)
        self.assertTrue(any('opposite-phase' in w for w in result['warnings']))

    def test_partial_range_preserves_original_timestamps(self):
        result = measure(PROJECT / 'recordings/Calls/70003510.wav', {'start_seconds': 10, 'end_seconds': 30})
        self.assertEqual(result['scope']['duration_seconds'], 20)
        self.assertTrue(result['scope']['partial'])
        self.assertGreaterEqual(result['conversation']['quiet_intervals'][0]['start_seconds'], 10)

    def test_verified_channels_and_invalid_roles(self):
        path = PROJECT / 'recordings/Calls/70003509.wav'
        result = measure(path, {'channel_layout': 'separate_roles', 'agent_channel': 0, 'customer_channel': 1})
        self.assertTrue(result['roles_verified_by_import'])
        self.assertTrue(result['conversation']['customer_speech_agent_no_speech_intervals'])
        with self.assertRaises(AudioError):
            measure(path, {'channel_layout': 'separate_roles', 'agent_channel': 0, 'customer_channel': 2})

    def test_preview_bounded_and_zero_energy(self):
        result = preview(PROJECT / 'recordings/Calls/70003503.wav', {'preview_start': 0, 'preview_end': 10})
        self.assertLessEqual(len(result['waveform']), 600)
        self.assertLessEqual(len(result['spectrum']), 192)
        self.assertEqual(len(result['spectrum'][0]), 96)
        self.assertTrue(all(item['power_ratio'] is None for item in result['top_k']))
        self.assertTrue(all(not item['frequencies_hz'] for item in result['min_k'] + result['top_k']))
        with self.assertRaises(AudioError):
            preview(PROJECT / 'recordings/Calls/70003503.wav', {'preview_start': 0, 'preview_end': 31})

    def test_frequency_ranks_match_tone_and_k_limits(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'tone.wav'
            rate = 16000
            samples = (.5 * np.sin(2 * np.pi * 1000 * np.arange(rate) / rate) * 32767).astype('<i2')
            with wave.open(str(path), 'wb') as output:
                output.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
                output.writeframes(samples.tobytes())
            result = preview(path, {'preview_end': 1, 'preview_k': 3})
            self.assertEqual(result['k'], 3)
            for top, low in zip(result['top_k'], result['min_k']):
                self.assertEqual(top['frequencies_hz'][0], 1000)
                self.assertEqual(len(low['frequencies_hz']), 3)
                self.assertEqual(top['levels_db'], sorted(top['levels_db'], reverse=True))
                self.assertEqual(low['levels_db'], sorted(low['levels_db']))
                self.assertGreater(top['power_ratio'], low['power_ratio'])
            for invalid in (0, 21, True, 1.5):
                with self.assertRaises(AudioError):
                    preview(path, {'preview_end': 1, 'preview_k': invalid})

    def test_energy_chunk_size_does_not_change_results(self):
        import numpy as np
        samples = np.r_[np.zeros(22050), np.ones(22050) * .1, np.zeros(22050)].astype(np.float32)
        results = []
        for size in (137, 88200):
            tracker = EnergyFrames(22050, DEFAULTS)
            for start in range(0, len(samples), size):
                tracker.feed(samples[start:start+size])
            tracker.feed(np.empty(0, dtype=np.float32), final=True)
            results.append(tracker.intervals)
            self.assertEqual(tracker.cursor, len(samples))
        self.assertEqual(*results)

    def test_truncated_wav_never_finishes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'broken.wav'
            original = (PROJECT / 'recordings/Calls/70003503.wav').read_bytes()
            path.write_bytes(original[:-20000])
            decoder = StrictDecoder(path)
            with self.assertRaises(AudioError):
                list(decoder)
            self.assertFalse(decoder.complete)

    def test_worker_rejects_changed_source_identity(self):
        request = {'job_id': 'integrity', 'operation': 'measure', 'path': str(PROJECT / 'recordings/Calls/70003503.wav'), 'options': {'expected_sha256': 'wrong'}}
        result = subprocess.run([sys.executable, '-m', 'avoidance.audio_worker'], cwd=PROJECT,
                                input=json.dumps(request) + '\n', text=True, capture_output=True, timeout=20, check=True)
        events = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(events[-1]['type'], 'error')
        self.assertIn('bytes changed', events[-1]['message'])
        self.assertFalse(any(event['type'] == 'result' for event in events))

    @unittest.skipUnless((PROJECT / 'runtime/models/whisper-base/model.bin').is_file(), 'Local model required; tests never download it')
    def test_actual_spanish_and_zero_transcription(self):
        from avoidance.transcription import transcribe
        result = transcribe(PROJECT / 'recordings/Calls/70003502.wav', {'language': 'es'})
        self.assertIn('gracias', result['text'].lower())
        self.assertTrue(all(0 <= row['start_seconds'] < row['end_seconds'] <= 10 for row in result['segments']))
        zero = transcribe(PROJECT / 'recordings/Calls/70003503.wav')
        self.assertEqual(zero['segments'], [])
        self.assertEqual(zero['text'], '')


if __name__ == '__main__':
    unittest.main()

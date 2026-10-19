"""Audio inventory safety and immutable evidence, without optional libraries."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from avoidance.audio_store import AudioStore
from avoidance.recordings import parse_csv, folder_csv


class RecordingCSVTests(unittest.TestCase):
    def setUp(self):
        self.dataset = {'transactions': [dict(transaction_id='001', connection_id='C1', agent_id='A', business_date='2026-10-06', duration_seconds=10), dict(transaction_id='002', connection_id='C1', agent_id='B', business_date='2026-10-06', duration_seconds=20)]}

    def parse(self, rows):
        return parse_csv(('recording_file,call_id,call_id_type,recording_scope\n' + rows).encode(), self.dataset, 'p')

    def test_leading_zero_and_partial_kept(self):
        result = self.parse('Calls/a.wav,001,transaction,partial\n')
        self.assertEqual(result['files'][0]['links'][0]['transaction_ids'], ['001'])
        self.assertEqual(result['files'][0]['options']['recording_scope'], 'partial')

    def test_connection_not_guessed_to_agent(self):
        result = self.parse('a.wav,C1,connection,transaction_leg\nb.wav,C1,connection,whole_connection\n')
        self.assertEqual([r['links'][0]['state'] for r in result['files']], ['ambiguous', 'context'])

    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError):
            self.parse('../outside.wav,001,transaction,partial\n')

    def test_unmatched_remains_visible(self):
        result = self.parse('a.wav,999,transaction,partial\n')
        self.assertEqual(result['files'][0]['links'][0]['state'], 'unmatched')

    def test_nonfinite_offset_rejected(self):
        with self.assertRaises(ValueError):
            parse_csv(b'recording_file,call_id,call_id_type,recording_scope,audio_start_seconds\na.wav,001,transaction,partial,nan\n', self.dataset, 'p')

    def test_excel_utf16_semicolon_csv(self):
        text = 'sep=;\nrecording_file;call_id;call_id_type;recording_scope\nCalls/español.wav;001;transaction;partial\n'
        result = parse_csv(text.encode('utf-16'), self.dataset, 'p')
        self.assertEqual(result['files'][0]['recording_file'], 'Calls/español.wav')
        self.assertEqual(result['files'][0]['links'][0]['transaction_ids'], ['001'])

    def test_windows_csv_with_accents(self):
        text = 'recording_file,call_id,call_id_type,recording_scope\nCalls/español.wav,001,transaction,partial\n'
        result = parse_csv(text.encode('cp1252'), self.dataset, 'p')
        self.assertEqual(result['files'][0]['recording_file'], 'Calls/español.wav')

    def test_excel_file_is_not_misreported_as_encoding_problem(self):
        with self.assertRaisesRegex(ValueError, 'not a recording map CSV'):
            parse_csv(b'PK\x03\x04binary workbook', self.dataset, 'p')

    def test_nested_audio_folder_exact_ids_only(self):
        result = parse_csv(folder_csv(['2026/10/06/001.wav', '2026/10/07/phone-001.mp3']), self.dataset, 'p')
        self.assertEqual(result['files'][0]['links'][0]['transaction_ids'], ['001'])
        self.assertEqual(result['files'][1]['links'][0]['state'], 'unmatched')
        self.assertEqual(result['files'][0]['options']['recording_scope'], 'partial')

    def test_folder_map_rejects_unsafe_and_duplicate_paths(self):
        for paths in (['../outside.wav'], ['001.wav', '001.wav'], ['call.xlsx']):
            with self.assertRaises(ValueError):
                folder_csv(paths)


class AudioStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.audio = AudioStore(Path(self.temp.name))
        dataset = {'transactions': [dict(transaction_id='001', connection_id='C', agent_id='A', business_date='2026-10-06', duration_seconds=10)]}
        csv = b'recording_file,call_id,call_id_type,recording_scope\na.wav,001,transaction,transaction_leg\n'
        batch = self.audio.create_import('p', True, csv, parse_csv(csv, dataset, 'p'))
        self.original = self.audio.root / 'originals/source.wav'
        self.original.parent.mkdir()
        self.original.write_bytes(b'source')
        self.recording = self.audio.register_recording(batch['id'], 'a.wav', hashlib.sha256(b'source').hexdigest(), 6, self.original, {'001'})

    def tearDown(self):
        self.temp.cleanup()

    def complete(self, operation):
        job = self.audio.enqueue(self.recording['id'], operation, {})
        claimed = self.audio.claim('owner', True)
        self.assertEqual(job['id'], claimed['id'])
        self.assertTrue(self.audio.complete(job['id'], 'owner', {'operation': operation}))
        return self.audio.recording(self.recording['id'])

    def test_cached_job_and_original_preserved(self):
        first = self.complete('measure')
        self.audio.enqueue(first['id'], 'measure', {})
        self.assertIsNone(self.audio.claim('owner', True))
        self.assertEqual(self.original.read_bytes(), b'source')

    def test_late_cancelled_output_never_attaches(self):
        job = self.audio.enqueue(self.recording['id'], 'measure', {})
        self.audio.claim('owner', True)
        self.audio.cancel(job['id'])
        self.assertFalse(self.audio.complete(job['id'], 'owner', {'fake': 'late'}))
        self.assertIsNone(self.audio.recording(self.recording['id'])['bundle_id'])

    def test_transcript_replaces_bundle_and_stale_review_rejected(self):
        measured = self.complete('measure')
        final = self.complete('transcribe')
        self.assertNotEqual(measured['bundle_id'], final['bundle_id'])
        with self.assertRaises(ValueError):
            self.audio.save_review(final['id'], measured['bundle_id'], 'p', 'p', 'Needs review', 'Reviewer', 'Listen again')
        result = self.audio.save_review(final['id'], final['bundle_id'], 'p', 'p', 'Legitimate interaction', 'Reviewer', 'Customer asked for time')
        self.assertEqual(result['bundle_id'], final['bundle_id'])
        self.assertEqual(self.audio.bundle(measured['bundle_id'])['transcript_id'], None)

    def test_changed_publication_rejects_review(self):
        measured = self.complete('measure')
        with self.assertRaises(ValueError):
            self.audio.save_review(measured['id'], measured['bundle_id'], 'p', 'new-p', 'Needs review', 'Reviewer', 'Listen')

    def test_recovery_requeues_interrupted_stage(self):
        job = self.audio.enqueue(self.recording['id'], 'measure', {})
        self.audio.claim('old', True)
        self.audio.recover()
        self.assertEqual(self.audio.job(job['id'])['state'], 'queued')
        self.assertEqual(self.audio.claim('new', True)['owner'], 'new')

    def test_selection_is_idempotent(self):
        policy = self.audio.policy()
        for _ in range(2):
            self.audio.mark_selected(self.recording['id'], 'random_quality_sample', policy, '2026-10-06')
        self.assertEqual(self.audio.recording(self.recording['id'])['selection_reasons'].count('random_quality_sample'), 1)

    def test_sample_and_threshold_validation(self):
        for bad in (True, -1, 5001, 2.5):
            with self.assertRaises(ValueError):
                self.audio.set_policy({'random_sample_size': bad})
        with self.assertRaises(ValueError):
            self.audio.set_policy({'quiet_candidate_seconds': float('nan')})


if __name__ == '__main__':
    unittest.main()

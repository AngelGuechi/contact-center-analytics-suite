"""One bounded, restartable subprocess owns local audio inference.

The base application imports only the standard library here. Inference libraries
and the cached model live in the optional audio environment.
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

from .audio_store import AudioStore
from .recordings import MAX_FILE_BYTES, parse_csv, validate_signature
from .store import fingerprint, safe_relative
from setup import RuntimeLock


class AudioService:
    def __init__(self, core, project):
        self.core, self.project = core, Path(project)
        self.store = AudioStore(core.root)
        self.python = self.project / '.venv-audio' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        self.model = self.project / 'runtime/models/whisper-base'
        self.owner = uuid.uuid4().hex
        self.stop_event = threading.Event()
        self.process = None
        self.thread = None
        self.worker_error = None
        self.selection_epochs = {}
        self.coordinator_lock = None
        engine_files = ('audio_decode.py', 'audio_analysis.py', 'transcription.py', 'audio_worker.py')
        self.engine = fingerprint({**{name: hashlib.sha256((self.project / 'avoidance' / name).read_bytes()).hexdigest() for name in engine_files},
                                   'pins': hashlib.sha256((self.project / 'requirements-audio.txt').read_bytes()).hexdigest(),
                                   'model': hashlib.sha256((self.project / 'audio_model.source.json').read_bytes()).hexdigest()})

    def readiness(self):
        marker = self.project / '.venv-audio/audio_environment.json'
        try:
            saved = json.loads(marker.read_text(encoding='utf-8'))
            ready = self.python.is_file() and saved['project'] == str(self.project) and saved['python'] == str(self.python) and saved['requirements_sha256'] == hashlib.sha256((self.project / 'requirements-audio.txt').read_bytes()).hexdigest()
        except (OSError, ValueError, KeyError):
            ready = False
        model_ready = all((self.model / name).is_file() for name in ('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt'))
        return {'ready': ready, 'model_ready': model_ready,
                'message': ('Local CPU audio worker ready' if model_ready else 'Silence analysis ready; transcription model missing. Run INSTALL_AUDIO.bat.') if ready else 'Run INSTALL_AUDIO.bat once to enable audio analysis.',
                'profile': 'CPU · int8 · multilingual base · 2 threads', 'worker_error': self.worker_error}

    def status(self):
        return {**self.readiness(), **self.store.stage_status(), 'policy': self.store.policy(),
                'capacity_note': '5,000 calls × 640 seconds = 889 audio hours/day. Capacity requires a benchmark on the target Core i5.'}

    def start(self):
        self.coordinator_lock = RuntimeLock(self.store.root / 'coordinator.lock')
        try:
            self.coordinator_lock.__enter__()
        except Exception:
            self.coordinator_lock = None
            self.worker_error = 'Another app owns the audio worker for this data folder. Close it before starting processing here.'
            return
        self.store.recover()
        with self.store.connect() as db:
            publications = [r[0] for r in db.execute('SELECT DISTINCT publication_id FROM recordings')]
        for publication_id in publications:
            self.select(publication_id)
        self.thread = threading.Thread(target=self.run, name='audio-coordinator', daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
        self.kill_worker()
        if self.thread:
            self.thread.join(timeout=2)
        if self.coordinator_lock:
            self.coordinator_lock.__exit__(None, None, None)
            self.coordinator_lock = None

    def kill_worker(self):
        process, self.process = self.process, None
        if process:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            for stream in (process.stdin, process.stdout):
                if stream:
                    stream.close()

    def worker(self):
        if self.process and self.process.poll() is None:
            return self.process, self.events
        self.kill_worker()
        self.events = queue.Queue(maxsize=256)
        env = {**os.environ, 'HF_HUB_OFFLINE': '1', 'HF_HUB_DISABLE_TELEMETRY': '1', 'OMP_NUM_THREADS': '2'}
        self.process = subprocess.Popen([str(self.python), '-m', 'avoidance.audio_worker'], cwd=self.project,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            encoding='utf-8', env=env, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        process, events = self.process, self.events
        def read():
            try:
                for line in process.stdout:
                    events.put(json.loads(line))
            except Exception as exc:
                events.put({'type': 'error', 'message': str(exc)})
            finally:
                events.put({'type': 'exited', 'message': 'Audio worker stopped unexpectedly.'})
        threading.Thread(target=read, name='audio-output', daemon=True).start()
        return process, events

    def options(self, recording, operation, extra=None):
        return {**recording['options'], 'engine_signature': self.engine, 'cpu_threads': 2, 'expected_sha256': recording['sha256'],
                'model_path': str(self.model), **(extra or {})}

    def enqueue(self, recording_id, operation, extra=None):
        recording = self.store.recording(recording_id)
        return self.store.enqueue(recording_id, operation, self.options(recording, operation, extra), 10 if operation == 'preview' else 0)

    def import_csv(self, content, publication_id=None):
        with self.core._lock:
            pub, dataset, _ = self.core._inspection_context(publication_id)
            parsed = parse_csv(content, dataset, pub['id'])
            return self.store.create_import(pub['id'], bool(pub['report'].get('synthetic')), content, parsed)

    def candidate_ids(self, publication_id):
        with self.core._lock:
            pub, _, _ = self.core._inspection_context(publication_id)
            return {str(identifier) for row in pub['report'].get('daily', {}).get('slices', []) if row.get('flagged')
                    for identifier in row.get('signal_transaction_ids', [])}

    def retain(self, import_id, filename, temporary):
        entry = self.store.import_entry(import_id, filename)
        validate_signature(temporary)
        size = temporary.stat().st_size
        if not 0 < size <= MAX_FILE_BYTES:
            raise ValueError('Recording must be nonempty and smaller than 2 GB.')
        with temporary.open('rb') as stream:
            sha = hashlib.file_digest(stream, 'sha256').hexdigest()
        destination = self.store.root / 'originals' / sha / ('source' + temporary.suffix.lower())
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            os.replace(temporary, destination)
        recording = self.store.register_recording(import_id, filename, sha, size, destination, self.candidate_ids(entry['publication_id']))
        self.enqueue(recording['id'], 'measure')
        return recording

    def fixtures(self):
        with self.core._lock:
            pub, _, _ = self.core._inspection_context(None)
            if not pub['report'].get('synthetic'):
                raise ValueError('Generated recordings require a generated workbook dataset. Use a separate CA_DATA_DIR for operational data.')
            publication_id = pub['id']
        folder = self.project / 'recordings'
        result = self.import_csv((folder / 'recordings.csv').read_bytes(), publication_id)
        for item in result['files']:
            incoming = self.store.root / 'incoming' / (uuid.uuid4().hex + Path(item['recording_file']).suffix)
            incoming.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copyfile(folder / safe_relative(item['recording_file']), incoming)
                self.retain(result['id'], item['recording_file'], incoming)
            finally:
                incoming.unlink(missing_ok=True)
        return self.store.import_status(result['id'])

    def detail(self, recording_id, bundle_id=None):
        recording = self.store.recording(recording_id)
        selected = bundle_id or recording['bundle_id']
        bundle = self.store.bundle(selected) if selected else None
        if bundle and bundle['recording_id'] != recording_id:
            raise ValueError('This evidence bundle belongs to another recording.')
        current = self.core.status().get('publication')
        return {'recording': recording, 'bundle_id': selected,
                'is_current': bool(current and current['id'] == recording['publication_id'] and selected == recording['bundle_id']),
                'measurement': self.store.artifact(bundle['measurement_id']) if bundle else None,
                'transcript': self.store.artifact(bundle['transcript_id']) if bundle else None,
                'jobs': self.store.recording_jobs(recording_id), 'reviews': self.store.reviews(recording_id)}

    def save_review(self, data):
        with self.core._lock:
            current = self.core.status().get('publication')
            return self.store.save_review(current_publication_id=(current or {}).get('id'), **data)

    def select(self, publication_id):
        if not self.store.ready_for_sample(publication_id):
            return
        policy = self.store.policy()
        rows = self.store.measured_recordings(publication_id)
        epoch = fingerprint({'rows': [r['id'] for r in rows], 'policy': policy})
        if self.selection_epochs.get(publication_id) == epoch:
            return
        groups = {}
        for row in rows:
            dates = sorted({d for link in row['links'] for d in link['business_dates']}) or ['unknown']
            date = dates[0]
            measurement = self.store.artifact(row['measurement_id'])
            longest = measurement['conversation']['totals']['longest_quiet_seconds']
            quiet_candidate = policy['quiet_candidate_seconds'] is not None and longest >= policy['quiet_candidate_seconds']
            if row['candidate'] or quiet_candidate:
                reason = 'audio_quiet_candidate' if quiet_candidate else 'spreadsheet_review_candidate'
                self.store.mark_selected(row['id'], reason, policy, date)
                self.enqueue(row['id'], 'transcribe', {'language': policy['asr_language']})
            else:
                groups.setdefault(date, []).append(row)
        for date, group in groups.items():
            ranked = sorted(group, key=lambda r: fingerprint({'seed': policy['sample_seed'], 'date': date, 'id': r['id']}))
            for row in ranked[:policy['random_sample_size']]:
                self.store.mark_selected(row['id'], 'random_quality_sample', policy, date)
                self.enqueue(row['id'], 'transcribe', {'language': policy['asr_language']})
        self.selection_epochs[publication_id] = epoch

    def run(self):
        counter = 0
        while not self.stop_event.wait(.25):
            ready = self.readiness()
            if not ready['ready']:
                continue
            job = self.store.claim(self.owner, ready['model_ready'], prefer_asr=counter % 10 == 9)
            if not job:
                continue
            counter += 1
            try:
                process, events = self.worker()
                path = (self.store.root / safe_relative(job['original'])).resolve()
                if not path.is_relative_to(self.store.root / 'originals'):
                    raise ValueError('Invalid retained source location.')
                process.stdin.write(json.dumps({'job_id': job['id'], 'operation': job['operation'], 'path': str(path), 'options': job['options']}) + '\n')
                process.stdin.flush()
                deadline = time.monotonic() + 7200
                while True:
                    if self.stop_event.is_set() or self.store.job(job['id'])['cancel_requested']:
                        self.kill_worker()
                        self.store.fail(job['id'], self.owner, 'Interrupted; will resume after restart.', interrupted=self.stop_event.is_set())
                        break
                    if time.monotonic() > deadline:
                        raise TimeoutError('Audio stage exceeded two hours; retry after checking the recording.')
                    try:
                        event = events.get(timeout=.25)
                    except queue.Empty:
                        continue
                    if event.get('job_id') not in {None, job['id']}:
                        continue
                    if event['type'] == 'progress':
                        self.store.progress(job['id'], self.owner, event['message'], event['progress'])
                    elif event['type'] == 'result':
                        self.store.complete(job['id'], self.owner, event['result'])
                        with self.store.connect() as db:
                            pubs = [r[0] for r in db.execute('SELECT DISTINCT r.publication_id FROM recordings r JOIN recording_jobs j ON r.id=j.recording_id WHERE j.job_id=?', (job['id'],))]
                        if job['operation'] == 'measure':
                            for pub in pubs:
                                self.select(pub)
                        self.worker_error = None
                        break
                    else:
                        raise RuntimeError(event.get('message', 'Audio worker failed.'))
            except Exception as exc:
                self.worker_error = str(exc)
                self.kill_worker()
                self.store.fail(job['id'], self.owner, str(exc))

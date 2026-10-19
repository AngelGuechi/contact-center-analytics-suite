import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import json
import socket
import threading
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import uvicorn
from avoidance.webapp import PROJECT, create_app


class Response:
    def __init__(self, response):
        with response:
            self.status_code = response.status
            self.content = response.read()
        self.text = self.content.decode('utf-8', errors='replace')
    def json(self):
        return json.loads(self.content)


class TestClient:
    def __init__(self, app):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        self.base = f'http://127.0.0.1:{port}'
        self.server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='critical'))
    def __enter__(self):
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        for _ in range(50):
            try:
                self.get('/api/health')
                return self
            except OSError:
                time.sleep(.05)
        raise RuntimeError('Test server failed to start')
    def __exit__(self, *args):
        self.server.should_exit = True
        self.thread.join(5)
    def get(self, path, headers=None):
        return self.request(path, 'GET', None, headers or {})
    def post(self, path, files=None, data=None, json=None, headers=None):
        headers = dict(headers or {})
        if files:
            boundary = 'local-audio-test-boundary'
            parts = []
            for key, value in (data or {}).items():
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
            for key, (filename, content) in files.items():
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode() + content + b'\r\n')
            parts.append(f'--{boundary}--\r\n'.encode())
            payload = b''.join(parts)
            headers['Content-Type'] = 'multipart/form-data; boundary=' + boundary
        else:
            payload = __import__('json').dumps(json or {}).encode()
            headers['Content-Type'] = 'application/json'
        return self.request(path, 'POST', payload, headers)
    def request(self, path, method, payload, headers):
        request = Request(self.base + path, data=payload, headers=headers, method=method)
        try:
            response = urlopen(request, timeout=10)
        except HTTPError as exc:
            response = exc
        return Response(response)


class AudioAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.temp.name), seed_demo=False)
        self.app.state.store.import_folder(PROJECT / 'data')
        self.start = patch('avoidance.audio_service.AudioService.start')
        self.start.start()
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.headers = {'X-Call-Review': '1'}

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.start.stop()
        self.temp.cleanup()

    def test_fixture_import_idempotency_and_media_range(self):
        first = self.client.post('/api/audio/fixtures', headers=self.headers)
        self.assertEqual(first.status_code, 200, first.text)
        second = self.client.post('/api/audio/fixtures', headers=self.headers)
        self.assertEqual(first.json()['id'], second.json()['id'])
        self.assertEqual(self.client.get('/api/audio/recordings').json()['total'], 10)
        identifier = first.json()['files'][0]['recording_id']
        media = self.client.get(f'/api/audio/recordings/{identifier}/media', headers={'Range': 'bytes=0-99'})
        self.assertEqual(media.status_code, 206)
        self.assertEqual(len(media.content), 100)
        self.assertEqual(media.content[:4], b'RIFF')
        publication = first.json()['publication_id']
        links = self.client.get(f'/api/audio/links?publication_id={publication}&transaction_ids=70003501,999').json()
        self.assertTrue(links['70003501'])
        self.assertEqual(links['999'], [])

    def test_mutation_header_required(self):
        self.assertEqual(self.client.post('/api/audio/fixtures').status_code, 403)

    def test_invalid_upload_preserves_original_and_report(self):
        publication = self.app.state.store.status()['publication']['id']
        csv = b'recording_file,call_id,call_id_type,recording_scope\na.wav,70003501,transaction,transaction_leg\n'
        batch = self.client.post('/api/audio/imports', files={'csv': ('recordings.csv', csv)}, headers=self.headers).json()
        result = self.client.post(f"/api/audio/imports/{batch['id']}/files", files={'file': ('a.wav', b'not audio')}, data={'recording_file': 'a.wav'}, headers=self.headers)
        self.assertEqual(result.status_code, 400)
        self.assertEqual(self.app.state.store.status()['publication']['id'], publication)
        self.assertEqual(self.client.get('/api/audio/recordings').json()['total'], 0)
        finished = self.client.post(f"/api/audio/imports/{batch['id']}/finish", headers=self.headers).json()
        self.assertEqual(finished['files'][0]['state'], 'skipped')
        self.assertEqual(finished['pending'], 0)
        self.assertTrue(self.app.state.audio.store.ready_for_sample(publication))

    def test_bad_ranges_and_language_rejected(self):
        for invalid in ('0', '21', '1.5'):
            self.assertEqual(self.client.get(f'/api/audio/recordings/unknown/preview?k={invalid}').status_code, 422)
        self.assertEqual(self.client.get('/api/audio/recordings/unknown/preview?start=0&end=31').status_code, 400)
        self.assertEqual(self.client.post('/api/audio/recordings/unknown/transcribe', json={'language': 'fr'}, headers=self.headers).status_code, 400)

    def test_audio_folder_without_separate_csv(self):
        publication = self.app.state.store.status()['publication']['id']
        response = self.client.post('/api/audio/imports/folder', json={'publication_id': publication,
            'paths': ['2026/10/06/70003501.wav', '2026/10/06/unknown.mp3']}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        batch = response.json()
        self.assertEqual(len(batch['files']), 2)
        self.assertEqual(len(batch['issues']), 1)
        entry = self.app.state.audio.store.import_entry(batch['id'], '2026/10/06/70003501.wav')['entry']
        self.assertEqual(entry['links'][0]['transaction_ids'], ['70003501'])
        self.assertEqual(entry['options']['channel_layout'], 'unknown')
        repeated = self.client.post('/api/audio/imports/folder', json={'publication_id': publication,
            'paths': ['2026/10/06/unknown.mp3', '2026/10/06/70003501.wav']}, headers=self.headers)
        self.assertEqual(repeated.json()['id'], batch['id'])


if __name__ == '__main__':
    unittest.main()

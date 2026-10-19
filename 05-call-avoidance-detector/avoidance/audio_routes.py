"""Local recording import and review endpoints."""
import math
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .recordings import MAX_CSV_BYTES, MAX_FILE_BYTES, folder_csv
from .store import safe_relative


class AudioReview(BaseModel):
    recording_id: str = Field(max_length=128)
    bundle_id: str = Field(max_length=128)
    publication_id: str = Field(max_length=128)
    state: str = Field(max_length=64)
    reviewer: str = Field(min_length=1, max_length=120)
    note: str = Field(min_length=1, max_length=4000)


def audio_router(service):
    router = APIRouter(prefix='/api/audio')

    def call(function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except KeyError as exc:
            raise HTTPException(404, str(exc.args[0])) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get('/status')
    def status():
        return service.status()

    @router.get('/policy')
    def policy():
        return service.store.policy()

    @router.post('/policy')
    def policy_save(data: dict):
        result = call(service.store.set_policy, data)
        service.selection_epochs.clear()
        with service.store.connect() as db:
            pubs = [row[0] for row in db.execute('SELECT DISTINCT publication_id FROM recordings')]
        for pub in pubs:
            service.select(pub)
        return result

    @router.post('/imports')
    async def import_csv(csv: UploadFile = File(...), publication_id: str | None = Form(None)):
        content = await csv.read(MAX_CSV_BYTES + 1)
        await csv.close()
        return call(service.import_csv, content, publication_id)

    @router.post('/imports/folder')
    def import_folder(data: dict):
        content = call(folder_csv, data.get('paths'))
        return call(service.import_csv, content, data.get('publication_id'))

    @router.get('/imports/{identifier}')
    def imported(identifier: str):
        return call(service.store.import_status, identifier)

    @router.post('/imports/{identifier}/finish')
    def finish_import(identifier: str):
        result = call(service.store.finish_import, identifier)
        service.select(result['publication_id'])
        return result

    @router.post('/imports/{identifier}/files')
    async def upload(identifier: str, file: UploadFile = File(...), recording_file: str = Form(...)):
        name = call(safe_relative, recording_file).as_posix()
        call(service.store.import_entry, identifier, name)
        incoming = service.store.root / 'incoming' / (uuid.uuid4().hex + Path(name).suffix.lower())
        incoming.parent.mkdir(parents=True, exist_ok=True)
        try:
            size = 0
            with incoming.open('wb') as stream:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_FILE_BYTES or shutil.disk_usage(incoming.parent).free < len(chunk) + 100 * 1024 * 1024:
                        raise HTTPException(400, 'Recording exceeds 2 GB or the disk has insufficient free space.')
                    stream.write(chunk)
            return await run_in_threadpool(call, service.retain, identifier, name, incoming)
        finally:
            incoming.unlink(missing_ok=True)
            await file.close()

    @router.post('/fixtures')
    def fixtures():
        return call(service.fixtures)

    @router.get('/recordings')
    def recordings(page: int = 1, page_size: int = 25, publication_id: str | None = None,
                   transaction_id: str | None = None, search: str = '', state: str | None = None):
        return call(service.store.list_recordings, page, page_size, publication_id, transaction_id, search, state)

    @router.get('/links')
    def links(publication_id: str, transaction_ids: str):
        identifiers = transaction_ids.split(',')
        if len(identifiers) > 100 or any(len(i) > 128 for i in identifiers):
            raise HTTPException(400, 'Request at most 100 call IDs.')
        with service.store.connect() as db:
            rows = db.execute('SELECT t.transaction_id,r.id,r.filename FROM transaction_links t JOIN recordings r ON r.id=t.recording_id WHERE t.publication_id=? AND t.transaction_id IN (' + ','.join('?' for _ in identifiers) + ') ORDER BY r.filename', [publication_id, *identifiers]).fetchall()
        result = {identifier: [] for identifier in identifiers}
        for row in rows:
            result[row['transaction_id']].append({'id': row['id'], 'filename': row['filename']})
        return result

    @router.get('/recordings/{identifier}')
    def detail(identifier: str, bundle_id: str | None = None):
        return call(service.detail, identifier, bundle_id)

    @router.get('/recordings/{identifier}/media')
    def media(identifier: str):
        path = call(service.store.original_path, identifier)
        return FileResponse(path, media_type='audio/wav' if path.suffix == '.wav' else 'audio/mpeg', content_disposition_type='inline')

    @router.post('/recordings/{identifier}/transcribe')
    def transcribe(identifier: str, data: dict):
        language = data.get('language', 'auto')
        if language not in {'auto', 'en', 'es'}:
            raise HTTPException(400, 'Choose auto, en or es.')
        return call(service.enqueue, identifier, 'transcribe', {'language': language})

    @router.get('/recordings/{identifier}/preview')
    def preview(identifier: str, start: float = 0, end: float = 30, channel: int = 0, k: int = Query(default=5, ge=1, le=20)):
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or not 0 < end - start <= 30 or channel not in {0, 1}:
            raise HTTPException(400, 'Choose a valid channel and a window of up to 30 seconds.')
        return call(service.enqueue, identifier, 'preview', {'preview_start': start, 'preview_end': end, 'preview_channel': channel, 'preview_k': k})

    @router.get('/jobs/{identifier}')
    def job(identifier: str):
        result = call(service.store.job, identifier)
        if result['state'] == 'completed':
            result['result'] = call(service.store.artifact, result['result_id'])
        return result

    @router.post('/jobs/{identifier}/{action}')
    def job_action(identifier: str, action: str):
        if action not in {'cancel', 'retry'}:
            raise HTTPException(400, 'Choose cancel or retry.')
        return call(getattr(service.store, action), identifier)

    @router.post('/reviews')
    def review(data: AudioReview):
        return call(service.save_review, data.model_dump())

    return router

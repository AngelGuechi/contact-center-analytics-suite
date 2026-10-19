"""Local FastAPI host for the prebuilt React application."""
from __future__ import annotations

import json
import os
import shutil
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .fixtures import generate_demo
from .store import LocalStore, safe_relative
from .audio_service import AudioService
from .audio_routes import audio_router

PROJECT = Path(__file__).resolve().parents[1]
PRODUCT = "call-avoidance-review"


def data_directory() -> Path:
    value = Path(os.environ.get("CA_DATA_DIR", str(PROJECT / "runtime" / "data"))).expanduser()
    return (PROJECT / value).resolve() if not value.is_absolute() else value.resolve()


class ReviewInput(BaseModel):
    evidence_id: str = Field(min_length=1, max_length=128)
    state: str = Field(max_length=64)
    reviewer: str = Field(min_length=1, max_length=120)
    note: str = Field(min_length=1, max_length=4000)
    publication_id: str | None = Field(default=None, min_length=1, max_length=128)


def create_app(root: Path | None = None, *, seed_demo: bool = True, instance_id: str | None = None) -> FastAPI:
    store = LocalStore(root or data_directory())
    audio = AudioService(store, PROJECT)
    instance_id = instance_id or uuid.uuid4().hex

    def background(function, *args, **kwargs):
        def worker():
            try:
                store.run_job(function, *args, **kwargs)
            except Exception:
                pass  # The persisted attempt and visible status carry the error.
        threading.Thread(target=worker, name="call-review-import", daemon=True).start()

    def import_demo():
        demo = store.root / "demo-input"
        if not (demo / "manifest.json").exists():
            generate_demo(demo)
        return store.import_folder(demo)

    @asynccontextmanager
    async def lifespan(app):
        audio.start()
        if seed_demo and not store.status()["has_report"]:
            store.begin_job("Preparing the synthetic 15-day demonstration")
            background(import_demo)
        try:
            yield
        finally:
            audio.close()

    app = FastAPI(title="Call review desk", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.store = store
    app.state.audio = audio
    app.include_router(audio_router(audio))

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        host = request.headers.get("host", "").split(":")[0].lower()
        if host not in {"127.0.0.1", "localhost", "testserver", "[", "::1"}:
            return JSONResponse({"detail": "Use this application's local browser address."}, status_code=403)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc != request.headers.get("host"):
                return JSONResponse({"detail": "This change must come from the local app."}, status_code=403)
            if request.headers.get("x-call-review") != "1":
                return JSONResponse({"detail": "Open the local app to make changes."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "no-cache"
        return response

    @app.get("/api/health")
    def health():
        return {"product": PRODUCT, "instance_id": instance_id, "data_directory": str(store.root),
                "project_directory": str(PROJECT),
                "ready": (PROJECT / "frontend" / "dist" / "index.html").exists(), **store.status()}

    @app.get("/api/status")
    def status():
        return store.status()

    @app.get("/api/report")
    def report():
        try:
            return store.report()
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/evidence/{evidence_id}")
    def evidence(evidence_id: str, page: int = 1, page_size: int = 100, scope: str = "current",
                 publication_id: str | None = None, signals_only: bool = False):
        if page < 1 or not 1 <= page_size <= 100:
            raise HTTPException(status_code=400, detail="Use a positive page and at most 100 rows.")
        try:
            return store.evidence(evidence_id, page, page_size, scope, publication_id, signals_only)
        except (ValueError, KeyError) as exc:
            detail = str(exc.args[0]) if exc.args else str(exc)
            return JSONResponse({"detail": detail, "code": "evidence_unavailable", "reload_report": True}, status_code=404)

    @app.post("/api/reviews")
    def review(data: ReviewInput):
        try:
            return store.save_review(data.evidence_id, data.state, data.reviewer, data.note, data.publication_id)
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/settings")
    def settings(data: dict):
        try:
            store.begin_job("Updating rules from cached validated data")
            result = store.run_job(store.update_settings, data)
            return result
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/demo")
    def demo():
        try:
            store.begin_job("Loading the synthetic demonstration")
            background(import_demo)
            return {"message": "Demonstration loading; reviews and original files are preserved."}
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/import")
    async def import_files(files: list[UploadFile] = File(...), paths: str = Form("[]")):
        try:
            names = json.loads(paths)
            if not isinstance(names, list) or any(not isinstance(name, str) for name in names) or (names and len(names) != len(files)):
                raise ValueError("File paths do not match the selected files.")
            if len(files) > 1000:
                raise ValueError("Import at most 1,000 files at a time.")
            batch = store.root / "uploads" / uuid.uuid4().hex
            batch.mkdir(parents=True)
            seen = set()
            total = 0
            for index, upload in enumerate(files):
                relative = safe_relative(names[index] if names else upload.filename or "")
                if relative.as_posix().lower() in seen:
                    raise ValueError("Two selected files have the same relative path.")
                seen.add(relative.as_posix().lower())
                if relative.suffix.lower() != ".xlsx" and relative.name not in {"manifest.json", "incidents.json"}:
                    continue  # Folder selection may include the answer key or other harmless files.
                destination = batch / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                file_size = 0
                with destination.open("wb") as output:
                    while chunk := await upload.read(1024 * 1024):
                        file_size += len(chunk)
                        total += len(chunk)
                        if file_size > 50 * 1024 * 1024 or total > 500 * 1024 * 1024:
                            raise ValueError("This local import supports 50 MB per file and 500 MB per batch.")
                        output.write(chunk)
                await upload.close()
            if not any(batch.rglob("*.xlsx")):
                raise ValueError("Select a folder containing Excel exports and its manifest.json.")
            store.begin_job("Validating uploaded workbooks; the previous report remains available")
            background(store.import_folder, batch)
            return {"message": "Import queued", "files": len(seen)}
        except (ValueError, TypeError) as exc:
            if "batch" in locals() and batch.exists():
                shutil.rmtree(batch)
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/replay/{step}")
    def replay(step: int):
        if step not in {1, 2, 3, 4}:
            raise HTTPException(status_code=400, detail="Choose replay stage 1, 2, 3 or 4.")
        try:
            store.begin_job(f"Preparing synthetic replay stage {step}")
            def import_stage():
                from .replay import replay_folder
                return store.import_folder(replay_folder(store.root, step))
            background(import_stage)
            return {"message": f"Synthetic replay stage {step} queued; active rules apply."}
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    frontend = PROJECT / "frontend" / "dist"
    if frontend.exists():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="interface")
    return app

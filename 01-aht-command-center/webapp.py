"""Local V3 browser application. Bind to localhost only until access control exists."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from azure_ai import AIUnavailable, generate
from core import AHTStore, ImportProblem, MAX_UPLOAD_BYTES


ROOT = Path(__file__).resolve().parent
store = AHTStore()
app = FastAPI(title="AHT Command Center V3", docs_url=None, redoc_url=None)
app.mount("/assets", StaticFiles(directory=ROOT / "web"), name="assets")


@app.get("/")
def home():
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "published_version": store.status()["published_version"]}


@app.get("/api/status")
def status():
    return store.status()


@app.get("/api/dashboard")
def dashboard(report_date: str | None = None, supervisor: str | None = None,
              agent: str | None = None, queue: str | None = None, rank_period: str = "today"):
    try:
        return store.dashboard(report_date, supervisor, agent, queue, rank_period)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/recommendations")
def recommendations(report_date: str | None = None, supervisor: str | None = None,
                    rank_period: str = "today"):
    try:
        return store.recommendations(report_date, supervisor, rank_period)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/runs")
def runs():
    return {"runs": store.recent_runs()}


@app.post("/api/upload")
async def upload(file: UploadFile = File(...), start: str | None = Form(None),
                 end: str | None = Form(None), revision: int | None = Form(None)):
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()
    try:
        return store.import_bytes(content, file.filename or "download.xlsx", start, end, revision)
    except ImportProblem as exc:
        raise HTTPException(400, str(exc)) from exc


class Review(BaseModel):
    state: str
    note: str = ""


@app.post("/api/recommendations/{evidence_id}/review")
def review(evidence_id: str, body: Review):
    try:
        return store.review_recommendation(evidence_id, body.state, body.note)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class AIRequest(BaseModel):
    report_date: str
    period: str = "today"


@app.post("/api/ai/{evidence_id}")
def ai(evidence_id: str, body: AIRequest):
    try:
        candidates = store.recommendations(body.report_date, rank_period=body.period)["recommendations"]
        evidence = next((row for row in candidates if row["evidence_id"] == evidence_id), None)
        if evidence is None:
            raise HTTPException(404, "Evidence is not in the current published report")
        return generate(store, evidence)
    except (AIUnavailable, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc

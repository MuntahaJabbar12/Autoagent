"""AutoAgent web server: the API and the web page."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import ideas, llm, pipeline, script, voice
from .config import ROOT, settings
from .jobs import JobManager, LimitError, RateLimiter

STATIC = ROOT / "static"

app = FastAPI(title="AutoAgent", docs_url=None, redoc_url=None)
manager: JobManager | None = None
idea_limiter = RateLimiter(30)


def jobs() -> JobManager:
    global manager
    if manager is None:
        manager = JobManager()
    return manager


def client_id(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "anon")


class IdeasIn(BaseModel):
    topic: str = Field(min_length=2, max_length=80)

    @field_validator("topic")
    @classmethod
    def strip(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 2:
            raise ValueError("Type a topic of at least 2 characters.")
        return v


class VideoIn(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    length: str = "short"
    tone: str = "curious"
    voice: str = "andrew"
    format: str = "landscape"

    @field_validator("title")
    @classmethod
    def clean(cls, v: str) -> str:
        return " ".join(v.split())

    @field_validator("length")
    @classmethod
    def v_len(cls, v: str) -> str:
        return v if v in script.LENGTHS else "short"

    @field_validator("tone")
    @classmethod
    def v_tone(cls, v: str) -> str:
        return v if v in script.TONES else "curious"

    @field_validator("voice")
    @classmethod
    def v_voice(cls, v: str) -> str:
        return v if v in voice.VOICES else "andrew"

    @field_validator("format")
    @classmethod
    def v_format(cls, v: str) -> str:
        return v if v in ("landscape", "shorts") else "landscape"


@app.get("/api/status")
def status() -> dict:
    missing = settings.missing()
    return {
        "ready": not missing,
        "missing": missing,
        "youtube_trends": bool(settings.youtube_api_key),
        "voices": [{"id": k, "label": v["label"]} for k, v in voice.VOICES.items()],
        "tones": list(script.TONES),
        "per_hour": settings.max_videos_per_hour,
    }


@app.post("/api/ideas")
def get_ideas(body: IdeasIn, request: Request) -> dict:
    if settings.missing():
        raise HTTPException(503, "This app isn't set up yet: " + ", ".join(settings.missing()) + " missing.")
    try:
        idea_limiter.check(client_id(request))
        return ideas.ideas_for(body.topic)
    except LimitError as exc:
        raise HTTPException(429, str(exc)) from exc
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/videos", status_code=202)
def make_video(body: VideoIn, request: Request) -> dict:
    if settings.missing():
        raise HTTPException(503, "This app isn't set up yet: " + ", ".join(settings.missing()) + " missing.")
    try:
        job = jobs().submit(pipeline.Options(**body.model_dump()), client_id(request))
    except LimitError as exc:
        raise HTTPException(429, str(exc)) from exc
    return job.public(jobs().position(job))


@app.get("/api/videos/{job_id}")
def video_status(job_id: str) -> dict:
    job = jobs().get(job_id)
    if not job:
        raise HTTPException(404, "This video has expired or doesn't exist.")
    return job.public(jobs().position(job))


@app.get("/files/{job_id}/{name}")
def files(job_id: str, name: str, download: int = 0) -> FileResponse:
    job = jobs().get(job_id)
    if not job or job.status != "done" or not job.result:
        raise HTTPException(404, "File not found.")
    if name not in (job.result["video"], job.result["thumbnail"], job.result["metadata"]):
        raise HTTPException(404, "File not found.")
    path: Path = jobs().path(job_id) / name
    if not path.is_file():
        raise HTTPException(404, "This video has expired.")
    return FileResponse(path, filename=name if download else None)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")

"""In-memory job queue: limits per visitor, a small worker pool, and automatic cleanup."""
from __future__ import annotations

import queue
import shutil
import threading
import time
import traceback
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path

from . import pipeline
from .config import settings


class LimitError(RuntimeError):
    pass


@dataclass
class Job:
    id: str
    options: pipeline.Options
    status: str = "queued"          # queued | running | done | failed
    stage: str = "queued"
    progress: float = 0.0
    message: str = "Waiting for a free editor"
    result: dict | None = None
    error: str | None = None
    created: float = field(default_factory=time.time)
    finished: float | None = None

    def public(self, position: int | None = None) -> dict:
        return {"id": self.id, "status": self.status, "stage": self.stage,
                "progress": round(self.progress, 3), "message": self.message,
                "result": self.result, "error": self.error, "queue_position": position}


class RateLimiter:
    def __init__(self, per_hour: int):
        self.per_hour = per_hour
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def check(self, key: str, now: float | None = None) -> None:
        now = now or time.time()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > 3600:
                q.popleft()
            if len(q) >= self.per_hour:
                wait = int((3600 - (now - q[0])) / 60) + 1
                raise LimitError(f"You've made {self.per_hour} videos this hour. "
                                 f"You can make another in about {wait} minutes.")
            q.append(now)


class JobManager:
    def __init__(self, runner=pipeline.run, out_dir: Path | None = None, workers: int | None = None):
        self.runner = runner
        self.out_dir = out_dir or settings.output_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, Job] = {}
        self.q: queue.Queue[str] = queue.Queue()
        self.order: list[str] = []
        self.lock = threading.Lock()
        self.limiter = RateLimiter(settings.max_videos_per_hour)
        for _ in range(workers or settings.workers):
            threading.Thread(target=self._work, daemon=True).start()
        threading.Thread(target=self._sweep, daemon=True).start()

    # public -----------------------------------------------------------------
    def submit(self, opts: pipeline.Options, client: str) -> Job:
        with self.lock:
            waiting = sum(1 for j in self.jobs.values() if j.status in ("queued", "running"))
        if waiting >= settings.max_queue:
            raise LimitError("Lots of people are making videos right now. Try again in a few minutes.")
        self.limiter.check(client)
        job = Job(id=uuid.uuid4().hex[:12], options=opts)
        with self.lock:
            self.jobs[job.id] = job
            self.order.append(job.id)
        self.q.put(job.id)
        return job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def position(self, job: Job) -> int | None:
        if job.status != "queued":
            return None
        with self.lock:
            ahead = [j for j in self.order if self.jobs.get(j) and self.jobs[j].status in ("queued", "running")]
        return ahead.index(job.id) if job.id in ahead else None

    def path(self, job_id: str) -> Path:
        return self.out_dir / job_id

    # internals --------------------------------------------------------------
    def _work(self) -> None:
        while True:
            job_id = self.q.get()
            job = self.jobs.get(job_id)
            if not job:
                continue
            job.status, job.message = "running", "Starting"

            def progress(stage: str, pct: float, msg: str, job=job) -> None:
                job.stage, job.progress, job.message = stage, max(job.progress, pct), msg

            try:
                job.result = self.runner(job.options, self.path(job.id), progress)
                job.status, job.stage, job.progress, job.message = "done", "done", 1.0, "Your video is ready"
            except Exception as exc:  # report a readable reason, keep the server alive
                traceback.print_exc()
                job.status, job.error = "failed", str(exc) or exc.__class__.__name__
                job.message = "Something went wrong"
                shutil.rmtree(self.path(job.id), ignore_errors=True)
            finally:
                job.finished = time.time()

    def sweep_once(self, now: float | None = None) -> int:
        now = now or time.time()
        removed = 0
        for job_id, job in list(self.jobs.items()):
            if job.finished and now - job.finished > settings.keep_minutes * 60:
                shutil.rmtree(self.path(job_id), ignore_errors=True)
                with self.lock:
                    self.jobs.pop(job_id, None)
                    if job_id in self.order:
                        self.order.remove(job_id)
                removed += 1
        return removed

    def _sweep(self) -> None:
        while True:
            time.sleep(300)
            self.sweep_once()

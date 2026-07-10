import asyncio
import queue
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from schemas import MusicRequest
import services.pipeline as pipeline_svc
from services.pipeline import GenerationCancelled

MAX_FINISHED_JOBS = 20
TERMINAL_STATUSES = {"done", "error", "cancelled"}


@dataclass
class Job:
    id: str
    request: MusicRequest
    status: str = "queued"  # queued / loading / running / done / error / cancelled
    progress: Tuple[int, int] = (0, 0)
    result: Optional[dict] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    listeners: List["asyncio.Queue[dict]"] = field(default_factory=list)


class JobManager:
    """キュー登録・単一ワーカーによる直列実行・SSE配信を担う。"""

    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._pending: List[str] = []  # queued/running のジョブID（キュー順）
        self._queue: "queue.Queue[Optional[str]]" = queue.Queue()
        self._registry_lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._worker: Optional[threading.Thread] = None

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._worker = threading.Thread(target=self._run_worker, daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._queue.put(None)

    # ── 登録・参照 ──────────────────────────────────────────────

    def submit(self, request: MusicRequest) -> Tuple[str, int]:
        job = Job(id=uuid.uuid4().hex[:8], request=request)
        with self._registry_lock:
            self._jobs[job.id] = job
            self._pending.append(job.id)
            position = self._pending.index(job.id)
        self._queue.put(job.id)
        return job.id, position

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def snapshot(self, job_id: str) -> Optional[dict]:
        job = self._jobs.get(job_id)
        return self._event_for(job) if job else None

    def cancel(self, job_id: str) -> Optional[dict]:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        if job.status == "queued":
            self._set_status(job, "cancelled")
        elif job.status in ("loading", "running"):
            job.cancel_event.set()
        return {"status": job.status}

    # ── SSE 購読 ────────────────────────────────────────────────

    def subscribe(self, job_id: str) -> Optional["asyncio.Queue[dict]"]:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        listener: "asyncio.Queue[dict]" = asyncio.Queue()
        with self._registry_lock:
            listener.put_nowait(self._event_for(job))
            job.listeners.append(listener)
        return listener

    def unsubscribe(self, job_id: str, listener: "asyncio.Queue[dict]") -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        with self._registry_lock:
            if listener in job.listeners:
                job.listeners.remove(listener)

    # ── 内部実装 ────────────────────────────────────────────────

    def _position(self, job_id: str) -> int:
        try:
            return self._pending.index(job_id)
        except ValueError:
            return 0

    def _event_for(self, job: Job) -> dict:
        if job.status == "queued":
            return {"type": "queued", "position": self._position(job.id)}
        if job.status == "loading":
            return {"type": "loading"}
        if job.status == "running":
            current, total = job.progress
            return {"type": "progress", "current": current, "total": total}
        if job.status == "done":
            return {"type": "done", **(job.result or {})}
        if job.status == "error":
            return {"type": "error", "message": job.error or ""}
        return {"type": "cancelled"}

    def _broadcast(self, job: Job) -> None:
        event = self._event_for(job)
        loop = self._loop
        if loop is None:
            return
        for listener in list(job.listeners):
            loop.call_soon_threadsafe(listener.put_nowait, event)

    def _broadcast_queue_positions(self) -> None:
        for job_id in self._pending:
            job = self._jobs.get(job_id)
            if job is not None and job.status == "queued":
                self._broadcast(job)

    def _set_status(self, job: Job, status: str, **fields) -> None:
        with self._registry_lock:
            job.status = status
            for k, v in fields.items():
                setattr(job, k, v)
        self._broadcast(job)
        if status in TERMINAL_STATUSES:
            self._finish(job)

    def _finish(self, job: Job) -> None:
        with self._registry_lock:
            if job.id in self._pending:
                self._pending.remove(job.id)
            finished = sorted(
                (j for j in self._jobs.values() if j.status in TERMINAL_STATUSES),
                key=lambda j: j.created_at,
            )
            for stale in finished[:-MAX_FINISHED_JOBS] if len(finished) > MAX_FINISHED_JOBS else []:
                self._jobs.pop(stale.id, None)
        self._broadcast_queue_positions()

    def _run_worker(self) -> None:
        while True:
            job_id = self._queue.get()
            if job_id is None:
                break
            job = self._jobs.get(job_id)
            if job is None or job.status == "cancelled":
                continue
            self._run_job(job)

    def _run_job(self, job: Job) -> None:
        self._set_status(job, "loading")

        if job.cancel_event.is_set():
            self._set_status(job, "cancelled")
            return

        def progress_callback(current: int, total: int) -> None:
            if job.cancel_event.is_set():
                raise GenerationCancelled()
            job.status = "running"
            job.progress = (current, total)
            self._broadcast(job)

        try:
            result = pipeline_svc.generate(job.request, progress_callback, job.cancel_event)
            self._set_status(job, "done", result=result)
        except GenerationCancelled:
            self._set_status(job, "cancelled")
        except Exception as e:
            traceback.print_exc()
            self._set_status(job, "error", error=str(e))


job_manager = JobManager()

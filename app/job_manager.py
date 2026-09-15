"""
app/job_manager.py
Sequential queue manager for background packaging jobs with real-time SSE telemetry.
"""

import os
import time
import uuid
import json
import asyncio
from pathlib import Path
from typing import Dict, List, Any, Optional, Set
from pydantic import BaseModel, Field

from app.config import DATA_DIR, INPUT_DIR
from app.builder import run_packaging_pipeline

JOBS_FILE = DATA_DIR / "jobs_history.json"


class JobCreateRequest(BaseModel):
    folder_name: str
    game_title: Optional[str] = None
    app_id: Optional[str] = None
    main_exe: Optional[str] = None
    disc_type: Optional[str] = "single"
    disc_size_mb: Optional[int] = 0
    limit_ram: Optional[bool] = True
    player_name: Optional[str] = "VaporPlayer"
    language: Optional[str] = "english"
    steam_id: Optional[str] = "76561197960287930"
    firewall_rule: Optional[bool] = True


class Job:
    def __init__(self, job_id: str, request: JobCreateRequest, game_path: Path):
        self.id = job_id
        self.folder_name = request.folder_name
        self.game_title = request.game_title or request.folder_name
        self.app_id = request.app_id or "480"
        self.game_path = game_path
        self.params = request.model_dump()
        self.status = "queued"  # queued, running, completed, failed, cancelled
        self.stage = "Queued in packaging manager"
        self.progress = 0
        self.created_at = time.time()
        self.started_at: Optional[float] = None
        self.completed_at: Optional[float] = None
        self.logs: List[str] = []
        self.output_files: List[str] = []
        self.error: Optional[str] = None
        self._subscribers: Set[asyncio.Queue] = set()
        self._cancelled = False

    def is_cancelled(self) -> bool:
        return self._cancelled

    def cancel(self):
        self._cancelled = True
        if self.status in ["queued", "running"]:
            self.status = "cancelled"
            self.stage = "Packaging cancelled by user"
            self.broadcast_sync({"type": "status", "status": self.status, "stage": self.stage})

    async def add_log(self, text: str):
        timestamp = time.strftime("%H:%M:%S")
        entry = f"[{timestamp}] {text}"
        self.logs.append(entry)
        # Keep log size reasonable in memory
        if len(self.logs) > 2000:
            self.logs.pop(0)
        await self.broadcast({"type": "log", "line": entry})

    async def update_progress(self, progress: int, stage: str):
        self.progress = progress
        self.stage = stage
        await self.broadcast({
            "type": "progress",
            "progress": self.progress,
            "stage": self.stage
        })

    async def broadcast(self, message: Dict[str, Any]):
        for q in list(self._subscribers):
            try:
                await q.put(message)
            except Exception:
                pass

    def broadcast_sync(self, message: Dict[str, Any]):
        for q in list(self._subscribers):
            try:
                q.put_nowait(message)
            except Exception:
                pass

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        self._subscribers.discard(q)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "folder_name": self.folder_name,
            "game_title": self.game_title,
            "app_id": self.app_id,
            "status": self.status,
            "stage": self.stage,
            "progress": self.progress,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "output_files": self.output_files,
            "error": self.error,
            "params": self.params,
        }


class QueueManager:
    def __init__(self):
        self.jobs: Dict[str, Job] = {}
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.active_job_id: Optional[str] = None
        self._worker_task: Optional[asyncio.Task] = None
        self._load_history()

    def _load_history(self):
        if JOBS_FILE.exists():
            try:
                with open(JOBS_FILE, "r", encoding="utf-8") as f:
                    history = json.load(f)
                    for item in history:
                        job_id = item["id"]
                        req = JobCreateRequest(**item["params"])
                        game_p = Path(item.get("params", {}).get("game_path", str(INPUT_DIR / item["folder_name"])))
                        j = Job(job_id, req, game_p)
                        j.status = item.get("status", "completed")
                        j.stage = item.get("stage", "Finished")
                        j.progress = item.get("progress", 100)
                        j.created_at = item.get("created_at", 0)
                        j.started_at = item.get("started_at")
                        j.completed_at = item.get("completed_at")
                        j.output_files = item.get("output_files", [])
                        j.error = item.get("error")
                        self.jobs[job_id] = j
            except Exception:
                pass

    def _save_history(self):
        try:
            JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
            # Save recent 50 completed/failed jobs
            serializable = [
                j.to_dict() for j in sorted(self.jobs.values(), key=lambda x: x.created_at, reverse=True)[:50]
            ]
            with open(JOBS_FILE, "w", encoding="utf-8") as f:
                json.dump(serializable, f, indent=2)
        except Exception:
            pass

    def start_worker(self):
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._process_queue())

    async def enqueue(self, request: JobCreateRequest) -> Job:
        # Determine actual game path inside INPUT_DIR
        game_path = (INPUT_DIR / request.folder_name).resolve()
        if not game_path.exists():
            # If input dir itself is the game
            if INPUT_DIR.name == request.folder_name or not (INPUT_DIR / request.folder_name).exists():
                game_path = INPUT_DIR

        job_id = str(uuid.uuid4())[:8]
        job = Job(job_id, request, game_path)
        self.jobs[job_id] = job
        await self.queue.put(job_id)
        self.start_worker()
        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        return self.jobs.get(job_id)

    def get_all_jobs(self) -> List[Dict[str, Any]]:
        return [j.to_dict() for j in sorted(self.jobs.values(), key=lambda x: x.created_at, reverse=True)]

    def cancel_job(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if not job:
            return False
        job.cancel()
        self._save_history()
        return True

    async def _process_queue(self):
        """Sequential background queue processor."""
        while True:
            job_id = await self.queue.get()
            job = self.jobs.get(job_id)

            if not job or job.is_cancelled():
                self.queue.task_done()
                continue

            self.active_job_id = job_id
            job.status = "running"
            job.started_at = time.time()
            await job.add_log(f"Job started for {job.game_title}...")
            await job.update_progress(1, "Starting packaging pipeline...")

            try:
                results = await run_packaging_pipeline(
                    job_id=job.id,
                    game_path=job.game_path,
                    params=job.params,
                    log_callback=job.add_log,
                    progress_callback=job.update_progress,
                    is_cancelled=job.is_cancelled,
                )

                job.status = "completed"
                job.stage = "Packaging finished successfully"
                job.progress = 100
                job.completed_at = time.time()
                job.output_files = results.get("output_isos", [])
                await job.add_log(f"Artifacts: {', '.join(job.output_files)}")
                await job.broadcast({"type": "complete", "job": job.to_dict()})

            except asyncio.CancelledError:
                job.status = "cancelled"
                job.stage = "Packaging cancelled"
                await job.add_log("Job was aborted by user.")
                await job.broadcast({"type": "cancelled", "job": job.to_dict()})

            except Exception as e:
                job.status = "failed"
                job.stage = f"Failed: {str(e)}"
                job.error = str(e)
                job.completed_at = time.time()
                await job.add_log(f"[ERROR] {str(e)}")
                await job.broadcast({"type": "error", "error": str(e), "job": job.to_dict()})

            finally:
                self.active_job_id = None
                self.queue.task_done()
                self._save_history()


queue_manager = QueueManager()

"""
app/main.py
FastAPI Web Server for VaporBurn — ISO Packaging Companion for VaporFetch.
"""

import os
import shutil
import asyncio
import json
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import (
    BASE_DIR,
    INPUT_DIR,
    OUTPUT_DIR,
    DATA_DIR,
    PORT,
    load_settings,
    save_settings,
)
from app.library import scan_input_library, inspect_game_folder, format_size
from app.job_manager import queue_manager, JobCreateRequest


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start background packaging worker queue on startup
    queue_manager.start_worker()
    yield


app = FastAPI(title="VaporBurn", version="1.0.0", lifespan=lifespan)

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>VaporBurn is initializing...</h1>")


# ---------------- Library Endpoints ---------------- #

@app.get("/api/library")
async def get_library():
    """Scans and lists all game backups found in /input."""
    try:
        games = scan_input_library()
        return {"games": games, "count": len(games), "input_path": str(INPUT_DIR)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed scanning library: {str(e)}")


@app.get("/api/library/{folder_name}")
async def get_game_details(folder_name: str):
    """Retrieves detailed metadata for a specific game folder."""
    target_dir = INPUT_DIR / folder_name
    if not target_dir.exists():
        if INPUT_DIR.name == folder_name:
            target_dir = INPUT_DIR
        else:
            raise HTTPException(status_code=404, detail=f"Game '{folder_name}' not found in /input")

    try:
        return inspect_game_folder(target_dir)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------- Job Queue & Packaging Endpoints ---------------- #

@app.post("/api/jobs")
async def create_job(req: JobCreateRequest):
    """Enqueues a new ISO packaging job."""
    try:
        job = await queue_manager.enqueue(req)
        return {"status": "enqueued", "job_id": job.id, "job": job.to_dict()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to enqueue job: {str(e)}")


@app.get("/api/jobs")
async def list_jobs():
    """Returns all queued, running, and finished packaging jobs."""
    return {
        "jobs": queue_manager.get_all_jobs(),
        "active_job_id": queue_manager.active_job_id,
    }


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    """Returns specific job status and metadata."""
    job = queue_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Aborts a queued or active packaging job."""
    success = queue_manager.cancel_job(job_id)
    if not success:
        raise HTTPException(status_code=404, detail="Job not found or already completed")
    return {"status": "cancelled", "job_id": job_id}


@app.get("/api/jobs/{job_id}/stream")
async def stream_job_telemetry(job_id: str):
    """Server-Sent Events (SSE) stream for live compiler logs and progress."""
    job = queue_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        # First send historical logs
        for log in job.logs:
            yield f"data: {json.dumps({'type': 'log', 'line': log})}\n\n"

        # Send initial status
        yield f"data: {json.dumps({'type': 'status', 'status': job.status, 'stage': job.stage, 'progress': job.progress})}\n\n"

        if job.status in ["completed", "failed", "cancelled"]:
            return

        q = job.subscribe()
        try:
            while True:
                data = await q.get()
                yield f"data: {json.dumps(data)}\n\n"
                if data.get("type") in ["complete", "error", "cancelled"]:
                    break
        finally:
            job.unsubscribe(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# ---------------- Output ISOs & Artifacts Endpoints ---------------- #

@app.get("/api/isos")
async def list_isos():
    """Lists all completed ISO images and checksums in /output."""
    if not OUTPUT_DIR.exists():
        return {"isos": [], "count": 0}

    isos = []
    for f in sorted(OUTPUT_DIR.glob("*.iso"), key=lambda p: p.stat().st_mtime, reverse=True):
        size_bytes = f.stat().st_size
        sha256_file = f.parent / f"{f.name}.sha256"
        sha_hash = ""
        if sha256_file.exists():
            try:
                sha_hash = sha256_file.read_text(encoding="utf-8").split()[0]
            except Exception:
                pass

        isos.append({
            "filename": f.name,
            "size_bytes": size_bytes,
            "size_formatted": format_size(size_bytes),
            "modified_time": f.stat().st_mtime,
            "sha256": sha_hash,
            "download_url": f"/api/isos/{f.name}/download",
            "checksum_url": f"/api/isos/{f.name}.sha256/download" if sha256_file.exists() else None,
        })

    return {"isos": isos, "count": len(isos), "output_path": str(OUTPUT_DIR)}


@app.get("/api/isos/{filename}/download")
async def download_iso_file(filename: str):
    """Directly streams or downloads an ISO or SHA256 file."""
    # Prevent directory traversal
    clean_name = os.path.basename(filename)
    target = OUTPUT_DIR / clean_name
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found in /output")

    media_type = "application/x-iso9660-image" if clean_name.endswith(".iso") else "text/plain"
    return FileResponse(
        path=target,
        media_type=media_type,
        filename=clean_name
    )


# ---------------- System & Storage Endpoints ---------------- #

@app.get("/api/system/storage")
async def get_storage_stats():
    """Returns disk capacity, usage, and free space for /input and /output."""
    def get_fs_stats(path: Path):
        try:
            usage = shutil.disk_usage(path)
            pct = round((usage.used / usage.total) * 100, 1) if usage.total > 0 else 0
            return {
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "percent": pct,
                "total_formatted": format_size(usage.total),
                "free_formatted": format_size(usage.free),
                "used_formatted": format_size(usage.used),
            }
        except Exception:
            return None

    return {
        "output_storage": get_fs_stats(OUTPUT_DIR),
        "input_storage": get_fs_stats(INPUT_DIR),
    }


@app.get("/api/settings")
async def get_settings():
    """Returns active settings."""
    return load_settings()


@app.post("/api/settings")
async def update_settings(new_settings: Dict[str, Any]):
    """Updates active settings."""
    saved = save_settings(new_settings)
    return {"status": "saved", "settings": saved}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=PORT, reload=False)


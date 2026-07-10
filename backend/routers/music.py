import asyncio
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

import services.pipeline as pipeline_svc
from schemas import MusicRequest, OllamaRequestBase
from services.jobs import job_manager

router = APIRouter()


@router.get("/api/versions")
async def get_versions():
    return {
        "versions": pipeline_svc.available_versions(),
        "codec_versions": pipeline_svc.CODEC_VERSIONS,
    }


@router.get("/api/config")
async def get_config():
    return {
        "versions": pipeline_svc.available_versions(),
        "codec_versions": pipeline_svc.CODEC_VERSIONS,
        "ollama_defaults": OllamaRequestBase().model_dump(),
        "music_defaults": MusicRequest(tags="", lyrics="").model_dump(exclude={"tags", "lyrics"}),
    }


@router.post("/api/music")
async def submit_music(request: MusicRequest):
    job_id, position = job_manager.submit(request)
    return {"job_id": job_id, "position": position}


@router.get("/api/music/{job_id}")
async def get_music_snapshot(job_id: str):
    event = job_manager.snapshot(job_id)
    if event is None:
        raise HTTPException(status_code=404, detail="job not found")
    return event


@router.post("/api/music/{job_id}/cancel")
async def cancel_music(job_id: str):
    result = job_manager.cancel(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="job not found")
    return result


@router.get("/api/music/{job_id}/events")
async def stream_music_events(job_id: str):
    listener = job_manager.subscribe(job_id)
    if listener is None:
        raise HTTPException(status_code=404, detail="job not found")

    async def event_stream():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(listener.get(), timeout=30.0)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    if event["type"] in ("done", "error", "cancelled"):
                        break
                except asyncio.TimeoutError:
                    # 30秒間イベントがなければハートビートを送って接続を維持
                    yield ": heartbeat\n\n"
        finally:
            job_manager.unsubscribe(job_id, listener)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

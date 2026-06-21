import asyncio
import json
import traceback

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import services.pipeline as pipeline_svc

router = APIRouter()


class MusicRequest(BaseModel):
    tags: str
    lyrics: str
    version_label: str = "3B-happy-new-year (latest)"
    codec_version: str = "oss-20260123"
    seed: int = -1
    max_seconds: int = 210
    topk: int = 50
    temperature: float = 1.0
    cfg_scale: float = 1.5
    keep_model_loaded: bool = True
    offload_mode: str = "auto"
    quantize_4bit: bool = True


@router.get("/api/versions")
async def get_versions():
    return {
        "versions": pipeline_svc.available_versions(),
        "codec_versions": pipeline_svc.CODEC_VERSIONS,
    }


@router.post("/api/music")
async def generate_music(request: MusicRequest):
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def progress_callback(current: int, total: int) -> None:
        asyncio.run_coroutine_threadsafe(
            queue.put({"type": "progress", "current": current, "total": total}),
            loop,
        )

    async def run_pipeline() -> None:
        try:
            result = await loop.run_in_executor(
                None,
                lambda: pipeline_svc.generate(request, progress_callback),
            )
            await queue.put({"type": "done", **result})
        except Exception as e:
            traceback.print_exc()
            await queue.put({"type": "error", "message": str(e)})

    async def event_stream():
        task = asyncio.create_task(run_pipeline())
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event["type"] in ("done", "error"):
                    break
            except asyncio.TimeoutError:
                # 30秒間イベントがなければハートビートを送って接続を維持
                yield ": heartbeat\n\n"
        await task

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

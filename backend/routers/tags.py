import asyncio
import time

from fastapi import APIRouter, HTTPException, Query

from schemas import TagsRequest, TagsResponse
from services.ollama import list_models, ollama_chat, parse_tags
from services.prompts import DEFAULT_TAGS_SYSTEM, DEFAULT_TAGS_USER
from utils import format_elapsed

router = APIRouter()


@router.get("/api/ollama-models")
async def get_ollama_models(url: str = Query(default="http://localhost:11434")):
    try:
        loop = asyncio.get_running_loop()
        models = await loop.run_in_executor(None, lambda: list_models(url))
        return {"models": models}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama接続エラー: {e}")


@router.post("/api/tags", response_model=TagsResponse)
async def generate_tags(request: TagsRequest) -> TagsResponse:
    try:
        loop = asyncio.get_running_loop()
        t0 = time.time()
        user_msg = DEFAULT_TAGS_USER.format(
            theme=request.theme,
            language=request.language,
            song_structure=request.song_structure,
            vocal=request.vocal,
        )
        raw = await loop.run_in_executor(
            None,
            lambda: ollama_chat(
                request.ollama_url, request.model,
                DEFAULT_TAGS_SYSTEM, user_msg, request.temperature,
            ),
        )
        return TagsResponse(tags=parse_tags(raw), elapsed=format_elapsed(time.time() - t0))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

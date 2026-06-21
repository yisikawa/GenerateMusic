import asyncio
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.ollama import ollama_chat, parse_tags
from services.prompts import DEFAULT_TAGS_SYSTEM, DEFAULT_TAGS_USER

router = APIRouter()


class TagsRequest(BaseModel):
    ollama_url: str = "http://localhost:11434"
    model: str = "qwen2.5:7b"
    language: str = "Japanese"
    song_structure: str = "Medium"
    vocal: str = "female_vocal"
    temperature: float = 1.0
    theme: str = "春の別れ、切ない恋の歌"


class TagsResponse(BaseModel):
    tags: str
    elapsed: str


def _fmt_elapsed(seconds: float) -> str:
    mins, secs = divmod(int(seconds), 60)
    return f"{mins}分{secs}秒" if mins else f"{secs}秒"


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
        return TagsResponse(tags=parse_tags(raw), elapsed=_fmt_elapsed(time.time() - t0))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

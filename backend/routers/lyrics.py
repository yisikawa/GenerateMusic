import asyncio
import time

from fastapi import APIRouter, HTTPException

from schemas import LyricsRequest, LyricsResponse
from services.ollama import ollama_chat, validate_lyrics
from services.prompts import DEFAULT_LYRICS_SYSTEM, DEFAULT_LYRICS_USER
from utils import format_elapsed

router = APIRouter()


@router.post("/api/lyrics", response_model=LyricsResponse)
async def generate_lyrics(request: LyricsRequest) -> LyricsResponse:
    try:
        loop = asyncio.get_running_loop()
        t0 = time.time()
        user_msg = DEFAULT_LYRICS_USER.format(
            theme=request.theme,
            language=request.language,
            song_structure=request.song_structure,
            vocal=request.vocal,
            tags=request.tags,
        )
        raw = await loop.run_in_executor(
            None,
            lambda: ollama_chat(
                request.ollama_url, request.model,
                DEFAULT_LYRICS_SYSTEM, user_msg, request.temperature,
            ),
        )
        return LyricsResponse(lyrics=validate_lyrics(raw), elapsed=format_elapsed(time.time() - t0))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

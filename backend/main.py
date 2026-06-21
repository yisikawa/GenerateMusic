import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).parent
_PROJECT_ROOT = _BACKEND_DIR.parent

for _p in [str(_PROJECT_ROOT), str(_BACKEND_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from routers.tags import router as tags_router
from routers.lyrics import router as lyrics_router
from routers.music import router as music_router

OUTPUT_DIR = _PROJECT_ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

app = FastAPI(title="GenerateMusic API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5170"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tags_router)
app.include_router(lyrics_router)
app.include_router(music_router)

app.mount("/audio", StaticFiles(directory=str(OUTPUT_DIR)), name="audio")

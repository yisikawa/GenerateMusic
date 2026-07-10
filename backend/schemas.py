from pydantic import BaseModel


class OllamaRequestBase(BaseModel):
    ollama_url: str = "http://localhost:11434"
    model: str = "qwen2.5:7b"
    language: str = "Japanese"
    song_structure: str = "Medium"
    vocal: str = "female_vocal"
    temperature: float = 1.0
    theme: str = "春の別れ、切ない恋の歌"


class TagsRequest(OllamaRequestBase):
    pass


class LyricsRequest(OllamaRequestBase):
    tags: str = ""


class TagsResponse(BaseModel):
    tags: str
    elapsed: str


class LyricsResponse(BaseModel):
    lyrics: str
    elapsed: str


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
    keep_model_loaded: bool = False
    offload_mode: str = "auto"
    quantize_4bit: bool = True

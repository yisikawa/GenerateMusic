import contextlib
import gc
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import torch
from transformers import BitsAndBytesConfig

_PROJECT_ROOT = Path(__file__).parent.parent.parent
MODELS_DIR = _PROJECT_ROOT / "models"
OUTPUT_DIR = _PROJECT_ROOT / "output"

MODEL_VERSIONS: Dict[str, str] = {
    "3B-happy-new-year (latest)": "HeartMuLa-oss-3B-happy-new-year",
    "RL-oss-3B-20260123":         "RL-oss-3B-20260123",
    "3B (base)":                  "3B",
}
CODEC_VERSIONS: List[str] = ["oss-20260123", "oss"]


def _resolve_model_path(v: str) -> Path:
    if v.startswith("HeartMuLa"):
        return MODELS_DIR / v
    elif "RL" in v or "2026" in v:
        return MODELS_DIR / f"HeartMuLa-{v}"
    else:
        return MODELS_DIR / f"HeartMuLa-oss-{v}"


def available_versions() -> List[str]:
    found = [k for k, v in MODEL_VERSIONS.items() if _resolve_model_path(v).exists()]
    return found if found else list(MODEL_VERSIONS.keys())


def _fmt_elapsed(seconds: float) -> str:
    mins, secs = divmod(int(seconds), 60)
    return f"{mins}分{secs}秒" if mins else f"{secs}秒"


_pipe = None
_pipe_key = None
_lock = threading.Lock()


@contextlib.contextmanager
def _patch_tqdm(callback: Optional[Callable[[int, int], None]]):
    if callback is None:
        yield
        return
    import tqdm as tqdm_module
    original = tqdm_module.tqdm

    class _PatchedTqdm(original):  # type: ignore[valid-type, misc]
        def update(self, n: int = 1) -> None:
            super().update(n)
            try:
                callback(int(self.n), int(self.total or 0))
            except Exception:
                pass

    tqdm_module.tqdm = _PatchedTqdm
    try:
        yield
    finally:
        tqdm_module.tqdm = original


def generate(request: Any, progress_callback: Optional[Callable[[int, int], None]] = None) -> Dict[str, str]:
    global _pipe, _pipe_key
    from heartlib.pipelines.music_generation import HeartMuLaGenPipeline

    with _lock:
        version = MODEL_VERSIONS.get(request.version_label, "HeartMuLa-oss-3B-happy-new-year")
        key = (version, request.codec_version, request.quantize_4bit)

        if _pipe is None or _pipe_key != key:
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32

            bnb_config = None
            if request.quantize_4bit and device.type == "cuda":
                major, _ = torch.cuda.get_device_capability()
                quant_type = "fp4" if major >= 10 else "nf4"
                bnb_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_quant_type=quant_type,
                    bnb_4bit_compute_dtype=torch.bfloat16,
                    bnb_4bit_use_double_quant=True,
                )
                print(f"[INFO] 4bit量子化有効 ({quant_type})")

            print(f"[INFO] Loading pipeline on {device} / {dtype}")
            _pipe = HeartMuLaGenPipeline.from_pretrained(
                pretrained_path=str(MODELS_DIR),
                device=device,
                torch_dtype=dtype,
                version=version,
                codec_version=request.codec_version,
                lazy_load=True,
                bnb_config=bnb_config,
            )
            _pipe_key = key
            print("[INFO] Pipeline loaded")

        seed = request.seed
        if seed == -1:
            seed = int(time.time() * 1000) % (2**31)
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed(seed)

        save_path = str(OUTPUT_DIR / f"music_{seed}.wav")
        print(f"[INFO] Generating: seed={seed}")

        is_instrumental = "instrumental" in request.tags.lower()
        lyrics = "[instrumental]" if is_instrumental else request.lyrics

        t0 = time.time()
        with torch.inference_mode(), _patch_tqdm(progress_callback):
            _pipe(
                {"lyrics": lyrics, "tags": request.tags},
                max_audio_length_ms=request.max_seconds * 1000,
                save_path=save_path,
                topk=request.topk,
                temperature=request.temperature,
                cfg_scale=request.cfg_scale,
                keep_model_loaded=request.keep_model_loaded,
                offload_mode=request.offload_mode,
            )
        elapsed_str = _fmt_elapsed(time.time() - t0)

        import soundfile as sf
        info = sf.info(save_path)
        dur_mins, dur_secs = divmod(int(info.duration), 60)
        duration_str = f"{dur_mins}分{dur_secs}秒" if dur_mins else f"{dur_secs}秒"
        print(f"[INFO] 生成完了: {save_path} ({elapsed_str}, {duration_str})")

        if not request.keep_model_loaded:
            _pipe = None
            _pipe_key = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        filename = Path(save_path).name
        return {
            "file_url": f"/audio/{filename}",
            "elapsed": elapsed_str,
            "duration": duration_str,
        }

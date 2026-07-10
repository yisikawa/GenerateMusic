import contextlib
import gc
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import torch
from transformers import BitsAndBytesConfig

from utils import format_elapsed


class GenerationCancelled(Exception):
    pass


_PROJECT_ROOT = Path(__file__).parent.parent.parent
MODELS_DIR = _PROJECT_ROOT / "models"
OUTPUT_DIR = _PROJECT_ROOT / "output"

MODEL_VERSIONS: Dict[str, str] = {
    "3B-happy-new-year (latest)": "HeartMuLa-oss-3B-happy-new-year",
    "RL-oss-3B-20260123":         "HeartMuLa-RL-oss-3B-20260123",
    "3B (base)":                  "HeartMuLa-oss-3B",
}
CODEC_VERSIONS: List[str] = ["oss-20260123", "oss"]


def _resolve_model_path(label: str) -> Path:
    return MODELS_DIR / MODEL_VERSIONS[label]


def available_versions() -> List[str]:
    found = [k for k in MODEL_VERSIONS if _resolve_model_path(k).exists()]
    return found if found else list(MODEL_VERSIONS.keys())


# モデルキャッシュ。呼び出し元は単一ワーカースレッド（services/jobs.py）である前提。
_pipe = None
_pipe_key = None


def _unload_pipe_if_needed(keep_model_loaded: bool) -> None:
    global _pipe, _pipe_key
    if keep_model_loaded:
        return
    _pipe = None
    _pipe_key = None
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


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
            except GenerationCancelled:
                raise
            except Exception:
                pass

    tqdm_module.tqdm = _PatchedTqdm
    try:
        yield
    finally:
        tqdm_module.tqdm = original


def generate(
    request: Any,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Dict[str, str]:
    global _pipe, _pipe_key
    from heartlib.pipelines.music_generation import HeartMuLaGenPipeline

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

    # モデルロード中断は困難なため、ロード完了直後・生成開始前に1回だけチェックする。
    if cancel_event is not None and cancel_event.is_set():
        _unload_pipe_if_needed(request.keep_model_loaded)
        raise GenerationCancelled()

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
    try:
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
    except Exception:
        try:
            Path(save_path).unlink(missing_ok=True)  # 書きかけのwavをベストエフォートで削除
        except OSError:
            pass
        _unload_pipe_if_needed(request.keep_model_loaded)
        raise
    elapsed_str = format_elapsed(time.time() - t0)

    import soundfile as sf
    info = sf.info(save_path)
    duration_str = format_elapsed(info.duration)
    print(f"[INFO] 生成完了: {save_path} ({elapsed_str}, {duration_str})")

    _unload_pipe_if_needed(request.keep_model_loaded)

    filename = Path(save_path).name
    return {
        "file_url": f"/audio/{filename}",
        "elapsed": elapsed_str,
        "duration": duration_str,
    }

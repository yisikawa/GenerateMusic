import traceback
from pathlib import Path
import torch
from heartlib.pipelines import HeartMuLaGenPipeline

MODELS_DIR = Path(__file__).parent / "models"

print("=== パス確認 ===")
print(f"MODELS_DIR        : {MODELS_DIR}")
print(f"HeartMuLa-oss-3B-happy-new-year : {(MODELS_DIR / 'HeartMuLa-oss-3B-happy-new-year').exists()}")
print(f"HeartCodec-oss    : {(MODELS_DIR / 'HeartCodec-oss').exists()}")
print(f"tokenizer.json    : {(MODELS_DIR / 'tokenizer.json').exists()}")
print(f"gen_config.json   : {(MODELS_DIR / 'gen_config.json').exists()}")
print(f"CUDA              : {torch.cuda.is_available()}")

print("\n=== パイプライン読み込み ===")
try:
    device = torch.device("cuda")
    dtype  = torch.float16
    pipe = HeartMuLaGenPipeline.from_pretrained(
        pretrained_path=str(MODELS_DIR),
        device={"mula": device, "codec": device},
        dtype={"mula": dtype,   "codec": dtype},
        version="3B-happy-new-year",
        lazy_load=False,
    )
    print("読み込み成功")
except Exception:
    print(traceback.format_exc())
    exit(1)

print("\n=== 生成テスト ===")
import tempfile, time
lyrics = "[Verse]\nテスト\n[Chorus]\nテスト"
tags   = "piano,sad,slow"

with (
    tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as lf,
    tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf,
):
    lf.write(lyrics); lyrics_path = lf.name
    tf.write(tags);   tags_path   = tf.name

try:
    with torch.no_grad():
        pipe(
            {"lyrics": lyrics_path, "tags": tags_path},
            max_audio_length_ms=30000,
            save_path="test_output.wav",
            topk=50,
            temperature=1.0,
            cfg_scale=1.5,
        )
    print("生成成功: test_output.wav")
except Exception:
    print(traceback.format_exc())

import gc
import re
import sys
import time
import traceback
from pathlib import Path

import requests
import torch
import gradio as gr
from transformers import BitsAndBytesConfig

# ── パス ──────────────────────────────────────────────────────────
MODELS_DIR = Path(__file__).parent / "models"
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# プロジェクト内のローカルhertlibを使用（ComfyUI版ベース）
_PROJECT_ROOT = Path(__file__).parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ── モデルバージョン定義（ComfyUI版の命名規則に合わせる）──────────
# from_pretrained内でのフォルダ解決:
#   "RL" or "2026" を含む → HeartMuLa-{version}
#   "HeartMuLa"で始まる  → {version} そのまま
#   それ以外              → HeartMuLa-oss-{version}
MODEL_VERSIONS = {
    "3B-happy-new-year (latest)": "HeartMuLa-oss-3B-happy-new-year",
    "RL-oss-3B-20260123":         "RL-oss-3B-20260123",
    "3B (base)":                  "3B",
}

CODEC_VERSIONS = ["oss-20260123", "oss"]

def _resolve_model_path(v: str) -> Path:
    if v.startswith("HeartMuLa"):
        return MODELS_DIR / v
    elif "RL" in v or "2026" in v:
        return MODELS_DIR / f"HeartMuLa-{v}"
    else:
        return MODELS_DIR / f"HeartMuLa-oss-{v}"

def _available_versions() -> list[str]:
    found = [k for k, v in MODEL_VERSIONS.items() if _resolve_model_path(v).exists()]
    return found if found else list(MODEL_VERSIONS.keys())

# ── デフォルトプロンプト ───────────────────────────────────────────
DEFAULT_TAGS_SYSTEM = """\
You are a professional music producer and tagging specialist.
Your task is to generate style tags for a music track based on the user's theme and request.

Output rules (strictly follow):
- Output ONLY a single line of comma-separated tags
- No spaces after commas
- No explanation, no numbering, no extra text
- 6 to 12 tags total
- All tags must be lowercase English words

Tag categories to draw from (mix these naturally):
  Genre     : pop, rock, jazz, classical, electronic, folk, rnb, hiphop, ambient, cinematic, ballad, bossa_nova, country, blues, metal, lofi
  Mood      : happy, sad, melancholic, energetic, calm, romantic, tense, dreamy, nostalgic, hopeful, lonely, uplifting, dark, peaceful
  Tempo     : slow, mid_tempo, fast, upbeat, driving
  Instrument: piano, guitar, violin, cello, drums, bass, synthesizer, strings, flute, trumpet, choir, ukulele, accordion
  Texture   : acoustic, orchestral, minimal, layered, sparse, lush, raw, polished
  Vocal     : male_vocal, female_vocal, duet, instrumental (use exactly one, matching the vocal type specified by the user)

Example outputs:
piano,melancholic,slow,strings,orchestral,lonely,ballad,cinematic
guitar,happy,upbeat,folk,acoustic,hopeful,ukulele,bright
synthesizer,electronic,dark,driving,mid_tempo,tense,layered\
"""

DEFAULT_TAGS_USER = """\
Generate music style tags for the following request.

Theme / Request: {theme}
Language context: {language}
Song structure: {song_structure}
Vocal type: {vocal}

Remember: output ONLY the comma-separated tags, nothing else.\
"""

DEFAULT_LYRICS_SYSTEM = """\
You are a professional lyricist. Write song lyrics based on the user's request.

Strict structural rules:
- Always use these section markers on their own line: [Verse], [Pre-Chorus], [Chorus], [Bridge], [Outro]
- Each marker must appear on its own line with nothing else on that line
- Do NOT use [Intro] or any other markers not listed above

Section usage by song_structure:
  Short : [Verse] x1 → [Pre-Chorus] x1 → [Chorus] x1 → [Outro] x1
  Medium: [Verse] x2 → [Pre-Chorus] x1 → [Chorus] x2 → [Bridge] x1 → [Chorus] x1 → [Outro] x1
  Full  : [Verse] x2 → [Pre-Chorus] x1 → [Chorus] x2 → [Verse] x1 → [Pre-Chorus] x1 → [Chorus] x2 → [Bridge] x1 → [Chorus] x1 → [Outro] x1

Content rules:
- Write in the language specified by the user
- Match the mood and style described by the tags
- Chorus lines should be memorable and repeatable
- Bridge should provide emotional contrast
- Outro should be short (2-4 lines) and resolve the song

Output only the lyrics with section markers. No explanations, no titles, no comments.\
"""

DEFAULT_LYRICS_USER = """\
Write song lyrics with the following specifications.

Theme / Request: {theme}
Language: {language}
Song structure: {song_structure}
Vocal type: {vocal}
Style tags (use these to set mood and tone): {tags}

Follow the section marker rules exactly. Output only the lyrics.\
"""

# ── Ollama ────────────────────────────────────────────────────────
def _ollama_chat(url: str, model: str, system: str, user: str, temperature: float) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "stream": False,
        "options": {"temperature": temperature},
    }
    resp = requests.post(f"{url}/api/chat", json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()["message"]["content"].strip()

def _parse_tags(raw: str) -> str:
    for line in raw.splitlines():
        line = line.strip()
        if re.match(r'^[a-z_]+(,[a-z_]+)+$', line):
            return line
    tokens = re.findall(r'[a-z_]+', raw.lower())
    return ",".join(tokens[:12]) if tokens else "pop,vocal"

def _validate_lyrics(text: str) -> str:
    if "[Chorus]" not in text and "[chorus]" not in text.lower():
        text = "[Verse]\n" + text
    return text.strip()

# ── ステップ実行関数 ───────────────────────────────────────────────
def _fmt_elapsed(seconds: float) -> str:
    mins, secs = divmod(int(seconds), 60)
    return f"{mins}分{secs}秒" if mins else f"{secs}秒"

def generate_tags(
    ollama_url, model, language, song_structure, vocal, temperature,
    theme, tags_system, tags_user_tmpl
):
    t0 = time.time()
    user_msg = tags_user_tmpl.format(
        theme=theme, language=language, song_structure=song_structure, vocal=vocal
    )
    raw = _ollama_chat(ollama_url, model, tags_system, user_msg, temperature)
    return _parse_tags(raw), _fmt_elapsed(time.time() - t0)

def generate_lyrics(
    ollama_url, model, language, song_structure, vocal, temperature,
    theme, style_tags, lyrics_system, lyrics_user_tmpl
):
    t0 = time.time()
    user_msg = lyrics_user_tmpl.format(
        theme=theme, language=language, song_structure=song_structure,
        vocal=vocal, tags=style_tags
    )
    raw = _ollama_chat(ollama_url, model, lyrics_system, user_msg, temperature)
    return _validate_lyrics(raw), _fmt_elapsed(time.time() - t0)

_pipe      = None
_pipe_key  = None  # (version, codec_version, quantize_4bit)

def generate_music(
    style_tags, lyrics,
    version_label, codec_version, seed,
    max_seconds, topk, temperature, cfg_scale,
    keep_model_loaded, offload_mode, quantize_4bit
):
    global _pipe, _pipe_key
    from heartlib.pipelines.music_generation import HeartMuLaGenPipeline

    try:
        version = MODEL_VERSIONS.get(version_label, "HeartMuLa-oss-3B-happy-new-year")
        key     = (version, codec_version, quantize_4bit)
        print(f"[INFO] version={version}, codec={codec_version}, 4bit={quantize_4bit}")

        if _pipe is None or _pipe_key != key:
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            dtype  = torch.bfloat16 if torch.cuda.is_available() else torch.float32

            bnb_config = None
            if quantize_4bit and device.type == "cuda":
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
                codec_version=codec_version,
                lazy_load=True,
                bnb_config=bnb_config,
            )
            _pipe_key = key
            print("[INFO] Pipeline loaded")

        if seed == -1:
            seed = int(time.time() * 1000) % (2**31)
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed(seed)

        save_path = str(OUTPUT_DIR / f"music_{seed}.wav")
        print(f"[INFO] Generating: seed={seed}")

        t0 = time.time()
        with torch.inference_mode():
            _pipe(
                {"lyrics": lyrics, "tags": style_tags},
                max_audio_length_ms=max_seconds * 1000,
                save_path=save_path,
                topk=topk,
                temperature=temperature,
                cfg_scale=cfg_scale,
                keep_model_loaded=keep_model_loaded,
                offload_mode=offload_mode,
            )
        elapsed_str = _fmt_elapsed(time.time() - t0)

        import soundfile as sf
        info = sf.info(save_path)
        dur_mins, dur_secs = divmod(int(info.duration), 60)
        duration_str = f"{dur_mins}分{dur_secs}秒" if dur_mins else f"{dur_secs}秒"
        print(f"[INFO] 生成完了: {save_path} ({elapsed_str}, {duration_str})")

        if not keep_model_loaded:
            _pipe = None; _pipe_key = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        return save_path, elapsed_str, duration_str

    except Exception as e:
        print(f"[ERROR]\n{traceback.format_exc()}")
        raise gr.Error(str(e))

# ── UI ────────────────────────────────────────────────────────────
with gr.Blocks(title="GenerateMusic") as demo:
    gr.Markdown("## GenerateMusic")

    tags_system      = gr.State(DEFAULT_TAGS_SYSTEM)
    tags_user_tmpl   = gr.State(DEFAULT_TAGS_USER)
    lyrics_system    = gr.State(DEFAULT_LYRICS_SYSTEM)
    lyrics_user_tmpl = gr.State(DEFAULT_LYRICS_USER)

    # ── Ollama 設定（横一列）─────────────────────────────────────
    with gr.Row():
        ollama_url  = gr.Textbox(label="Ollama URL", value="http://localhost:11434", scale=2)
        model       = gr.Textbox(label="モデル",     value="qwen2.5:7b",             scale=1)
        language    = gr.Dropdown(label="言語",
                        choices=["Japanese","English","Chinese","Korean"],
                        value="Japanese", scale=1)
        song_struct = gr.Dropdown(label="曲の長さ",
                        choices=[
                            ("シンプル (Verse→Chorus×1)",          "Short"),
                            ("標準 (Verse×2→Chorus×2→Bridge)",     "Medium"),
                            ("フル (Verse×2→Chorus×4→Bridge)",     "Full"),
                        ], value="Medium", scale=1)
        vocal = gr.Dropdown(label="ボーカル",
                        choices=[
                            ("女性ボーカル", "female_vocal"),
                            ("男性ボーカル", "male_vocal"),
                            ("デュエット",   "duet"),
                            ("インストゥルメンタル", "instrumental"),
                        ], value="female_vocal", scale=1)
        temperature = gr.Slider(label="Temperature",
                        minimum=0.1, maximum=2.0, step=0.05, value=1.0, scale=2)

    # ── テーマ ────────────────────────────────────────────────────
    theme = gr.Textbox(label="テーマ", value="春の別れ、切ない恋の歌",
                       lines=2, max_lines=4)

    # ── ボタン（1行）─────────────────────────────────────────────
    with gr.Row():
        btn_tags   = gr.Button("① タグ生成",  variant="secondary")
        btn_lyrics = gr.Button("② 作詞",      variant="secondary")
        btn_music  = gr.Button("③ 作曲開始",  variant="primary")

    # ── タグ ／ 歌詞（左右並列）──────────────────────────────────
    with gr.Row():
        with gr.Column(scale=1):
            with gr.Row():
                gr.Markdown("**Style Tags（編集可）**", scale=3)
                tags_elapsed = gr.Textbox(show_label=False, scale=1, interactive=False,
                                          max_lines=1, placeholder="生成時間")
            style_tags = gr.Textbox(show_label=False, lines=3)
        with gr.Column(scale=2):
            with gr.Row():
                gr.Markdown("**Lyrics（編集可）**", scale=3)
                lyrics_elapsed = gr.Textbox(show_label=False, scale=1, interactive=False,
                                            max_lines=1, placeholder="生成時間")
            lyrics_box = gr.Textbox(show_label=False, lines=10)

    # ── HeartMuLa 設定 ───────────────────────────────────────────
    with gr.Row():
        version       = gr.Dropdown(label="バージョン",
                            choices=_available_versions(), value=_available_versions()[0], scale=3)
        codec_version = gr.Dropdown(label="Codec",
                            choices=CODEC_VERSIONS, value=CODEC_VERSIONS[0], scale=2)
        seed          = gr.Number(label="Seed (-1=ランダム)", value=-1, precision=0, scale=1)
        keep_model_loaded = gr.Checkbox(label="keep_model_loaded", value=True,  scale=1)
        quantize_4bit     = gr.Checkbox(label="quantize_4bit",     value=True,  scale=1)
        offload_mode      = gr.Dropdown(label="offload_mode",
                                choices=["auto", "aggressive"], value="auto", scale=1)
    with gr.Row():
        cfg_scale   = gr.Slider(label="CFG Scale", minimum=0.5, maximum=5.0,  step=0.1,  value=1.5)
        topk        = gr.Slider(label="Top-k",     minimum=1,   maximum=200,  step=1,    value=50)
        max_seconds = gr.Slider(label="最大秒数",  minimum=30,  maximum=600,  step=10,   value=210)

    with gr.Row():
        audio_out     = gr.Audio(label="生成音楽", type="filepath", scale=4)
        elapsed_text  = gr.Textbox(label="作曲時間", scale=1, interactive=False, max_lines=1)
        duration_text = gr.Textbox(label="曲の長さ", scale=1, interactive=False, max_lines=1)

    # ── イベント ───────────────────────────────────────────────
    btn_tags.click(
        fn=generate_tags,
        inputs=[ollama_url, model, language, song_struct, vocal, temperature,
                theme, tags_system, tags_user_tmpl],
        outputs=[style_tags, tags_elapsed],
        concurrency_limit=4,
    )
    btn_lyrics.click(
        fn=generate_lyrics,
        inputs=[ollama_url, model, language, song_struct, vocal, temperature,
                theme, style_tags, lyrics_system, lyrics_user_tmpl],
        outputs=[lyrics_box, lyrics_elapsed],
        concurrency_limit=4,
    )
    btn_music.click(
        fn=generate_music,
        inputs=[style_tags, lyrics_box, version, codec_version, seed,
                max_seconds, topk, temperature, cfg_scale,
                keep_model_loaded, offload_mode, quantize_4bit],
        outputs=[audio_out, elapsed_text, duration_text],
        concurrency_limit=1,
    )

if __name__ == "__main__":
    demo.queue(default_concurrency_limit=4).launch()

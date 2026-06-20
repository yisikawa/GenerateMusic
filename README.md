# GenerateMusic

Ollama（ローカルLLM）で歌詞とスタイルタグを生成し、[HeartMuLa](https://github.com/HeartMuLa/heartlib) で楽曲を生成するスタンドアロンの Gradio アプリです。

---

## 機能

- **① タグ生成** : Ollama にテーマ・ボーカル種別・曲の長さを渡し、HeartMuLa 用のスタイルタグを自動生成
- **② 作詞** : Ollama にスタイルタグを含むプロンプトを渡し、セクションマーカー付きの歌詞を自動生成
- **③ 作曲開始** : HeartMuLa が歌詞とタグから楽曲を生成し、WAV ファイルとして保存
- タグ・歌詞は画面上で直接編集可能
- 生成後に「タグ生成時間」「作詞時間」「作曲時間」「曲の長さ」を表示
- 4ビット量子化（BitsAndBytesConfig）対応でVRAM節約
- `models/` フォルダに配置したモデルを自動検出してドロップダウンに表示

---

## 動作環境

| 項目 | 内容 |
|---|---|
| OS | Windows 10/11 |
| GPU | NVIDIA RTX 3060 12GB VRAM（CUDA 12.x）以上推奨 |
| Python | 3.11 |
| CUDA | 12.8 以上 |
| Ollama | 最新版（`http://localhost:11434` で起動） |

---

## セットアップ

### 1. リポジトリのクローン

```bash
git clone https://github.com/yisikawa/GenerateMusic.git
cd GenerateMusic
```

### 2. 仮想環境の作成と有効化

```bash
python -m venv venv
venv\Scripts\activate
```

### 3. PyTorch（CUDA版）のインストール

```bash
pip install torch torchaudio torchvision --index-url https://download.pytorch.org/whl/cu128
```

### 4. 依存パッケージのインストール

```bash
pip install -r requirements.txt
```

### 5. HeartMuLa モデルの配置

以下の構成で `models/` フォルダにモデルファイルを配置してください。

```
models/
├── HeartMuLa-oss-3B-happy-new-year/   # 推奨（最新）
│   ├── model-00001-of-00004.safetensors
│   ├── model-00002-of-00004.safetensors
│   ├── model-00003-of-00004.safetensors
│   └── model-00004-of-00004.safetensors
├── HeartMuLa-oss-3B/                  # ベースモデル
├── HeartMuLa-RL-oss-3B-20260123/      # RLモデル
├── HeartCodec-oss-20260123/           # Codec（推奨）
├── HeartCodec-oss/                    # Codec（旧）
├── tokenizer.json
└── gen_config.json
```

モデルは [HeartMuLa HuggingFace](https://huggingface.co/HeartMuLa) から入手してください。

### 6. Ollama のセットアップ

[Ollama](https://ollama.com/) をインストールし、使用するモデルを pull してください。

```bash
ollama pull qwen2.5:7b
```

---

## 起動

```bash
venv\Scripts\activate
python app.py
```

ブラウザで `http://127.0.0.1:7860` を開きます。

---

## 使い方

1. **Ollama 設定** : URL・モデル・言語・曲の長さ・ボーカル・Temperature を設定
2. **テーマ** : 曲のテーマや雰囲気を日本語（または選択言語）で入力
3. **① タグ生成** : スタイルタグを自動生成（編集可）
4. **② 作詞** : 歌詞を自動生成（編集可）
5. **③ 作曲開始** : HeartMuLa で楽曲を生成（初回はモデルロードに数分かかります）

生成された WAV ファイルは `output/` フォルダに保存されます。

---

## HeartMuLa パラメータ

| パラメータ | 説明 | デフォルト |
|---|---|---|
| バージョン | 使用するHeartMuLaモデル | 自動検出 |
| Codec | HeartCodecのバージョン | oss-20260123 |
| Seed | 乱数シード（-1でランダム） | -1 |
| CFG Scale | Classifier-Free Guidance強度 | 1.5 |
| Top-k | サンプリング候補数 | 50 |
| 最大秒数 | 生成する音楽の最大長 | 210秒 |
| keep_model_loaded | 生成後もモデルをVRAMに保持 | ON |
| quantize_4bit | 4ビット量子化（VRAM節約） | ON |
| offload_mode | モデルオフロード方式 | auto |

---

## フォルダ構成

```
GenerateMusic/
├── app.py                  # メインアプリ
├── requirements.txt
├── heartlib/               # HeartMuLaライブラリ（ComfyUI版ベース）
│   ├── heartcodec/
│   ├── heartmula/
│   └── pipelines/
│       └── music_generation.py
├── models/                 # モデルファイル（.gitignore対象）
└── output/                 # 生成WAVファイル（.gitignore対象）
```

---

## 注意事項

- `models/` と `output/` は `.gitignore` によりリポジトリに含まれません
- `heartlib/` はローカルコピーです。ComfyUI 版をベースに `comfy.utils` 依存を除去しています
- 初回の作曲時はモデルのロードに 5〜10 分かかります（RTX 3060 + 4bit量子化の場合）
- GPU VRAM が不足する場合は `quantize_4bit` を ON にしてください

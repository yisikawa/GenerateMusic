# 設計書: 音楽生成のジョブキュー化とバックエンド共通化リファクタ

作成日: 2026-07-08
対象ブランチ: develop

## 背景と目的

現状の課題（設計レビューで確認済み）:

1. **キャンセル不能**: `frontend/src/api/client.ts` の `generateMusic` は abort 関数を返すが UI で未使用。さらにフロントが切断してもバックエンド（`backend/routers/music.py` の `run_pipeline`）は生成を最後まで続けるため、数分〜十数分の GPU 生成を止める手段がない。
2. **同時リクエストの無言ブロック**: `backend/services/pipeline.py` の `_lock` により、生成中に来た2つ目のリクエストは応答なしで数分待たされる（画面は「モデル読み込み中…」のまま）。
3. **定義の重複**: `_fmt_elapsed` が3ファイルに同一定義、モデルバージョン一覧・Ollamaデフォルト値がフロント/バック双方にハードコードされドリフトの温床。

本リファクタでは (1)(2) を「ジョブキュー＋単一ワーカー」方式で解決し、(3) の重複排除を行う。

GPU は1つなので並列実行はせず、**直列スケジューリング**とする。「SSE接続＝生成実行」を切り離し、以下の3段構成にする:

- ジョブ登録（即応答、待ち順を返す）
- 単一ワーカーによるキュー消化
- SSE による進捗購読（切断・再接続可能）

副次効果: SSE が切断されても生成は継続し、再接続すれば途中から購読を再開できる。

## API 仕様

| メソッド | パス | 役割 |
|---|---|---|
| `POST` | `/api/music` | ジョブ登録。即座に `{"job_id": str, "position": int}` を返す（position は待ち順、0=即実行） |
| `GET` | `/api/music/{job_id}/events` | SSE でジョブ状態を購読。購読開始時にまず**現在状態を1イベント送信**してから差分を流す（再接続時の状態復元） |
| `POST` | `/api/music/{job_id}/cancel` | キャンセル。`{"status": "cancelled"}` または現況を返す |
| `GET` | `/api/music/{job_id}` | 状態スナップショット（JSON、ポーリング・デバッグ用） |
| `GET` | `/api/config` | 起動時設定。バージョン一覧＋各種デフォルト値（後述） |

`/api/versions` は `/api/config` に統合して廃止する。
`/api/tags`, `/api/lyrics`, `/api/ollama-models` は現行のまま（スキーマの import 元だけ変更）。

### SSE イベント型

```
{ "type": "queued",    "position": int }             # 待機中（position は現在の待ち順）
{ "type": "loading" }                                 # モデル読み込み中
{ "type": "progress",  "current": int, "total": int } # 生成中
{ "type": "done",      "file_url": str, "elapsed": str, "duration": str }
{ "type": "error",     "message": str }
{ "type": "cancelled" }
```

`done` / `error` / `cancelled` は終端イベント。ハートビート（`: heartbeat\n\n`、30秒無イベント時）は現行踏襲。

### 存在しない job_id

`/events`・`/cancel`・スナップショットとも 404 を返す。

## バックエンド構成

```
backend/
  main.py            # lifespan でワーカー起動/停止
  schemas.py         # ★新規: Pydantic モデルを集約
  utils.py           # ★新規: format_elapsed など共通関数
  routers/
    music.py         # ジョブ登録・購読・キャンセル・スナップショットの4エンドポイント
    lyrics.py        # schemas/utils を import するよう変更
    tags.py          # 同上
  services/
    jobs.py          # ★新規: JobManager（キュー・状態・単一ワーカー）
    pipeline.py      # 純粋な生成処理に縮小（cancel_event と progress callback を受け取る）
    ollama.py        # 変更なし
    prompts.py       # 変更なし
```

### schemas.py（重複排除の中核）

```python
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

class MusicRequest(BaseModel):
    # 現 backend/routers/music.py の MusicRequest をそのまま移動
    ...

class TagsResponse(BaseModel): ...
class LyricsResponse(BaseModel): ...
```

ポイント: **Pydantic のデフォルト値がアプリ全体のデフォルト値の単一ソース**になる。`/api/config` はこれを `model_dump()` して返すだけ。

### utils.py

```python
def format_elapsed(seconds: float) -> str:
    mins, secs = divmod(int(seconds), 60)
    return f"{mins}分{secs}秒" if mins else f"{secs}秒"
```

現在 `pipeline.py` / `lyrics.py` / `tags.py` に3重定義されている `_fmt_elapsed` をこれに一本化。`pipeline.py` 内の再生時間フォーマット（`dur_mins, dur_secs = divmod(...)`）も同関数を使う。

### /api/config のレスポンス

```python
@router.get("/api/config")
async def get_config():
    return {
        "versions": pipeline_svc.available_versions(),
        "codec_versions": pipeline_svc.CODEC_VERSIONS,
        "ollama_defaults": OllamaRequestBase().model_dump(),
        "music_defaults": MusicRequest(tags="", lyrics="").model_dump(exclude={"tags", "lyrics"}),
    }
```

### services/jobs.py — JobManager（新規、設計の中核）

```python
@dataclass
class Job:
    id: str                      # uuid4().hex[:8]
    request: MusicRequest
    status: str = "queued"       # queued / loading / running / done / error / cancelled
    progress: tuple[int, int] = (0, 0)
    result: dict | None = None   # done 時の {file_url, elapsed, duration}
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    listeners: list[asyncio.Queue] = field(default_factory=list)  # SSE 購読者
```

JobManager の責務:

- `submit(request) -> (job_id, position)`: Job を生成して registry（dict）と `queue.Queue` に登録。
- **単一ワーカースレッド**: `lifespan` で起動、`queue.Queue` を順に消化。アプリ終了時は sentinel で停止。
  - 現行 `pipeline.py` の `_lock` は削除（直列性はワーカーが保証）。
  - モデルキャッシュ（`_pipe` / `_pipe_key`）はワーカースレッド専有となり、現行より安全。
- イベント配送: 状態変化・進捗を各 listener の `asyncio.Queue` へ `loop.call_soon_threadsafe` で push。メインの event loop 参照は lifespan 起動時に `asyncio.get_running_loop()` で捕捉して JobManager に渡す。
- `subscribe(job_id) -> asyncio.Queue`: 購読登録。**登録時に現在状態を合成した1イベントを即 put** してから差分配送（再接続対応）。`unsubscribe` で listener を除去。
- `cancel(job_id)`:
  - `queued` → registry 上で `cancelled` にし、ワーカーはキューから取り出した時点で status を見てスキップ。
  - `loading` / `running` → `cancel_event.set()`。
- 完了済みジョブ（done/error/cancelled）は**直近20件のみ保持**、超過分は古い順に registry から削除。

### キャンセルの実現方法

- **待機中**: 上記の通りスキップ。
- **実行中**: pipeline の tqdm progress callback 内で毎ステップ `cancel_event.is_set()` をチェックし、set なら `GenerationCancelled` 例外（jobs.py または pipeline.py で定義）を raise して生成ループを巻き戻す。生成1ステップは数百 ms なので実用上即座に止まる。
- **モデルロード中**: `from_pretrained` の中断は困難なため、**ロード完了直後・生成開始前に1回チェック**して生成に入らず `cancelled` にする仕様で割り切る（明記事項）。
- キャンセル・エラー時は書きかけの wav が残る可能性があるため、可能なら削除する（ベストエフォートで可）。

### pipeline.py の変更

- シグネチャを `generate(request: MusicRequest, progress_callback, cancel_event: threading.Event) -> dict` に変更。
- `_lock`、グローバルロック管理を削除（モデルキャッシュ `_pipe`/`_pipe_key` は残すが、呼び出し元が単一ワーカーであることを前提とする旨コメント）。
- `_patch_tqdm` のコールバック内でキャンセルチェックを行う（callback が `GenerationCancelled` を投げたら握りつぶさず伝播させること。現行の `except Exception: pass` は `GenerationCancelled` を除外する）。
- `format_elapsed` は `utils.py` から import。

### _resolve_model_path のヒューリスティック除去（ついで対応）

`"RL" in v or "2026" in v` の文字列推測をやめ、ラベル→ディレクトリ名の完全対応表にする:

```python
MODEL_VERSIONS = {
    "3B-happy-new-year (latest)": "HeartMuLa-oss-3B-happy-new-year",
    "RL-oss-3B-20260123":         "HeartMuLa-RL-oss-3B-20260123",
    "3B (base)":                  "HeartMuLa-oss-3B",
}
```

`_resolve_model_path` は `MODELS_DIR / MODEL_VERSIONS[label]` に単純化。
注意: `HeartMuLaGenPipeline.from_pretrained` に渡す `version` 引数の期待値は heartlib 側の実装を確認し、必要ならディレクトリ名をそのまま渡す形に合わせる（現行の挙動を壊さないこと）。

### main.py

- `lifespan` コンテキストマネージャで JobManager のワーカー起動・停止を行う。
- sys.path ハックは本設計のスコープ外（現行維持）。ただし schemas.py / utils.py の import は現行の import 方式（`from schemas import ...` 相当）に合わせる。

## フロントエンド変更

### api/client.ts

- `generateMusic` を3関数に分割:
  - `startMusic(req: MusicRequest): Promise<{ job_id: string; position: number }>`
  - `watchJob(jobId: string, onEvent: (e: MusicEvent) => void): () => void`（戻り値は購読解除関数）
  - `cancelJob(jobId: string): Promise<void>`
- `MusicEvent` に `queued`（position 付き）/ `loading` / `cancelled` を追加。
- `fetchVersions` → `fetchConfig` に変更（`/api/config` を叩く）。
- `watchJob` は接続が切れた場合（ネットワークエラー等）、終端イベント未受信なら**自動で再接続**する（例: 1秒待って再 GET。最大リトライ回数を設ける）。

### App.tsx

- 起動時に `fetchConfig` で `versions` / `codec_versions` / 各デフォルト値を取得して初期 state を組み立てる。
- `FALLBACK_VERSIONS` / `FALLBACK_CODECS` / `'qwen2.5:7b'` などのハードコードデフォルトは削除。config 取得失敗時は「バックエンドに接続できません」バナーを表示する（フォールバックで動いているように見せない）。
- 進捗表示の出し分け:
  - `queued` → 「待機中（あなたは◯番目）」
  - `loading` → 「モデル読み込み中…」
  - `progress` → 「作曲中: n / m フレーム」＋ progress バー
- 生成中（queued/loading/running）は**キャンセルボタン**を表示し、`cancelJob(jobId)` を呼ぶ。`cancelled` イベント受信で UI をリセット。
- 現在の `job_id` を state に保持。
- デッドコード `sharedOllamaProps ... void sharedOllamaProps`（App.tsx 202-206行付近）を削除。

## 実装ステップ（この順で。各ステップ完了時点でアプリが動作すること）

1. **共通化リファクタ（挙動不変）**
   - `backend/schemas.py` / `backend/utils.py` 新設、各 router から重複定義を除去。
   - `/api/config` 追加（`/api/versions` は一旦残してよい）。
   - `_resolve_model_path` の対応表化。
   - フロント: `fetchConfig` 対応、ハードコードデフォルト削除。
2. **ジョブキュー導入（キャンセルなし）**
   - `services/jobs.py` 新設、`music.py` をジョブ登録/SSE購読/スナップショットに書き換え。
   - `pipeline.py` から `_lock` 除去。
   - フロント: `startMusic` + `watchJob` 化、queued 表示。
3. **キャンセル対応**
   - `cancel_event` を pipeline に配線、`/cancel` エンドポイント、フロントのキャンセルボタン、SSE 自動再接続。

## 受け入れ基準

- [ ] タグ生成 → 作詞 → 作曲の一連フローが現行同様に動作する
- [ ] 作曲中に2つ目のリクエストを投げると即座に「待機中（2番目）」と表示され、1つ目の完了後に自動で開始される
- [ ] 待機中ジョブのキャンセルで即座に `cancelled` になる
- [ ] 実行中ジョブのキャンセルで生成が数秒以内に停止し、GPU メモリが解放される（keep_model_loaded=false 時）
- [ ] 作曲中にページをリロードしても生成は継続する（job_id を保持していれば再購読で進捗表示が復帰する、はスコープ外の任意対応）
- [ ] `_fmt_elapsed` の定義がリポジトリ内に1箇所のみ
- [ ] フロントにモデルバージョン一覧・Ollama デフォルト値のハードコードが残っていない
- [ ] バックエンド停止状態でフロントを開くと接続エラーバナーが表示される

## スコープ外（別課題）

- `backend` のパッケージ化・sys.path ハック解消
- output/ の履歴管理・クリーンアップ、seed 衝突対策
- temperature の Ollama / HeartMuLa 分離
- instrumental 判定の明示フラグ化
- App.tsx のコンポーネント分割

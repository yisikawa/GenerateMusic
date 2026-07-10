export interface TagsRequest {
  ollama_url: string
  model: string
  language: string
  song_structure: string
  vocal: string
  temperature: number
  theme: string
}

export interface TagsResponse {
  tags: string
  elapsed: string
}

export interface LyricsRequest extends TagsRequest {
  tags: string
}

export interface LyricsResponse {
  lyrics: string
  elapsed: string
}

export interface MusicRequest {
  tags: string
  lyrics: string
  version_label: string
  codec_version: string
  seed: number
  max_seconds: number
  topk: number
  temperature: number
  cfg_scale: number
  keep_model_loaded: boolean
  offload_mode: string
  quantize_4bit: boolean
}

export type MusicEvent =
  | { type: 'queued'; position: number }
  | { type: 'loading' }
  | { type: 'progress'; current: number; total: number }
  | { type: 'done'; file_url: string; elapsed: string; duration: string }
  | { type: 'error'; message: string }
  | { type: 'cancelled' }

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text)
  }
  return res.json() as Promise<T>
}

export async function generateTags(req: TagsRequest): Promise<TagsResponse> {
  return post<TagsResponse>('/api/tags', req)
}

export async function generateLyrics(req: LyricsRequest): Promise<LyricsResponse> {
  return post<LyricsResponse>('/api/lyrics', req)
}

export async function startMusic(req: MusicRequest): Promise<{ job_id: string; position: number }> {
  return post<{ job_id: string; position: number }>('/api/music', req)
}

const TERMINAL_EVENT_TYPES = new Set(['done', 'error', 'cancelled'])
const RECONNECT_DELAY_MS = 1000
const MAX_RECONNECT_ATTEMPTS = 5

export function watchJob(
  jobId: string,
  onEvent: (event: MusicEvent) => void,
): () => void {
  let es: EventSource | null = null
  let retryTimer: ReturnType<typeof setTimeout> | null = null
  let attempts = 0
  let stopped = false

  const connect = () => {
    es = new EventSource(`/api/music/${jobId}/events`)

    es.onopen = () => {
      attempts = 0
    }
    es.onmessage = (e) => {
      const event = JSON.parse(e.data) as MusicEvent
      onEvent(event)
      if (TERMINAL_EVENT_TYPES.has(event.type)) {
        stopped = true
        es?.close()
      }
    }
    es.onerror = () => {
      es?.close()
      if (stopped) return
      attempts += 1
      if (attempts > MAX_RECONNECT_ATTEMPTS) {
        onEvent({ type: 'error', message: 'サーバーとの接続が切断されました' })
        return
      }
      retryTimer = setTimeout(connect, RECONNECT_DELAY_MS)
    }
  }

  connect()

  return () => {
    stopped = true
    if (retryTimer) clearTimeout(retryTimer)
    es?.close()
  }
}

export async function cancelJob(jobId: string): Promise<void> {
  const res = await fetch(`/api/music/${jobId}/cancel`, { method: 'POST' })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text)
  }
}

export interface OllamaDefaults {
  ollama_url: string
  model: string
  language: string
  song_structure: string
  vocal: string
  temperature: number
  theme: string
}

export interface MusicDefaults {
  version_label: string
  codec_version: string
  seed: number
  max_seconds: number
  topk: number
  temperature: number
  cfg_scale: number
  keep_model_loaded: boolean
  offload_mode: string
  quantize_4bit: boolean
}

export interface AppConfig {
  versions: string[]
  codec_versions: string[]
  ollama_defaults: OllamaDefaults
  music_defaults: MusicDefaults
}

export async function fetchConfig(): Promise<AppConfig> {
  const res = await fetch('/api/config')
  if (!res.ok) throw new Error('config fetch failed')
  return res.json()
}

export async function fetchOllamaModels(ollamaUrl: string): Promise<string[]> {
  const res = await fetch(`/api/ollama-models?url=${encodeURIComponent(ollamaUrl)}`)
  if (!res.ok) throw new Error('ollama models fetch failed')
  const data = await res.json() as { models: string[] }
  return data.models
}

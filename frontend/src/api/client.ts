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
  | { type: 'progress'; current: number; total: number }
  | { type: 'done'; file_url: string; elapsed: string; duration: string }
  | { type: 'error'; message: string }

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

export function generateMusic(
  req: MusicRequest,
  onEvent: (event: MusicEvent) => void,
): () => void {
  const controller = new AbortController()

  fetch('/api/music', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok) {
        const text = await res.text()
        onEvent({ type: 'error', message: text })
        return
      }
      const reader = res.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop()!
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6).trim()
            if (data) onEvent(JSON.parse(data) as MusicEvent)
          }
        }
      }
    })
    .catch((err: Error) => {
      if (err.name !== 'AbortError') {
        onEvent({ type: 'error', message: err.message })
      }
    })

  return () => controller.abort()
}

export async function fetchVersions(): Promise<{ versions: string[]; codec_versions: string[] }> {
  const res = await fetch('/api/versions')
  if (!res.ok) throw new Error('versions fetch failed')
  return res.json()
}

import { useState, useCallback, useEffect } from 'react'
import {
  generateTags,
  generateLyrics,
  generateMusic,
  fetchVersions,
  type MusicEvent,
} from './api/client'

const FALLBACK_VERSIONS = [
  '3B-happy-new-year (latest)',
  'RL-oss-3B-20260123',
  '3B (base)',
]
const FALLBACK_CODECS = ['oss-20260123', 'oss']

export default function App() {
  // ── Ollama settings ─────────────────────────────────────────────
  const [ollamaUrl, setOllamaUrl] = useState('http://localhost:11434')
  const [model, setModel] = useState('qwen2.5:7b')
  const [language, setLanguage] = useState('Japanese')
  const [songStructure, setSongStructure] = useState('Medium')
  const [vocal, setVocal] = useState('female_vocal')
  const [temperature, setTemperature] = useState(1.0)

  // ── Theme ────────────────────────────────────────────────────────
  const [theme, setTheme] = useState('春の別れ、切ない恋の歌')

  // ── Generated content ────────────────────────────────────────────
  const [tags, setTags] = useState('')
  const [tagsElapsed, setTagsElapsed] = useState('')
  const [lyrics, setLyrics] = useState('')
  const [lyricsElapsed, setLyricsElapsed] = useState('')

  // ── HeartMuLa settings ──────────────────────────────────────────
  const [availableVersions, setAvailableVersions] = useState<string[]>(FALLBACK_VERSIONS)
  const [availableCodecs, setAvailableCodecs] = useState<string[]>(FALLBACK_CODECS)
  const [versionLabel, setVersionLabel] = useState(FALLBACK_VERSIONS[0])
  const [codecVersion, setCodecVersion] = useState(FALLBACK_CODECS[0])
  const [seed, setSeed] = useState(-1)
  const [keepModelLoaded, setKeepModelLoaded] = useState(false)
  const [quantize4bit, setQuantize4bit] = useState(true)
  const [offloadMode, setOffloadMode] = useState('auto')

  // ── Generation params ────────────────────────────────────────────
  const [cfgScale, setCfgScale] = useState(1.5)
  const [topk, setTopk] = useState(50)
  const [maxSeconds, setMaxSeconds] = useState(210)

  // ── Output ───────────────────────────────────────────────────────
  const [audioUrl, setAudioUrl] = useState('')
  const [elapsed, setElapsed] = useState('')
  const [duration, setDuration] = useState('')
  const [progress, setProgress] = useState<{ current: number; total: number } | null>(null)

  // ── UI state ─────────────────────────────────────────────────────
  const [tagsLoading, setTagsLoading] = useState(false)
  const [lyricsLoading, setLyricsLoading] = useState(false)
  const [musicLoading, setMusicLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    fetchVersions()
      .then(({ versions, codec_versions }) => {
        if (versions.length) {
          setAvailableVersions(versions)
          setVersionLabel(versions[0])
        }
        if (codec_versions.length) {
          setAvailableCodecs(codec_versions)
          setCodecVersion(codec_versions[0])
        }
      })
      .catch(() => {})
  }, [])

  const handleTagsGenerate = useCallback(async () => {
    setTagsLoading(true)
    setError('')
    try {
      const result = await generateTags({
        ollama_url: ollamaUrl,
        model,
        language,
        song_structure: songStructure,
        vocal,
        temperature,
        theme,
      })
      setTags(result.tags)
      setTagsElapsed(result.elapsed)
    } catch (e) {
      setError(String(e))
    } finally {
      setTagsLoading(false)
    }
  }, [ollamaUrl, model, language, songStructure, vocal, temperature, theme])

  const handleLyricsGenerate = useCallback(async () => {
    setLyricsLoading(true)
    setError('')
    try {
      const result = await generateLyrics({
        ollama_url: ollamaUrl,
        model,
        language,
        song_structure: songStructure,
        vocal,
        temperature,
        theme,
        tags,
      })
      setLyrics(result.lyrics)
      setLyricsElapsed(result.elapsed)
    } catch (e) {
      setError(String(e))
    } finally {
      setLyricsLoading(false)
    }
  }, [ollamaUrl, model, language, songStructure, vocal, temperature, theme, tags])

  const handleMusicGenerate = useCallback(() => {
    setMusicLoading(true)
    setProgress(null)
    setAudioUrl('')
    setElapsed('')
    setDuration('')
    setError('')

    generateMusic(
      {
        tags,
        lyrics,
        version_label: versionLabel,
        codec_version: codecVersion,
        seed,
        max_seconds: maxSeconds,
        topk,
        temperature,
        cfg_scale: cfgScale,
        keep_model_loaded: keepModelLoaded,
        offload_mode: offloadMode,
        quantize_4bit: quantize4bit,
      },
      (event: MusicEvent) => {
        if (event.type === 'progress') {
          setProgress({ current: event.current, total: event.total })
        } else if (event.type === 'done') {
          setAudioUrl(event.file_url)
          setElapsed(event.elapsed)
          setDuration(event.duration)
          setMusicLoading(false)
          setProgress(null)
        } else {
          setError(event.message)
          setMusicLoading(false)
          setProgress(null)
        }
      },
    )
  }, [
    tags, lyrics, versionLabel, codecVersion, seed,
    maxSeconds, topk, temperature, cfgScale,
    keepModelLoaded, offloadMode, quantize4bit,
  ])

  const sharedOllamaProps = {
    ollama_url: ollamaUrl, model, language,
    song_structure: songStructure, vocal, temperature,
  }
  void sharedOllamaProps

  return (
    <div className="app">
      <h2>GenerateMusic</h2>

      {/* ── Ollama Settings ───────────────────────────────────────── */}
      <section className="card">
        <div className="row wrap">
          <label className="field-lg">
            <span>Ollama URL</span>
            <input value={ollamaUrl} onChange={e => setOllamaUrl(e.target.value)} />
          </label>
          <label className="field-sm">
            <span>モデル</span>
            <input value={model} onChange={e => setModel(e.target.value)} />
          </label>
          <label className="field-sm">
            <span>言語</span>
            <select value={language} onChange={e => setLanguage(e.target.value)}>
              <option>Japanese</option>
              <option>English</option>
              <option>Chinese</option>
              <option>Korean</option>
            </select>
          </label>
          <label className="field-md">
            <span>曲の長さ</span>
            <select value={songStructure} onChange={e => setSongStructure(e.target.value)}>
              <option value="Short">シンプル (Verse→Chorus×1)</option>
              <option value="Medium">標準 (Verse×2→Chorus×2→Bridge)</option>
              <option value="Full">フル (Verse×2→Chorus×4→Bridge)</option>
            </select>
          </label>
          <label className="field-sm">
            <span>ボーカル</span>
            <select value={vocal} onChange={e => setVocal(e.target.value)}>
              <option value="female_vocal">女性ボーカル</option>
              <option value="male_vocal">男性ボーカル</option>
              <option value="duet">デュエット</option>
              <option value="instrumental">インストゥルメンタル</option>
            </select>
          </label>
          <label className="field-md">
            <span>Temperature: {temperature.toFixed(2)}</span>
            <input
              type="range" min="0.1" max="2.0" step="0.05"
              value={temperature}
              onChange={e => setTemperature(Number(e.target.value))}
            />
          </label>
        </div>
      </section>

      {/* ── Theme ─────────────────────────────────────────────────── */}
      <section className="card">
        <label className="field-full">
          <span>テーマ</span>
          <textarea
            value={theme}
            onChange={e => setTheme(e.target.value)}
            rows={2}
          />
        </label>
      </section>

      {/* ── Buttons ───────────────────────────────────────────────── */}
      <div className="row buttons">
        <button
          className="btn-secondary"
          onClick={handleTagsGenerate}
          disabled={tagsLoading}
        >
          {tagsLoading ? '生成中…' : '① タグ生成'}
        </button>
        <button
          className="btn-secondary"
          onClick={handleLyricsGenerate}
          disabled={lyricsLoading}
        >
          {lyricsLoading ? '生成中…' : '② 作詞'}
        </button>
        <button
          className="btn-primary"
          onClick={handleMusicGenerate}
          disabled={musicLoading}
        >
          {musicLoading ? '作曲中…' : '③ 作曲開始'}
        </button>
      </div>

      {/* ── Tags / Lyrics ─────────────────────────────────────────── */}
      <div className="row content-cols">
        <section className="card col-1">
          <div className="panel-header">
            <strong>Style Tags（編集可）</strong>
            <span className="elapsed">{tagsElapsed}</span>
          </div>
          <textarea
            value={tags}
            onChange={e => setTags(e.target.value)}
            rows={3}
          />
        </section>
        <section className="card col-2">
          <div className="panel-header">
            <strong>Lyrics（編集可）</strong>
            <span className="elapsed">{lyricsElapsed}</span>
          </div>
          <textarea
            value={lyrics}
            onChange={e => setLyrics(e.target.value)}
            rows={10}
          />
        </section>
      </div>

      {/* ── HeartMuLa Settings ────────────────────────────────────── */}
      <section className="card">
        <div className="row wrap">
          <label className="field-md">
            <span>バージョン</span>
            <select value={versionLabel} onChange={e => setVersionLabel(e.target.value)}>
              {availableVersions.map(v => <option key={v}>{v}</option>)}
            </select>
          </label>
          <label className="field-sm">
            <span>Codec</span>
            <select value={codecVersion} onChange={e => setCodecVersion(e.target.value)}>
              {availableCodecs.map(v => <option key={v}>{v}</option>)}
            </select>
          </label>
          <label className="field-sm">
            <span>Seed (-1=ランダム)</span>
            <input
              type="number"
              value={seed}
              onChange={e => setSeed(Number(e.target.value))}
            />
          </label>
          <label className="field-check">
            <input
              type="checkbox"
              checked={keepModelLoaded}
              onChange={e => setKeepModelLoaded(e.target.checked)}
            />
            <span>keep_model_loaded</span>
          </label>
          <label className="field-check">
            <input
              type="checkbox"
              checked={quantize4bit}
              onChange={e => setQuantize4bit(e.target.checked)}
            />
            <span>quantize_4bit</span>
          </label>
          <label className="field-sm">
            <span>offload_mode</span>
            <select value={offloadMode} onChange={e => setOffloadMode(e.target.value)}>
              <option>auto</option>
              <option>aggressive</option>
            </select>
          </label>
        </div>
        <div className="row wrap" style={{ marginTop: '0.75rem' }}>
          <label className="field-md">
            <span>CFG Scale: {cfgScale.toFixed(1)}</span>
            <input
              type="range" min="0.5" max="5.0" step="0.1"
              value={cfgScale}
              onChange={e => setCfgScale(Number(e.target.value))}
            />
          </label>
          <label className="field-md">
            <span>Top-k: {topk}</span>
            <input
              type="range" min="1" max="200" step="1"
              value={topk}
              onChange={e => setTopk(Number(e.target.value))}
            />
          </label>
          <label className="field-md">
            <span>最大秒数: {maxSeconds}秒</span>
            <input
              type="range" min="30" max="600" step="10"
              value={maxSeconds}
              onChange={e => setMaxSeconds(Number(e.target.value))}
            />
          </label>
        </div>
      </section>

      {/* ── Progress ──────────────────────────────────────────────── */}
      {musicLoading && (
        <div className="progress-wrap">
          {progress ? (
            <>
              <div className="progress-label">
                作曲中: {progress.current} / {progress.total} フレーム
              </div>
              <progress value={progress.current} max={progress.total} />
            </>
          ) : (
            <div className="progress-label">モデル読み込み中…</div>
          )}
        </div>
      )}

      {/* ── Error ─────────────────────────────────────────────────── */}
      {error && <div className="error-box">{error}</div>}

      {/* ── Output ────────────────────────────────────────────────── */}
      <section className="card">
        <div className="row output-row">
          <div className="audio-wrap">
            <span>生成音楽</span>
            {audioUrl ? (
              <audio controls src={audioUrl} />
            ) : (
              <div className="audio-placeholder">音楽が生成されると表示されます</div>
            )}
          </div>
          <div className="stat-box">
            <span className="stat-label">作曲時間</span>
            <span className="stat-value">{elapsed || '—'}</span>
          </div>
          <div className="stat-box">
            <span className="stat-label">曲の長さ</span>
            <span className="stat-value">{duration || '—'}</span>
          </div>
        </div>
      </section>
    </div>
  )
}

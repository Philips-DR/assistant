// Buttons for meetings: record, transcribe, write notes. The same tools the model calls in
// chat, called directly -- no model, no waiting on one.

import { useEffect, useState, type ReactElement } from 'react'
import { runAction } from '../api'
import { useAppState } from '../state'
import { clock, fileName, usePoll } from '../usePoll'

interface Session {
  id: string
  state: 'recording' | 'orphaned' | 'stopped'
  source: string
  recorded_seconds?: number
  audio?: string | null
  duration_seconds?: number | null
  max_volume_db?: number | null
  warnings?: string[]
}

interface Job {
  id: string
  audio: string
  state: 'running' | 'done' | 'failed' | 'interrupted'
  phase: string
  percent: number | null
  eta: string | null
  markdown: string
  timeline: string
  detail: string
}

interface Recordings {
  audio: string[]
  transcripts: { markdown: string; timeline: string | null; notes: string | null; minutes?: string | null }[]
}

async function call<T>(tool: string, args: Record<string, unknown> = {}): Promise<T> {
  const result = await runAction<T & { error?: string }>(tool, args)
  const output = result.output
  if (output && typeof output === 'object' && 'error' in output && output.error) {
    throw new Error(String(output.error))
  }
  return output as T
}

function Recorder({ onStopped }: { onStopped: (audio: string) => void }) {
  const [consent, setConsent] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [last, setLast] = useState<Session | null>(null)

  const status = usePoll(
    () => call<{ session: Session | null }>('meet_ai__recording_status'),
    2000,
  )
  const session = status.data?.session ?? null

  const act = async (fn: () => Promise<void>) => {
    setBusy(true)
    setError('')
    try {
      await fn()
      await status.reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const start = () =>
    act(async () => {
      setLast(null)
      await call('meet_ai__start_recording', consent.trim() ? { consent: consent.trim() } : {})
    })

  const stop = () =>
    act(async () => {
      const done = await call<Session>('meet_ai__stop_recording')
      setLast(done)
      if (done.audio) onStopped(done.audio)
    })

  return (
    <div className="card">
      <h2>Record</h2>
      {session?.state === 'recording' ? (
        <div className="live">
          <span className="rec-dot" aria-hidden />
          <span className="rec-clock">{clock(session.recorded_seconds)}</span>
          <span className="muted">recording {session.id}</span>
          <button className="danger" disabled={busy} onClick={() => void stop()}>
            Stop
          </button>
        </div>
      ) : session?.state === 'orphaned' ? (
        <div className="warn-box">
          <p>
            Recording <strong>{session.id}</strong> was interrupted with {clock(session.recorded_seconds)} on disk.
          </p>
          <button className="primary" disabled={busy} onClick={() => void stop()}>
            Recover it
          </button>
        </div>
      ) : (
        <div className="row">
          <input
            value={consent}
            onChange={(e) => setConsent(e.target.value)}
            placeholder='Who agreed to be recorded — e.g. "verbal, all present"'
            aria-label="Consent"
          />
          <button className="primary" disabled={busy} onClick={() => void start()}>
            Start recording
          </button>
        </div>
      )}

      {last && (
        <div className="result">
          Saved <strong>{fileName(last.audio)}</strong> · {clock(last.duration_seconds)} · peak {last.max_volume_db} dB
          {last.warnings?.map((w) => (
            <p key={w} className="warn">{w}</p>
          ))}
        </div>
      )}
      {(error || status.error) && <p className="error">{error || status.error}</p>}
      <p className="hint">One microphone records everyone in the room together; speaker labels are still inferred.</p>
    </div>
  )
}

function Transcriber({ audio, setAudio }: { audio: string; setAudio: (a: string) => void }) {
  const [speakers, setSpeakers] = useState(false)
  const [count, setCount] = useState(4)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const status = usePoll(() => call<{ job: Job | null }>('meet_ai__transcription_status'), 5000)
  const recordings = usePoll(() => call<Recordings>('meet_ai__list_recordings'), 30000)
  const job = status.data?.job ?? null
  const running = job?.state === 'running'

  const start = async () => {
    setBusy(true)
    setError('')
    try {
      await call('meet_ai__start_transcription', {
        audio,
        ...(speakers ? { diarize: true, speakers: count } : {}),
      })
      await status.reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <h2>Transcribe</h2>

      {job && (
        <div className={`job job-${job.state}`}>
          <div className="job-head">
            <strong>{fileName(job.audio)}</strong>
            <span className="badge">{job.state === 'running' ? job.phase : job.state}</span>
          </div>
          {running && (
            <>
              <div className="bar" role="progressbar" aria-valuenow={job.percent ?? 0} aria-valuemin={0} aria-valuemax={100}>
                <div style={{ width: `${job.percent ?? 0}%` }} />
              </div>
              <p className="muted">
                {job.percent != null ? `${job.percent.toFixed(1)}%` : job.phase}
                {job.eta ? ` · about ${job.eta} left` : ''}
              </p>
            </>
          )}
          {job.state === 'done' && <p className="muted">Transcript ready: {fileName(job.markdown)}</p>}
          {(job.state === 'failed' || job.state === 'interrupted') && <p className="warn">{job.detail}</p>}
        </div>
      )}

      {!running && (
        <div className="stack">
          <div className="row">
            <input
              list="audio-files"
              value={audio}
              onChange={(e) => setAudio(e.target.value)}
              placeholder="Audio file — pick one, or paste a path"
              aria-label="Audio file"
            />
            <datalist id="audio-files">
              {recordings.data?.audio.map((a) => <option key={a} value={a}>{fileName(a)}</option>)}
            </datalist>
          </div>
          <div className="row">
            <label className="check">
              <input type="checkbox" checked={speakers} onChange={(e) => setSpeakers(e.target.checked)} />
              Label speakers
            </label>
            {speakers && (
              <label className="check">
                people present
                <input type="number" min={1} max={30} value={count} onChange={(e) => setCount(Number(e.target.value))} />
              </label>
            )}
            <button className="primary" disabled={busy || !audio.trim()} onClick={() => void start()}>
              Transcribe
            </button>
          </div>
          {speakers && <p className="hint">Give the real headcount — guessing over-splits badly.</p>}
        </div>
      )}
      {(error || status.error) && <p className="error">{error || status.error}</p>}
    </div>
  )
}

interface Preview { segments: number; words: number; approx_tokens: number }

// Notes and minutes are two outputs of one transcript, made the same way: a model writes,
// every point is checked against the transcript, and docu-ai compiles the file on its own
// -- meet-ai never learns docu-ai exists.
interface Written {
  markdown: string
  verified_claims: number
  dropped_claims: number
  summary: string
}

interface BuiltDoc {
  url: string
  title: string
  residue: string[]
}

type Kind = 'notes' | 'minutes'

const KINDS: { kind: Kind; label: string; tool: string; working: string }[] = [
  { kind: 'notes', label: 'Notes', tool: 'meet_ai__generate_notes', working: 'Writing notes…' },
  { kind: 'minutes', label: 'Minutes', tool: 'meet_ai__generate_minutes', working: 'Writing minutes…' },
]

function describe(kind: Kind, output: Record<string, unknown>): string {
  if (kind === 'minutes') {
    const items = (output.items as string[] | undefined) ?? []
    return `“${String(output.title)}” — ${items.length} agenda items, ${String(output.verified_claims)} verified points`
  }
  return `${String(output.verified_claims)} verified claims — ${String(output.decisions)} decisions, ${String(output.actions)} actions, ${String(output.questions)} questions`
}

interface TranscriptText { text: string; truncated: boolean; end: number; duration: number }

/** The transcript itself, to check a line against. A read-only call, so it is neither
 * audited nor noted for the model -- looking is not acting. */
function TranscriptReader({ path }: { path: string }) {
  const [paragraphs, setParagraphs] = useState<string[] | null>(null)
  const [truncated, setTruncated] = useState(false)
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    call<TranscriptText>('meet_ai__read_transcript', { transcript: path })
      .then((t) => {
        setParagraphs(t.text.split('\n\n'))
        setTruncated(t.truncated)
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
  }, [path])

  const needle = query.trim().toLowerCase()
  const shown = (paragraphs ?? []).filter((p) => !needle || p.toLowerCase().includes(needle))

  const highlight = (text: string) => {
    if (!needle) return text
    const parts: (string | ReactElement)[] = []
    let from = 0
    const lower = text.toLowerCase()
    for (let at = lower.indexOf(needle); at >= 0; at = lower.indexOf(needle, from)) {
      parts.push(text.slice(from, at), <mark key={at}>{text.slice(at, at + needle.length)}</mark>)
      from = at + needle.length
    }
    parts.push(text.slice(from))
    return parts
  }

  return (
    <div className="transcript">
      <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search the transcript" aria-label="Search the transcript" />
      {error && <p className="error">{error}</p>}
      {!paragraphs && !error && <p className="muted">Loading…</p>}
      {paragraphs && (
        <p className="muted small">
          {needle ? `${shown.length} of ${paragraphs.length} paragraphs match` : `${paragraphs.length} paragraphs`}
          {truncated && ' · very long transcript: only the first part is shown'}
        </p>
      )}
      <div className="transcript-text">
        {shown.map((p, i) => {
          const match = /^\[(\d\d:\d\d:\d\d)\]\s*(.*)$/s.exec(p)
          return (
            <p key={i}>
              {match ? <><span className="stamp">{match[1]}</span> {highlight(match[2] ?? '')}</> : highlight(p)}
            </p>
          )
        })}
      </div>
    </div>
  )
}

function Notes() {
  const recordings = usePoll(() => call<Recordings>('meet_ai__list_recordings'), 15000)
  const [previews, setPreviews] = useState<Record<string, Preview>>({})
  const [results, setResults] = useState<Record<string, Written & Record<string, unknown>>>({})
  const [docs, setDocs] = useState<Record<string, BuiltDoc>>({})
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [reading, setReading] = useState('')
  const tools = useAppState().tools

  const ready = recordings.data?.transcripts.filter((t) => t.timeline) ?? []
  const kinds = KINDS.filter((k) => tools.has(k.tool))

  const run = async (key: string, work: () => Promise<void>) => {
    setBusy(key)
    setError('')
    try {
      await work()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  const preview = (timeline: string) =>
    run(`preview:${timeline}`, async () => {
      const p = await call<Preview>('meet_ai__preview_notes', { timeline })
      setPreviews((all) => ({ ...all, [timeline]: p }))
    })

  const write = (kind: (typeof KINDS)[number], timeline: string) =>
    run(`${kind.kind}:${timeline}`, async () => {
      const r = await call<Written & Record<string, unknown>>(kind.tool, { timeline })
      setResults((all) => ({ ...all, [`${kind.kind}:${timeline}`]: r }))
      await recordings.reload()
    })

  const makeDoc = (path: string) =>
    run(`doc:${path}`, async () => {
      const built = await call<BuiltDoc>('docu_ai__build', { path })
      setDocs((all) => ({ ...all, [path]: built }))
    })

  return (
    <div className="card">
      <h2>Notes and minutes</h2>
      {ready.length === 0 && <p className="muted">No transcripts with a timeline yet. Transcribe a recording first.</p>}
      <ul className="list">
        {ready.map((t) => {
          const timeline = t.timeline ?? ''
          const p = previews[timeline]
          return (
            <li key={timeline}>
              <div className="list-main">
                <strong>{fileName(t.markdown)}</strong>
                <div className="row">
                  {tools.has('meet_ai__read_transcript') && (
                    <button onClick={() => setReading(reading === t.markdown ? '' : t.markdown)}>
                      {reading === t.markdown ? 'Close transcript' : 'Read transcript'}
                    </button>
                  )}
                  <button disabled={busy === `preview:${timeline}`} onClick={() => void preview(timeline)}>Preview</button>
                </div>
              </div>
              {reading === t.markdown && <TranscriptReader path={t.markdown} />}
              {p && <p className="muted">{p.words.toLocaleString()} words · about {p.approx_tokens.toLocaleString()} tokens to send</p>}
              {kinds.map((k) => {
                const key = `${k.kind}:${timeline}`
                const r = results[key]
                const path = r?.markdown ?? (k.kind === 'notes' ? t.notes : t.minutes) ?? ''
                const doc = path ? docs[path] : undefined
                return (
                  <div key={k.kind} className="output">
                    <div className="row">
                      <span className="output-label">{k.label}</span>
                      <button className={path ? '' : 'primary'} disabled={busy !== ''} onClick={() => void write(k, timeline)}>
                        {busy === key ? k.working : path ? 'Write again' : `Write ${k.kind}`}
                      </button>
                      {path && (
                        <button className="primary" disabled={busy !== ''} onClick={() => void makeDoc(path)}>
                          {busy === `doc:${path}` ? 'Building the Doc…' : 'Make a Google Doc'}
                        </button>
                      )}
                      {path && !r && <span className="badge done">written</span>}
                    </div>
                    {r && (
                      <p className="result">
                        {describe(k.kind, r)}
                        {r.dropped_claims > 0 && <span className="warn"> · {r.dropped_claims} dropped: quote not found in the transcript</span>}
                      </p>
                    )}
                    {doc && (
                      <p className="result">
                        <a href={doc.url} target="_blank" rel="noreferrer">Open “{doc.title}” in Google Docs</a>
                        {doc.residue.length > 0 && <span className="warn"> · markdown residue: {doc.residue.join('; ')}</span>}
                      </p>
                    )}
                  </div>
                )
              })}
            </li>
          )
        })}
      </ul>
      {(error || recordings.error) && <p className="error">{error || recordings.error}</p>}
      <p className="hint">
        Every point carries a quote found word-for-word in the transcript; anything that can't be found is dropped.
        Minutes leave attendance for the secretary — a recording can't show who was present.
      </p>
    </div>
  )
}

export function Meetings() {
  const [audio, setAudio] = useState('')
  return (
    <div className="panel">
      <Recorder onStopped={setAudio} />
      <Transcriber audio={audio} setAudio={setAudio} />
      <Notes />
    </div>
  )
}

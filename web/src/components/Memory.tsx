// What the assistant knows about you. Adding and forgetting go through the same remember and
// forget tools the model uses, so they are audited -- and the model sees the change on its
// very next turn.

import { useState } from 'react'
import { runAction } from '../api'
import { usePoll } from '../usePoll'

interface Fact { id: string; kind: string; subject: string; content: string; created: string }

const KINDS: { kind: string; label: string; hint: string }[] = [
  { kind: 'person', label: 'People', hint: 'Who someone is.' },
  { kind: 'project', label: 'Projects', hint: 'What you are working on.' },
  { kind: 'preference', label: 'Preferences', hint: 'How you like things done.' },
  { kind: 'spelling', label: 'Spellings', hint: 'Correct spelling, then the misheard forms, comma-separated. Used to fix transcripts.' },
  { kind: 'fact', label: 'Other', hint: 'Anything else worth knowing.' },
]

async function call<T>(tool: string, args: Record<string, unknown> = {}): Promise<T> {
  const result = await runAction<T & { error?: string }>(tool, args)
  const output = result.output
  if (output && typeof output === 'object' && 'error' in output && output.error) throw new Error(String(output.error))
  return output as T
}

export function Memory() {
  const facts = usePoll(() => call<{ facts: Fact[] }>('assistant__recall'), 20000)
  const [kind, setKind] = useState('person')
  const [subject, setSubject] = useState('')
  const [content, setContent] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  const act = async (label: string, fn: () => Promise<void>) => {
    setBusy(label)
    setError('')
    try {
      await fn()
      await facts.reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy('')
    }
  }

  const add = () => act('add', async () => {
    await call('assistant__remember', { kind, subject: subject.trim(), content: content.trim() })
    setSubject('')
    setContent('')
  })

  const forget = (id: string) => act(id, async () => {
    await call('assistant__forget', { id })
  })

  const all = facts.data?.facts ?? []
  const hint = KINDS.find((k) => k.kind === kind)?.hint

  return (
    <div className="panel">
      <div className="card">
        <h2>Remember something</h2>
        <form className="stack" onSubmit={(e) => { e.preventDefault(); void add() }}>
          <div className="row">
            <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Kind">
              {KINDS.map((k) => <option key={k.kind} value={k.kind}>{k.label}</option>)}
            </select>
            <input value={subject} onChange={(e) => setSubject(e.target.value)}
              placeholder={kind === 'spelling' ? 'Correct spelling — e.g. AyaData' : 'About — e.g. Kwame'} aria-label="Subject" />
          </div>
          <div className="row">
            <input value={content} onChange={(e) => setContent(e.target.value)}
              placeholder={kind === 'spelling' ? 'Misheard as — e.g. aya data, ayadata' : 'What to remember'} aria-label="Content" />
            <button className="primary" type="submit" disabled={!subject.trim() || !content.trim() || busy === 'add'}>Remember</button>
          </div>
          {hint && <p className="hint">{hint} Saving the same kind and subject again replaces the old note.</p>}
        </form>
        {(error || facts.error) && <p className="error">{error || facts.error}</p>}
      </div>

      {KINDS.map(({ kind: k, label }) => {
        const group = all.filter((f) => f.kind === k)
        if (group.length === 0) return null
        return (
          <div className="card" key={k}>
            <h2>{label}</h2>
            <ul className="list facts">
              {group.map((f) => (
                <li key={f.id}>
                  <div className="fact">
                    <div>
                      <strong>{f.subject}</strong>
                      <p className="muted">{f.content}</p>
                    </div>
                    <button disabled={busy === f.id} onClick={() => void forget(f.id)}>Forget</button>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )
      })}

      {facts.data && all.length === 0 && (
        <div className="card"><p className="muted">Nothing remembered yet.</p></div>
      )}
    </div>
  )
}

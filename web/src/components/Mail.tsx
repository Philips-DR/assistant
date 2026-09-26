// Buttons for mail. Reading, searching and syncing always; drafting and sending only when
// mail-ai has been given them -- the page asks the server what exists rather than assuming.

import { useState } from 'react'
import { runAction } from '../api'
import { useAppState } from '../state'
import { usePoll } from '../usePoll'

interface Status { messages: number; threads: number; newest: string; full_sync_complete: boolean }
interface Thread { thread_id: string; subject: string; started_by: string; messages: number; last: string }
interface Message { id: string; from: string; to: string; at: string; body: string }
interface ThreadDetail { thread_id: string; subject: string; messages: Message[] }
interface Draft { draft_id: string; to: string; subject: string; thread_id: string; confirmation: string }
interface Found { id: string; thread_id: string; from_addr: string; subject: string; at: string }

async function call<T>(tool: string, args: Record<string, unknown> = {}): Promise<T> {
  const result = await runAction<T & { error?: string }>(tool, args)
  const output = result.output
  if (output && typeof output === 'object' && 'error' in output && output.error) throw new Error(String(output.error))
  return output as T
}

const when = (iso: string) => (iso ? new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : '')
const who = (address: string) => address.replace(/<.*>/, '').replace(/"/g, '').trim() || address

/** Sending is the one thing here that cannot be undone, so it is shown in full first. */
function SendConfirm({ preview, onSend, onCancel, sending }: {
  preview: string | null; onSend: () => void; onCancel: () => void; sending: boolean
}) {
  return (
    <div className="approval">
      <div className="approval-head">
        <span className="approval-kicker">This will send</span>
        <span className="approval-tool">and cannot be undone</span>
      </div>
      {preview
        ? <pre className="approval-preview">{preview}</pre>
        : <p className="approval-warning">The email could not be shown. Sending means sending it unseen.</p>}
      <div className="approval-actions">
        <button className="primary" disabled={sending} onClick={onSend}>{sending ? 'Sending…' : 'Send'}</button>
        <button disabled={sending} onClick={onCancel}>Cancel</button>
      </div>
    </div>
  )
}

export function Mail() {
  const { tools } = useAppState()
  const canDraft = tools.has('mail_ai__draft_reply') && tools.has('mail_ai__send_draft')

  const status = usePoll(() => call<Status>('mail_ai__status'), 30000)
  const threads = usePoll(() => call<{ threads: Thread[] }>('mail_ai__list_threads', { limit: 40 }), 30000)
  const [query, setQuery] = useState('')
  const [found, setFound] = useState<Found[] | null>(null)
  const [open, setOpen] = useState<ThreadDetail | null>(null)
  const [reply, setReply] = useState('')
  const [draft, setDraft] = useState<Draft | null>(null)
  const [confirming, setConfirming] = useState<string | null | undefined>(undefined)
  const [busy, setBusy] = useState('')
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  const act = async (label: string, fn: () => Promise<void>) => {
    setBusy(label)
    setError('')
    try { await fn() } catch (e) { setError(e instanceof Error ? e.message : String(e)) } finally { setBusy('') }
  }

  const sync = () => act('sync', async () => {
    const r = await call<{ added: number; mode: string }>('mail_ai__sync')
    setNotice(`${r.added} new message${r.added === 1 ? '' : 's'}`)
    await Promise.all([status.reload(), threads.reload()])
  })

  const search = () => act('search', async () => {
    if (!query.trim()) { setFound(null); return }
    setFound((await call<{ messages: Found[] }>('mail_ai__search', { text: query.trim() })).messages)
  })

  const openThread = (id: string) => act('open', async () => {
    setOpen(await call<ThreadDetail>('mail_ai__read_thread', { thread_id: id }))
    setReply(''); setDraft(null); setConfirming(undefined); setNotice('')
  })

  const makeDraft = () => act('draft', async () => {
    if (!open) return
    setDraft(await call<Draft>('mail_ai__draft_reply', { thread_id: open.thread_id, body: reply.trim() }))
    setNotice('Draft saved in Gmail. Nothing has been sent.')
  })

  // First press: the server returns the rendered email instead of sending.
  const askSend = () => act('send', async () => {
    if (!draft) return
    const r = await runAction('mail_ai__send_draft', { draft_id: draft.draft_id, confirmation: draft.confirmation })
    setConfirming(r.needs_confirmation ? (r.preview ?? null) : null)
  })

  // Second, confirmed press: the gate re-checks the draft still says what was shown.
  const send = () => act('send', async () => {
    if (!draft) return
    const r = await runAction<{ error?: string }>('mail_ai__send_draft',
      { draft_id: draft.draft_id, confirmation: draft.confirmation }, true)
    if (r.output && typeof r.output === 'object' && 'error' in r.output && r.output.error) throw new Error(String(r.output.error))
    setConfirming(undefined); setDraft(null); setReply('')
    setNotice('Sent.')
  })

  const discard = () => act('discard', async () => {
    if (!draft) return
    await call('mail_ai__discard_draft', { draft_id: draft.draft_id })
    setDraft(null); setNotice('Draft discarded.')
  })

  const list: { id: string; title: string; sub: string; when: string }[] = found
    ? found.map((m) => ({ id: m.thread_id, title: m.subject || '(no subject)', sub: who(m.from_addr), when: m.at }))
    : (threads.data?.threads ?? []).map((t) => ({
        id: t.thread_id, title: t.subject || '(no subject)',
        sub: `${who(t.started_by)}${t.messages > 1 ? ` · ${t.messages}` : ''}`, when: t.last,
      }))

  return (
    <div className="panel">
      <div className="card">
        <div className="mail-bar">
          <h2>Mail</h2>
          <span className="muted">
            {status.data ? `${status.data.messages} messages · newest ${when(status.data.newest)}` : 'loading…'}
          </span>
          <button disabled={busy === 'sync'} onClick={() => void sync()}>{busy === 'sync' ? 'Syncing…' : 'Sync now'}</button>
        </div>
        <form className="row" onSubmit={(e) => { e.preventDefault(); void search() }}>
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search the synced mailbox" aria-label="Search mail" />
          <button type="submit">Search</button>
          {found && <button type="button" onClick={() => { setFound(null); setQuery('') }}>Clear</button>}
        </form>
        {notice && <p className="result">{notice}</p>}
        {(error || status.error) && <p className="error">{error || status.error}</p>}
      </div>

      <div className="mail">
        <ul className="card mail-list">
          {list.length === 0 && <li className="muted">{found ? 'Nothing matches.' : 'No mail synced yet.'}</li>}
          {list.map((item, i) => (
            <li key={`${item.id}-${i}`}>
              <button className={`mail-item ${open?.thread_id === item.id ? 'on' : ''}`} onClick={() => void openThread(item.id)}>
                <span className="mail-title">{item.title}</span>
                <span className="muted">{item.sub}</span>
                <span className="muted mail-when">{when(item.when)}</span>
              </button>
            </li>
          ))}
        </ul>

        <div className="card mail-thread">
          {!open && <p className="muted">Pick a conversation.</p>}
          {open && (
            <>
              <h3>{open.subject || '(no subject)'}</h3>
              {open.messages.map((m) => (
                <article key={m.id} className="mail-message">
                  <header><strong>{who(m.from)}</strong> <span className="muted">{when(m.at)}</span></header>
                  {/* Email written by someone else: text only, never markup. */}
                  <pre>{m.body || '(no text)'}</pre>
                </article>
              ))}

              {canDraft ? (
                <div className="stack reply">
                  {!draft && (
                    <>
                      <textarea value={reply} onChange={(e) => setReply(e.target.value)} rows={4} placeholder="Write a reply" aria-label="Reply" />
                      <div className="row">
                        <button className="primary" disabled={!reply.trim() || busy === 'draft'} onClick={() => void makeDraft()}>
                          {busy === 'draft' ? 'Saving…' : 'Save as draft'}
                        </button>
                      </div>
                    </>
                  )}
                  {draft && confirming === undefined && (
                    <div className="row">
                      <span className="muted">Draft to {who(draft.to)} saved.</span>
                      <button className="primary" disabled={busy === 'send'} onClick={() => void askSend()}>Send…</button>
                      <button disabled={busy === 'discard'} onClick={() => void discard()}>Discard</button>
                    </div>
                  )}
                  {draft && confirming !== undefined && (
                    <SendConfirm preview={confirming} sending={busy === 'send'}
                      onSend={() => void send()} onCancel={() => setConfirming(undefined)} />
                  )}
                </div>
              ) : (
                <p className="hint">Replying is off. Drafting and sending appear here once they are switched on for mail-ai.</p>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

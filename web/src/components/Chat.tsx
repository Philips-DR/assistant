import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { sendChat, toolLabel, type AssistantEvent } from '../api'
import { useAppState } from '../state'
import { ApprovalCard } from './ApprovalCard'

function ToolLine({ event }: { event: AssistantEvent }) {
  const fromButton = event.origin === 'button'
  const mark = event.outcome === 'ok' ? '✓' : event.outcome === 'declined' ? '–' : '✕'
  return (
    <div className={`tool-line ${event.outcome ?? ''}`}>
      <span className="tool-mark" aria-hidden>{mark}</span>
      {fromButton ? 'You pressed ' : ''}
      <span className="tool-name">{toolLabel(event.tool)}</span>
      {event.outcome === 'declined' && <span className="muted"> — declined</span>}
      {event.outcome === 'failed' && <span className="muted"> — failed</span>}
    </div>
  )
}

export function Chat() {
  const { events, pending, busy, connected } = useAppState()
  const [draft, setDraft] = useState('')
  const [error, setError] = useState('')
  const bottom = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [events.length, pending.length])

  const submit = async (e?: FormEvent) => {
    e?.preventDefault()
    const message = draft.trim()
    if (!message || busy) return
    setError('')
    try {
      await sendChat(message)
      setDraft('')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void submit()
    }
  }

  return (
    <section className="chat">
      <div className="transcript" aria-live="polite">
        {events.length === 0 && (
          <div className="empty">
            <p>Ask for anything the tools can do.</p>
            <p className="muted">"Record this meeting." · "What's in my inbox?" · "Write up yesterday's meeting as a Doc."</p>
          </div>
        )}

        {events.map((event) => {
          switch (event.type) {
            case 'user_message':
              return <div key={event.seq} className="bubble user">{event.text}</div>
            case 'assistant_text':
              return (
                <div key={event.seq} className="bubble assistant">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{event.text ?? ''}</ReactMarkdown>
                </div>
              )
            case 'tool_finished':
              // Read-only button presses are status polls; they would flood the transcript.
              if (event.origin === 'button' && event.read_only) return null
              return <ToolLine key={event.seq} event={event} />
            case 'approval_needed': {
              const live = pending.find((p) => p.id === event.id)
              return live ? <ApprovalCard key={event.seq} approval={live} /> : null
            }
            case 'turn_error':
              return <div key={event.seq} className="error">Something went wrong: {event.error}</div>
            default:
              return null
          }
        })}

        {busy && pending.length === 0 && <div className="thinking">Working…</div>}
        {pending
          .filter((p) => !events.some((e) => e.type === 'approval_needed' && e.id === p.id))
          .map((p) => <ApprovalCard key={p.id} approval={p} />)}
        <div ref={bottom} />
      </div>

      <form className="composer" onSubmit={(e) => void submit(e)}>
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKey}
          placeholder={busy ? 'Working on the last message…' : 'Message the assistant'}
          disabled={!connected}
          rows={2}
          aria-label="Message"
        />
        <button className="primary" type="submit" disabled={busy || !draft.trim() || !connected}>
          Send
        </button>
      </form>
      {error && <p className="error composer-error">{error}</p>}
    </section>
  )
}


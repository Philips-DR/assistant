// What has happened, across both modes. In buttons mode this is how you see that the model
// did something in chat -- and in chat, button presses show inline the same way.

import { toolLabel } from '../api'
import { useAppState } from '../state'

export function Activity() {
  const { events } = useAppState()
  const shown = events
    .filter((e) => (e.type === 'tool_finished' && !e.read_only) || e.type === 'user_message' || e.type === 'turn_error' || e.type === 'notice')
    .slice(-12)
    .reverse()

  return (
    <aside className="card activity">
      <h2>Activity</h2>
      {shown.length === 0 && (
        <p className="muted">Anything you or the assistant change shows up here, whichever mode it happened in.</p>
      )}
      <ul>
        {shown.map((e) => (
          <li key={e.seq}>
            <span className="muted">{new Date(e.at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
            {e.type === 'user_message' && <> you asked: <em>{(e.text ?? '').slice(0, 60)}</em></>}
            {e.type === 'turn_error' && <span className="warn"> a chat turn failed</span>}
            {e.type === 'notice' && <span className={e.level === 'success' ? '' : 'warn'}> {e.title}</span>}
            {e.type === 'tool_finished' && (
              <>
                {' '}
                {e.origin === 'button' ? 'you' : 'assistant'} ran <strong>{toolLabel(e.tool)}</strong>
                {e.outcome !== 'ok' && <span className="muted"> — {e.outcome}</span>}
              </>
            )}
          </li>
        ))}
      </ul>
    </aside>
  )
}

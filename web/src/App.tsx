import { useEffect, useState } from 'react'
import { useAppState } from './state'
import { ApprovalCard } from './components/ApprovalCard'
import { Activity } from './components/Activity'
import { Chat } from './components/Chat'
import { Mail } from './components/Mail'
import { Meetings } from './components/Meetings'

type Mode = 'chat' | 'buttons'
type Section = 'meetings' | 'mail'

function savedMode(): Mode {
  // The URL wins, so a view can be bookmarked or linked; then the last mode used.
  if (location.hash.startsWith('#buttons')) return 'buttons'
  if (location.hash === '#chat') return 'chat'
  try {
    return localStorage.getItem('assistant-mode') === 'buttons' ? 'buttons' : 'chat'
  } catch {
    return 'chat'
  }
}

export function App() {
  const { pending, busy, connected, model } = useAppState()
  const [mode, setMode] = useState<Mode>(savedMode)
  const [section, setSection] = useState<Section>(location.hash === '#buttons/mail' ? 'mail' : 'meetings')

  useEffect(() => {
    history.replaceState(null, '', mode === 'buttons' && section === 'mail' ? '#buttons/mail' : `#${mode}`)
    try {
      localStorage.setItem('assistant-mode', mode)
    } catch {
      // private window or blocked storage: the mode just won't be remembered
    }
  }, [mode, section])

  return (
    <div className="app">
      <header className="top">
        <h1>Assistant</h1>

        <div className="modes" role="tablist" aria-label="Mode">
          <button role="tab" aria-selected={mode === 'chat'} className={mode === 'chat' ? 'on' : ''} onClick={() => setMode('chat')}>
            Chat
            {mode !== 'chat' && pending.length > 0 && <span className="dot-count">{pending.length}</span>}
          </button>
          <button role="tab" aria-selected={mode === 'buttons'} className={mode === 'buttons' ? 'on' : ''} onClick={() => setMode('buttons')}>
            Buttons
          </button>
        </div>

        <div className="status">
          <span className={`conn ${connected ? 'up' : 'down'}`} aria-hidden />
          <span className="muted">{connected ? model || 'connected' : 'reconnecting…'}</span>
        </div>
      </header>

      <main>
        {mode === 'chat' ? (
          <Chat />
        ) : (
          <div className="buttons-mode">
            {pending.length > 0 && (
              <div className="banner">
                <p>The assistant is waiting for your answer:</p>
                {pending.map((p) => (
                  <ApprovalCard key={p.id} approval={p} />
                ))}
              </div>
            )}
            {busy && pending.length === 0 && <p className="muted working-note">The assistant is working on a chat message.</p>}
            <nav className="sections" aria-label="Section">
              <button className={section === 'meetings' ? 'on' : ''} onClick={() => setSection('meetings')}>Meetings</button>
              <button className={section === 'mail' ? 'on' : ''} onClick={() => setSection('mail')}>Mail</button>
            </nav>
            <div className="buttons-grid">
              {section === 'meetings' ? <Meetings /> : <Mail />}
              <Activity />
            </div>
          </div>
        )}
      </main>
    </div>
  )
}

import { useEffect, useState } from 'react'
import { useAppState } from './state'
import { ApprovalCard } from './components/ApprovalCard'
import { Activity } from './components/Activity'
import { Notices } from './components/Notices'
import { Chat } from './components/Chat'
import { History } from './components/History'
import { Mail } from './components/Mail'
import { Memory } from './components/Memory'
import { Meetings } from './components/Meetings'

type Mode = 'chat' | 'buttons'
type Section = 'meetings' | 'mail' | 'memory' | 'history'
const SECTIONS: Section[] = ['meetings', 'mail', 'memory', 'history']

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
  const [section, setSection] = useState<Section>(() => {
    const named = location.hash.replace('#buttons/', '') as Section
    return SECTIONS.includes(named) ? named : 'meetings'
  })

  // The hash is read on load AND whenever it changes. Reading it only once meant the back
  // button, a bookmark, or an edited URL changed the address but left the old section showing
  // -- a hash change does not reload the page. (replaceState below does not fire hashchange,
  // so this cannot loop.)
  useEffect(() => {
    const follow = () => {
      if (location.hash === '#chat') {
        setMode('chat')
      } else if (location.hash.startsWith('#buttons')) {
        setMode('buttons')
        const named = location.hash.replace('#buttons/', '') as Section
        setSection(SECTIONS.includes(named) ? named : 'meetings')
      }
    }
    window.addEventListener('hashchange', follow)
    return () => window.removeEventListener('hashchange', follow)
  }, [])

  useEffect(() => {
    history.replaceState(null, '', mode === 'buttons' && section !== 'meetings' ? `#buttons/${section}` : `#${mode}`)
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
              {SECTIONS.map((s) => (
                <button key={s} className={section === s ? 'on' : ''} onClick={() => setSection(s)}>
                  {s[0]?.toUpperCase() + s.slice(1)}
                </button>
              ))}
            </nav>
            <div className="buttons-grid">
              {section === 'meetings' && <Meetings />}
              {section === 'mail' && <Mail />}
              {section === 'memory' && <Memory />}
              {section === 'history' && <History />}
              <Activity />
            </div>
          </div>
        )}
      </main>
      <Notices />
    </div>
  )
}

// Is everything working? Shows, never acts: fixing a login means a terminal and a browser,
// and the page says which command. Each thing is checked at the level that owns it -- the
// model login and the network here, a tool's health from how its own calls have gone.

import { useCallback, useEffect, useState } from 'react'
import { getStatus, toolLabel, type Level, type Status } from '../api'

const dot = (level: Level | undefined) => <span className={`dot ${level ?? 'unknown'}`} aria-label={level ?? 'not checked'} />

function ms(value: number | null, error: string) {
  return value != null ? `${value} ms` : <span className="muted">{error || 'no'}</span>
}

export function Settings() {
  const [status, setStatus] = useState<Status | null>(null)
  const [checking, setChecking] = useState(false)
  const [error, setError] = useState('')

  const check = useCallback(async (live: boolean) => {
    setChecking(live)
    setError('')
    try {
      setStatus(await getStatus(live))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setChecking(false)
    }
  }, [])

  // Instant view first, then the live checks, which each cost a round trip.
  useEffect(() => {
    void check(false).then(() => check(true))
  }, [check])

  const model = status?.model
  return (
    <div className="panel">
      <div className="card">
        <div className="row spread">
          <h2>Connections</h2>
          <button disabled={checking} onClick={() => void check(true)}>{checking ? 'Checking…' : 'Check now'}</button>
        </div>

        <h3>Model</h3>
        {model && (
          <div className="status-row">
            {dot(model.level)}
            <div>
              <strong>{model.model}</strong>
              <span className="muted"> · {model.provider}{model.profile ? ` · profile ${model.profile}` : ''}{model.region ? ` · ${model.region}` : ''}</span>
              {model.level === 'ok' && model.account && <p className="muted">Signed in to account {model.account}{model.role ? ` as ${model.role}` : ''}.</p>}
              {model.level === 'error' && (
                <>
                  <p className="warn">Can’t reach the model: {model.detail}</p>
                  {model.hint && <p>{model.hint}</p>}
                </>
              )}
              {!model.level && <p className="muted">{checking ? 'Checking the login…' : 'Not checked yet.'}</p>}
            </div>
          </div>
        )}

        <h3>Network</h3>
        {!status?.network && <p className="muted">{checking ? 'Testing connections…' : 'Not checked yet.'}</p>}
        {status?.network && (
          <div className="table-wrap">
            <table className="history">
              <thead><tr><th></th><th>Service</th><th className="num">IPv4</th><th className="num">IPv6</th><th>Verdict</th></tr></thead>
              <tbody>
                {status.network.map((n) => (
                  <tr key={n.host}>
                    <td>{dot(n.level)}</td>
                    <td>{n.name}<div className="muted small">{n.host}</div></td>
                    <td className="num">{ms(n.ipv4_ms, n.ipv4_error)}</td>
                    <td className="num">{ms(n.ipv6_ms, n.ipv6_error)}</td>
                    <td>{n.verdict}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <h3>Tools</h3>
        {status?.tools.map((t) => (
          <div key={t.name} className="status-row">
            {dot(t.level)}
            <div>
              <strong>{t.name}</strong>
              <span className="muted"> · {t.tools} tools{t.name === 'mail-ai' ? (status.mail_compose ? ' · drafting on' : ' · drafting off') : ''}</span>
              {t.last_call ? (
                <p className={t.level === 'ok' ? 'muted' : 'warn'}>
                  Last call: {toolLabel(t.last_call.tool)}, {t.last_call.outcome}, {new Date(t.last_call.at).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })}
                  {t.last_call.error && <> — {t.last_call.error}</>}
                </p>
              ) : (
                <p className="muted">Not used yet.</p>
              )}
            </div>
          </div>
        ))}
        {error && <p className="error">{error}</p>}
        <p className="hint">
          Google logins belong to each tool: sign in again with <code>npm run auth</code> in docu-ai, or <code>./mail auth</code> in mail-ai.
        </p>
      </div>
    </div>
  )
}

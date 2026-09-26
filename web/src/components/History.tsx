// Every tool call, from the audit log -- newest first, across restarts. The Activity panel is
// this run's live view; this is the durable record.

import { getHistory, toolLabel } from '../api'
import { usePoll } from '../usePoll'

export function History() {
  const rows = usePoll(() => getHistory(300), 15000)
  const data = rows.data ?? []

  return (
    <div className="panel">
      <div className="card">
        <h2>History</h2>
        {data.length === 0 && <p className="muted">Nothing has run yet.</p>}
        {data.length > 0 && (
          <div className="table-wrap">
            <table className="history">
              <thead>
                <tr><th>When</th><th>What</th><th>By</th><th>Result</th><th className="num">Took</th></tr>
              </thead>
              <tbody>
                {data.map((r, i) => (
                  <tr key={`${r.at}-${i}`}>
                    <td className="muted">{new Date(r.at).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })}</td>
                    <td className="tool-name">{toolLabel(r.tool)}</td>
                    <td className="muted">{r.origin === 'button' ? 'you' : 'assistant'}</td>
                    <td className={`outcome ${r.outcome}`} title={r.error ?? ''}>{r.outcome}</td>
                    <td className="num muted">{r.duration_ms != null ? `${(r.duration_ms / 1000).toFixed(1)}s` : ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {rows.error && <p className="error">{rows.error}</p>}
      </div>
    </div>
  )
}

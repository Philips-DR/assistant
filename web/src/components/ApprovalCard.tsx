// The gate, in a browser. Shown inline in chat and as a banner in buttons mode: an approval
// is waiting on you whichever view you happen to be in.

import { useState } from 'react'
import { answerApproval, toolLabel, type Approval } from '../api'

export function ApprovalCard({ approval }: { approval: Approval }) {
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')

  const answer = async (approve: boolean) => {
    setSending(true)
    setError('')
    try {
      await answerApproval(approval.id, approve)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setSending(false)
    }
  }

  const hasArguments = Object.keys(approval.arguments).length > 0

  return (
    <div className="approval" role="alertdialog" aria-label={`Approve ${toolLabel(approval.tool)}?`}>
      <div className="approval-head">
        <span className="approval-kicker">Needs your approval</span>
        <span className="approval-tool">{toolLabel(approval.tool)}</span>
      </div>

      {approval.preview ? (
        // Rendered as text, never HTML: this is an email body or a transcript, written by
        // someone else, and it must not be able to become markup on this page.
        <pre className="approval-preview">{approval.preview}</pre>
      ) : approval.preview_expected ? (
        <p className="approval-warning">
          This action offers a preview of what it would do, and the preview could not be produced.
          Approving means approving it unseen.
        </p>
      ) : null}

      {hasArguments && (
        <details className="approval-args" open={!approval.preview}>
          <summary>Details</summary>
          <pre>{JSON.stringify(approval.arguments, null, 2)}</pre>
        </details>
      )}

      {error && <p className="error">{error}</p>}

      <div className="approval-actions">
        <button className="primary" disabled={sending} onClick={() => void answer(true)}>
          Approve
        </button>
        <button disabled={sending} onClick={() => void answer(false)}>
          Decline
        </button>
      </div>
    </div>
  )
}

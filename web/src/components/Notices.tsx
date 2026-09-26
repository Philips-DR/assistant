// Something finished while you were elsewhere. Toasts in the page, and a system notification
// when the tab is hidden -- a two-hour transcription is exactly when nobody is watching.

import { useEffect, useRef, useState } from 'react'
import { useAppState } from '../state'

const SHOW_FOR_MS = 20_000

export function Notices() {
  const { events } = useAppState()
  const [dismissed, setDismissed] = useState<Set<number>>(new Set())
  // Notices already in the first snapshot happened before this page opened: list them in
  // Activity, but don't pop them up again on every reload.
  const firstSeen = useRef<number | null>(null)
  const announced = useRef<Set<number>>(new Set())
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 5000)
    return () => clearInterval(timer)
  }, [])

  if (firstSeen.current === null && events.length > 0) {
    firstSeen.current = Math.max(...events.map((e) => e.seq))
  }
  const baseline = firstSeen.current ?? 0
  const fresh = events.filter((e) => e.type === 'notice' && e.seq > baseline)

  useEffect(() => {
    for (const e of fresh) {
      if (announced.current.has(e.seq)) continue
      announced.current.add(e.seq)
      if (document.hidden && 'Notification' in window && Notification.permission === 'granted') {
        new Notification(e.title ?? 'Assistant', { body: e.body })
      }
    }
  }, [fresh])

  const visible = fresh.filter((e) => !dismissed.has(e.seq) && now - e.at * 1000 < SHOW_FOR_MS)
  const canAsk = 'Notification' in window && Notification.permission === 'default'

  return (
    <div className="notices" aria-live="polite">
      {visible.map((e) => (
        <div key={e.seq} className={`notice ${e.level ?? 'success'}`}>
          <div>
            <strong>{e.title}</strong>
            <p>{e.body}</p>
          </div>
          <button className="notice-close" aria-label="Dismiss" onClick={() => setDismissed(new Set([...dismissed, e.seq]))}>
            ×
          </button>
        </div>
      ))}
      {canAsk && visible.length > 0 && (
        <button className="notice-ask" onClick={() => void Notification.requestPermission()}>
          Also tell me when this tab is in the background
        </button>
      )}
    </div>
  )
}

import { useCallback, useEffect, useRef, useState } from 'react'

/** Call `load` now and every `interval` ms. `interval` may change as state does -- fast while
 * something is recording or transcribing, slow when idle. */
export function usePoll<T>(load: () => Promise<T>, interval: number) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  const loader = useRef(load)
  loader.current = load

  const reload = useCallback(async () => {
    try {
      setData(await loader.current())
      setError('')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  useEffect(() => {
    void reload()
    const timer = window.setInterval(() => void reload(), interval)
    return () => window.clearInterval(timer)
  }, [interval, reload])

  return { data, error, reload }
}

export function clock(seconds: number | null | undefined): string {
  const s = Math.max(0, Math.floor(seconds ?? 0))
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`
}

export const fileName = (path: string | null | undefined) => (path ?? '').split('/').pop() ?? ''

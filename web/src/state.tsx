// One state for both modes. Chat and buttons are two views of it, which is what lets a
// recording stopped with a button be the one the model writes up in chat.

import { createContext, useCallback, useContext, useEffect, useReducer, type ReactNode } from 'react'
import { getState, getTools, openEvents, type Approval, type AssistantEvent } from './api'

interface State {
  events: AssistantEvent[]
  pending: Approval[]
  busy: boolean
  connected: boolean
  model: string
  tools: Set<string>
  /** Highest event seq in the first snapshot, or null before it arrives. Events at or below
   * it happened before this page opened. */
  openedAt: number | null
}

type Action =
  | { type: 'snapshot'; events: AssistantEvent[]; pending: Approval[]; busy: boolean; model: string }
  | { type: 'event'; event: AssistantEvent }
  | { type: 'connected'; value: boolean }
  | { type: 'tools'; names: string[] }

const initial: State = { events: [], pending: [], busy: false, connected: false, model: '', tools: new Set(), openedAt: null }

function reduce(state: State, action: Action): State {
  switch (action.type) {
    case 'snapshot':
      return {
        ...state,
        events: action.events,
        pending: action.pending,
        busy: action.busy,
        model: action.model,
        // Only the first snapshot sets it; a reconnect's snapshot must not swallow notices
        // that arrived while this page was open.
        openedAt: state.openedAt ?? Math.max(0, ...action.events.map((e) => e.seq)),
      }
    case 'connected':
      return { ...state, connected: action.value }
    case 'tools':
      return { ...state, tools: new Set(action.names) }
    case 'event': {
      const event = action.event
      // A reconnect replays from a fresh snapshot; drop anything already held.
      if (state.events.some((e) => e.seq === event.seq)) return state
      const events = [...state.events, event]
      switch (event.type) {
        case 'user_message':
          return { ...state, events, busy: true }
        case 'turn_done':
        case 'turn_error':
          return { ...state, events, busy: false }
        case 'approval_needed':
          return {
            ...state,
            events,
            pending: [
              ...state.pending.filter((p) => p.id !== event.id),
              {
                id: event.id ?? '',
                tool: event.tool ?? '',
                server: event.server ?? '',
                name: event.name ?? '',
                arguments: event.arguments ?? {},
                preview: event.preview ?? null,
                preview_expected: event.preview_expected ?? false,
              },
            ],
          }
        case 'approval_resolved':
          return { ...state, events, pending: state.pending.filter((p) => p.id !== event.id) }
        default:
          return { ...state, events }
      }
    }
  }
}

interface Context extends State {
  refresh: () => Promise<void>
}

const AppState = createContext<Context | null>(null)

export function StateProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reduce, initial)

  const refresh = useCallback(async () => {
    const [snapshot, tools] = await Promise.all([getState(), getTools()])
    // Views adapt to what the server actually offers -- mail drafting, for instance, only
    // exists when it has been switched on for mail-ai.
    dispatch({ type: 'tools', names: tools.map((t) => t.qualified_name) })
    dispatch({
      type: 'snapshot',
      events: snapshot.history,
      pending: snapshot.pending,
      busy: snapshot.busy,
      model: snapshot.model,
    })
  }, [])

  useEffect(() => {
    let source: EventSource | null = null
    let cancelled = false

    const connect = () => {
      source = openEvents()
      source.onopen = () => {
        dispatch({ type: 'connected', value: true })
        // Anything that happened while disconnected arrives in the snapshot.
        void refresh()
      }
      source.onmessage = (message: MessageEvent<string>) => {
        dispatch({ type: 'event', event: JSON.parse(message.data) as AssistantEvent })
      }
      source.onerror = () => {
        dispatch({ type: 'connected', value: false })
        // EventSource retries on its own; nothing else to do.
      }
    }

    void refresh().finally(() => {
      if (!cancelled) connect()
    })
    return () => {
      cancelled = true
      source?.close()
    }
  }, [refresh])

  return <AppState.Provider value={{ ...state, refresh }}>{children}</AppState.Provider>
}

export function useAppState(): Context {
  const context = useContext(AppState)
  if (!context) throw new Error('useAppState outside StateProvider')
  return context
}

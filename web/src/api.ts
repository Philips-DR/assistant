// The only module that talks to the server.

const token =
  document.querySelector<HTMLMetaElement>('meta[name="assistant-token"]')?.content ??
  import.meta.env.VITE_ASSISTANT_TOKEN ??
  ''

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message)
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      'content-type': 'application/json',
      // Every API call carries the per-launch token. A page in another tab can make the
      // browser send requests here, but cannot read this page to learn the token.
      'x-assistant-token': token,
      ...init.headers,
    },
  })
  if (response.status === 401) {
    // The server restarted and issued a new token; this tab still holds the old one and
    // every call will now fail. Say so, rather than leaving the page quietly frozen.
    window.dispatchEvent(new Event('assistant-stale'))
  }
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = (await response.json()) as { detail?: string; error?: string }
      detail = body.detail ?? body.error ?? detail
    } catch {
      // not JSON; keep the status text
    }
    throw new ApiError(response.status, detail)
  }
  return (await response.json()) as T
}

export type EventType =
  | 'user_message'
  | 'assistant_text'
  | 'tool_started'
  | 'tool_finished'
  | 'approval_needed'
  | 'approval_resolved'
  | 'turn_done'
  | 'turn_error'
  | 'notice'

export interface AssistantEvent {
  seq: number
  at: number
  type: EventType
  text?: string
  tool?: string
  outcome?: string
  origin?: 'chat' | 'button'
  arguments?: Record<string, unknown>
  result?: string
  error?: string
  id?: string
  approved?: boolean
  server?: string
  name?: string
  preview?: string | null
  preview_expected?: boolean
  read_only?: boolean
  level?: 'success' | 'warning' | 'error'
  title?: string
  body?: string
}

export interface Approval {
  id: string
  tool: string
  server: string
  name: string
  arguments: Record<string, unknown>
  preview: string | null
  preview_expected: boolean
}

export interface ServerState {
  busy: boolean
  pending: Approval[]
  history: AssistantEvent[]
  notes: string[]
  model: string
}

export interface ActionResult<T = unknown> {
  outcome?: string
  output?: T
  needs_confirmation?: boolean
  preview?: string | null
}

export interface ToolInfo {
  qualified_name: string
  server: string
  name: string
  read_only: boolean
  has_preview: boolean
}

export const getState = () => request<ServerState>('/api/state')

export const getTools = () => request<ToolInfo[]>('/api/tools')

export interface AuditRow {
  at: string
  tool: string
  outcome: string
  origin?: string
  duration_ms?: number
  error?: string | null
}

export const getHistory = (limit = 200) => request<AuditRow[]>(`/api/history?limit=${limit}`)

export type Level = 'ok' | 'warning' | 'error'

export interface Status {
  tools: {
    name: string
    tools: number
    level: Level
    last_call: { at: string; tool: string; outcome: string; error: string } | null
  }[]
  model: {
    provider: string
    model: string
    profile: string | null
    region: string | null
    level?: Level
    account?: string
    role?: string
    detail?: string
    hint?: string
  }
  mail_compose: boolean
  network?: {
    name: string
    host: string
    ipv4_ms: number | null
    ipv4_error: string
    ipv6_ms: number | null
    ipv6_error: string
    verdict: string
    level: Level
  }[]
}

export const getStatus = (live = false) => request<Status>(`/api/status${live ? '?live=true' : ''}`)

export const sendChat = (message: string) =>
  request<{ accepted: boolean }>('/api/chat', { method: 'POST', body: JSON.stringify({ message }) })

export const answerApproval = (id: string, approve: boolean) =>
  request<{ approved: boolean }>(`/api/approvals/${encodeURIComponent(id)}`, {
    method: 'POST',
    body: JSON.stringify({ approve }),
  })

/** A button press: a tool you chose, called without a model. */
export const runAction = <T = unknown>(
  tool: string,
  args: Record<string, unknown> = {},
  confirmed = false,
) =>
  request<ActionResult<T>>('/api/actions', {
    method: 'POST',
    body: JSON.stringify({ tool, arguments: args, confirmed }),
  })

/** EventSource cannot send headers, so this one request carries the token in its URL. */
export const openEvents = () => new EventSource(`/api/events?token=${encodeURIComponent(token)}`)

/** "meet_ai__start_recording" → "meet-ai · start recording" */
export function toolLabel(qualified: string | undefined): string {
  if (!qualified) return ''
  const [server, name] = qualified.split('__')
  return `${(server ?? '').replace(/_/g, '-')} · ${(name ?? '').replace(/_/g, ' ')}`
}

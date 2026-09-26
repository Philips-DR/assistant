# assistant — engineering rules

The smallest component in the suite. It classifies, calls, gates, and logs. **No domain
logic, ever** — if a change here needs to know what a timeline or a heading index is, it
belongs in a tool instead.

## Boundaries

- **Never import from a tool's repo.** The provider seam in `config.py` is a deliberate
  copy of meet-ai's, not an import. Sharing code across a repository boundary is how a suite
  of independent tools quietly becomes a monolith again — which is the exact failure this
  whole architecture was a response to. A little duplication at a boundary is the cheaper
  mistake.
- **`tools.yaml` is the only file that knows every tool exists.** Adding a tool is an entry
  there; no module gets edited.
- **Credentials and paths are injected into tools, never discovered by them.** The `env` on
  a server entry is that mechanism.

## The gate

- Approval is decided from the tool's own `readOnlyHint`, never from a list here.
- **Absent annotations fail closed.** A tool that forgot to annotate itself must not get a
  free pass; `read_only=bool(annotations and annotations.read_only_hint)`.
- Anything that is not an explicit `y`/`yes` is a decline.
- **The model must not ask permission in prose.** The system prompt says so explicitly.
  Without that, you get two gates: the model asks, the user answers the model, and the turn
  ends before the gate ever fires. Found live at M0 — the first two runs of a two-tool chain
  both stalled this way.

## MCP SDK — two traps, both sprung

**mcp 2.x exposes snake_case attributes and keeps camelCase only as a wire alias.** The
Python objects have `input_schema` and `is_error`; `inputSchema` and `isError` are the
aliases. Reading an alias off the object does not raise — `getattr(result, "isError", False)`
returns the default — so **every tool failure was silently recorded as a success** until a
real `invalid_grant` made it visible. Check the field list before reaching for a name you
remember:

    .venv/bin/python -c "from mcp.types import CallToolResult; print(list(CallToolResult.model_fields))"

**An exception raised while starting servers hangs the process instead of surfacing.**
`ToolRegistry.__aenter__` builds an `AsyncExitStack` of child processes; a failure part-way
through leaves them attached to a half-built stack and the program deadlocks with no
traceback at all. The `except BaseException: await self._stack.__aexit__(*sys.exc_info());
raise` around that loop is what turns a silent hang into an error message. It cost an hour
to find once — an `AttributeError` from the rename above, presenting as a hang.

## Memory

- **It is the assistant's own state, and no tool may read it.** Tools take what they need as
  arguments. The moment a tool reaches into memory, it stops being usable alone and the suite
  has a shared mutable centre again.
- **Not pgvector, on purpose.** Everything fits in a prompt at this scale, and sending all of
  it is more accurate than any retrieval. `relevant()` is the seam; narrow it only when the
  prompt genuinely gets too big.
- **Memory failing degrades what the assistant knows, never whether it runs.** A missing or
  malformed store loads as empty.
- **Memory is background, not instruction.** It is framed that way in the prompt because a
  remembered line is data the user wrote once, not an order outranking what they say now.
- **Both memory tools are gated.** Writing about a person should be visible as it happens.

## Honest reporting

- **A tool reporting its own failure is a failure.** MCP returns that as `is_error` on an
  otherwise successful response, not as a raised exception. An audit log that records a
  failed build as `ok` is worse than no audit log.
- The audit log never raises. A broken log must not break the work.

## The web server

- **Chat and buttons are one state.** A button that changes something becomes a note handed
  to the model with the next message; a model's action streams to every view. Two apps that
  happen to share a backend would let "stop the recording" and "write it up" refer to
  different things.
- **Notes are held until a turn boundary.** Appended mid-turn, a note would sit between a
  tool call and its result, and the model's API rejects that shape.
- **Every call takes `session.execute`,** chat or button. Two paths would drift — the button
  one would quietly lose its audit row or its preview the first time only the other changed.
- **A failed turn rolls the conversation back** to before it, keeping the button notes. A
  turn that dies mid-way can leave a tool call without its result, which poisons every
  later turn.
- **Status polls from buttons are not noted.** Only calls that change something are; a poll
  every few seconds would bury the model's context.
- **Security:** 127.0.0.1 only, never 0.0.0.0; a per-launch token on every `/api` request;
  Host must be localhost. The token may appear in a URL only for `/api/events`, because
  EventSource cannot send headers.

## The interface (`web/`)

Vite + React + strict TypeScript, built to `web/dist` and served by the same process. One
state for both modes (`state.tsx`), fed by one event stream; the modes are views, never
separate stores. Assistant replies render as Markdown through react-markdown, which does not
render raw HTML — and approval previews are rendered as text, never markup, because they are
email bodies and transcripts someone else wrote.

Four things that only showed up by running it:

- **The event stream must send bytes the moment it opens.** EventSource fires `onopen` only
  when the first bytes arrive, and the server sent nothing until the first event or the
  15-second keepalive — so every page load showed "reconnecting" and disabled the message box
  for up to 15 s. An immediate `: connected` comment brought first byte to 6 ms.
- **uvicorn needs `timeout_graceful_shutdown`.** It waits for open connections to drain before
  stopping, and an event stream never drains — any open browser tab blocked shutdown forever,
  holding the three tool processes with it.
- **Memory is re-read every turn.** The server runs for days; a fact remembered mid-session
  must reach the next turn, not the next restart.
- **Headless Chrome cannot screenshot this page with `--virtual-time-budget` or `--timeout`.**
  The first waits for network idle, which an event stream never reaches; the second works by
  stopping all network activity, which kills the stream and makes the page report
  "reconnecting" — corrupting exactly what it is measuring. Drive a real browser session
  (Puppeteer against the installed Chrome) instead.

## Approval previews

- **A tool may declare, in `_meta`, the read-only tool that renders its effect.** The gate
  calls it and shows the result instead of the arguments. This exists because
  `send_draft(draft_id, confirmation)` cannot be approved from its arguments, and the
  assistant must not learn what an email is in order to fix that.
- **Verify the named tool is read-only before calling it.** Otherwise a tool could name a
  destructive "preview" and have it run before anyone approved anything.
- **Never fall back silently.** A declared preview that could not be produced is announced;
  otherwise it is indistinguishable from a tool that offered none, and someone approves a
  send believing they saw it.
- **Sanitise preview text.** It is untrusted content — an email body — printed directly
  above a yes/no prompt, where escape sequences could repaint the screen or fake the prompt.
  Strip C0/C1 controls except newline and tab, and cap the length so a huge body cannot
  scroll the call being approved off the screen.

## The gate, continued

- **A gate that cannot get an answer declines.** `input()` raises `EOFError` when stdin is
  exhausted — piped input that ran out, a non-interactive shell — and letting it propagate
  kills the turn mid-chain with writes already done. Found live: two approved writes landed,
  then a third call hit end-of-input and crashed the session. `KeyboardInterrupt` is a
  decline for the same reason.

## Testing

No model, no child process, no network. The gate carries the most tests: it is the only
thing between a model's intention and a write, and it must work without depending on a
model behaving well.

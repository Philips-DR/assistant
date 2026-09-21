# assistant

Talk to your tools. The assistant classifies a request, calls a tool, gates anything that
writes, and logs what happened.

It owns no domain logic. It does not know what a timeline is, what a span is, or that
Google Docs indexes are UTF-16 code units. Every hard thing lives inside a tool, behind an
MCP door, where it is tested and cannot drift.

```bash
./assistant-cli --list                      # what tools exist, and which of them write
./assistant-cli "write up the meeting"      # one-shot
./assistant-cli                             # chat loop
```

## How it reaches the tools

Every tool is a child process speaking MCP over stdio. None is a network service, none has
to be running beforehand, and each is equally usable from its own terminal with the
assistant absent. `tools.yaml` is the only file in the system that knows more than one of
them exists:

```yaml
servers:
  - name: meet-ai
    command: ${MEET_AI_HOME:-../meet-ai}/mcp
    cwd: ${MEET_AI_HOME:-../meet-ai}
```

Paths take `~`, `$VAR` and `${VAR:-fallback}`, and a **relative path resolves against
`tools.yaml` itself**, not the working directory — so the defaults assume the tools are
siblings of this repository and work on a fresh machine unedited. An unset variable with no
fallback is an error rather than a literal, because a child process launched with a
nonsense path fails nowhere near its cause. A bare command like `npm` is left for `PATH`
to find.

`env` on a server entry is where that tool's paths and credentials are injected. A tool
never discovers either for itself.

## The gate

Anything that writes is shown to you with its exact arguments before it runs:

```
  run this?
  meet_ai.generate_notes
  {
    "timeline": ".../slice.timeline.json"
  }
  [y/N]
```

The decision of what needs approval comes from each tool's own `readOnlyHint` annotation,
not from a list kept here — a list would need updating every time a tool gained an
operation, and would be wrong in between. **A tool that declares nothing is treated as
writing.** Failing closed is the only safe default.

Anything that is not an explicit `y`/`yes` is a decline, including `ok` and `sure`. A gate
that guesses at intent is not a gate.

The model is told not to ask permission in prose, because the gate already does that. Both
at once makes two gates and a conversation that stalls waiting for an answer it was never
going to act on.

## The audit log

One JSON line per tool call, appended to `audit.jsonl`: what ran, with what arguments, how
long it took, and whether it worked. With tools behind MCP each call is a discrete typed
event rather than a function call buried in a process, which is what makes "what did it get
wrong this week" answerable from the log alone.

```
meet_ai__generate_notes   ok       7194ms
docu_ai__build            failed   invalid_grant
```

A tool that reports its own failure is recorded as a failure — see CLAUDE.md for why that
sentence had to be earned.

## Where the model comes from

Bedrock by default, or the Anthropic API when `ANTHROPIC_API_KEY` is set; `--provider`
forces either. Credentials are read from the environment in exactly one place and passed
down.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install pytest        # tests only
```

Then point `tools.yaml` at your tools.

## Testing

```bash
.venv/bin/python -m pytest tests/ -q
```

No model, no child process, no network. The approval gate has the most tests, because it is
the only thing standing between a model's intention and a write, and it must not depend on
a model behaving well in order to work.

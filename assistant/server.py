"""The assistant as a long-running server: one process, the tools held open, a browser in front.

Chat and buttons are two views of ONE system, not two apps. Every button action that changes
something is noted and handed to the model with your next message, so "stop the recording"
pressed in buttons mode and "write it up" typed in chat mode refer to the same recording.
Every chat action streams to the browser as events, so a transcription the model started
shows up in the buttons view with a live status. One state, one event stream, one gate.

Security, because this process can send email as you:

  * it binds to 127.0.0.1 only;
  * every /api request must carry a random token issued at launch and injected into the
    page -- a site in another tab can make your browser POST to localhost, but it cannot
    read the page to learn the token;
  * requests whose Host is not localhost are refused, which closes DNS rebinding.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from assistant.approval import needs_approval, sanitise
from assistant.config import load_tool_servers, model_config_from_environment
from assistant.session import ApprovalRequest, allow_gate, execute, run_turn
from assistant.setup import prepare
from assistant.tools import RemoteTool, ToolRegistry

ROOT = Path(__file__).resolve().parent.parent
WEB_DIST = ROOT / "web" / "dist"
HISTORY_LIMIT = 1000
KEEPALIVE_SECONDS = 15
LOCAL_HOSTS = {"127.0.0.1", "localhost"}
NOTE_LIMIT = 400


def approval_view(request: ApprovalRequest) -> dict[str, Any]:
    return {
        "id": request.id,
        "tool": request.tool.qualified_name,
        "server": request.tool.server,
        "name": request.tool.name,
        "arguments": request.arguments,
        # Untrusted content (an email body, a transcript) on its way to a screen. The
        # browser renders it as text, never HTML; this also caps its length.
        "preview": sanitise(request.preview) if request.preview else None,
        "preview_expected": request.preview_expected,
    }


def parsed(output: str) -> Any:
    try:
        return json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return output


class Hub:
    """Everything the browser and the model share."""

    def __init__(self, registry: ToolRegistry, config: Any, context: str, audit_path: Path) -> None:
        self.registry = registry
        self.config = config
        self.context = context
        self.audit_path = audit_path
        self.messages: list[dict[str, Any]] = []
        self.notes: list[str] = []
        self.turn: asyncio.Task | None = None
        self.pending: dict[str, tuple[ApprovalRequest, asyncio.Future]] = {}
        self.subscribers: set[asyncio.Queue] = set()
        self.history: deque[dict[str, Any]] = deque(maxlen=HISTORY_LIMIT)
        self.seq = 0

    @property
    def busy(self) -> bool:
        return self.turn is not None and not self.turn.done()

    async def emit(self, event: dict[str, Any]) -> None:
        self.seq += 1
        stamped = {**event, "seq": self.seq, "at": time.time()}
        self.history.append(stamped)
        for queue in list(self.subscribers):
            queue.put_nowait(stamped)

    async def web_gate(self, request: ApprovalRequest) -> bool:
        """Suspend the turn until a person answers in the browser."""
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self.pending[request.id] = (request, future)
        await self.emit({"type": "approval_needed", **approval_view(request)})
        try:
            return await future
        finally:
            self.pending.pop(request.id, None)

    def compose(self, message: str) -> str:
        """The user's message, with anything they did through buttons since the last one.

        Notes are held until a turn boundary rather than appended as they happen: a note
        landing mid-turn would sit between a tool call and its result, and the model's API
        rejects a conversation with that shape.
        """
        if not self.notes:
            return message
        done = "\n".join(f"- {note}" for note in self.notes)
        self.notes.clear()
        return f"[Since your last message, you did this in the interface:\n{done}]\n\n{message}"

    async def run(self, message: str) -> None:
        checkpoint = len(self.messages)
        held = list(self.notes)
        await self.emit({"type": "user_message", "text": message})
        self.messages.append({"role": "user", "content": self.compose(message)})
        try:
            await run_turn(self.registry, self.config, self.messages, self.audit_path,
                           context=self.context, gate=self.web_gate, emit=self.emit)
        except Exception as error:
            # A failed turn can leave a tool call without its result, which would poison
            # every later turn. Roll the conversation back to before it, and keep the notes.
            del self.messages[checkpoint:]
            self.notes = held + self.notes
            await self.emit({"type": "turn_error", "error": str(error)[:500]})

    def note(self, tool: RemoteTool, arguments: dict[str, Any], outcome: str, output: str) -> None:
        compact = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
        self.notes.append(
            f"{tool.server}.{tool.name}({compact}) -> {outcome}: {output[:NOTE_LIMIT]}"
        )


class ChatRequest(BaseModel):
    message: str


class ApprovalAnswer(BaseModel):
    approve: bool


class ActionRequest(BaseModel):
    tool: str
    arguments: dict[str, Any] = {}
    confirmed: bool = False


def create_app(
    tools_path: Path,
    memory_path: Path,
    audit_path: Path,
    provider: str | None = None,
    model: str | None = None,
    token: str | None = None,
    registry_factory: Callable[[list[Any]], ToolRegistry] | None = None,
) -> FastAPI:
    token = token or secrets.token_urlsafe(24)
    holder: dict[str, Hub] = {}

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        config = model_config_from_environment(provider, model)
        _store, local_tools, context = prepare(memory_path)
        registry = (registry_factory(local_tools) if registry_factory
                    else ToolRegistry(load_tool_servers(tools_path), local=local_tools))
        # Held open for the life of the server: the tools stay running instead of being
        # relaunched for every request.
        await registry.__aenter__()
        holder["hub"] = Hub(registry, config, context, audit_path)
        app.state.hub = holder["hub"]
        try:
            yield
        finally:
            await registry.__aexit__(None, None, None)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.token = token

    def hub() -> Hub:
        return holder["hub"]

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
        if host not in LOCAL_HOSTS:
            return JSONResponse({"error": "forbidden host"}, status_code=403)
        if request.url.path.startswith("/api/"):
            supplied = request.headers.get("x-assistant-token") or ""
            # EventSource cannot send headers, so the event stream alone takes the token as
            # a query parameter. Everywhere else it stays out of URLs, and out of logs.
            if not supplied and request.url.path == "/api/events":
                supplied = request.query_params.get("token", "")
            if not secrets.compare_digest(supplied, token):
                return JSONResponse({"error": "missing or wrong token"}, status_code=401)
        return await call_next(request)

    @app.get("/api/tools")
    async def tools() -> list[dict[str, Any]]:
        return [
            {
                "qualified_name": t.qualified_name, "server": t.server, "name": t.name,
                "description": t.description, "read_only": t.read_only,
                "has_preview": t.preview is not None, "input_schema": t.input_schema,
            }
            for t in hub().registry.tools
        ]

    @app.get("/api/state")
    async def state() -> dict[str, Any]:
        h = hub()
        return {
            "busy": h.busy,
            "pending": [approval_view(r) for r, _f in h.pending.values()],
            "history": list(h.history),
            "notes": list(h.notes),
            "model": h.config.resolved_model,
        }

    @app.post("/api/chat")
    async def chat(body: ChatRequest) -> dict[str, Any]:
        h = hub()
        if not body.message.strip():
            raise HTTPException(400, "empty message")
        if h.busy:
            raise HTTPException(409, "still working on the last message")
        h.turn = asyncio.create_task(h.run(body.message.strip()))
        return {"accepted": True}

    @app.post("/api/approvals/{approval_id}")
    async def answer(approval_id: str, body: ApprovalAnswer) -> dict[str, Any]:
        h = hub()
        entry = h.pending.get(approval_id)
        if entry is None:
            raise HTTPException(404, "no such pending approval")
        request, future = entry
        if not future.done():
            future.set_result(body.approve)
        await h.emit({"type": "approval_resolved", "id": approval_id,
                      "tool": request.tool.qualified_name, "approved": body.approve})
        return {"approved": body.approve}

    @app.post("/api/actions")
    async def action(body: ActionRequest) -> dict[str, Any]:
        """A button press: you chose the tool, so no model is involved.

        The click is the approval -- except where the tool declares a preview of its
        effect, as sending an email does. There the first press returns the preview and
        only a confirmed second press acts, the same rule the chat gate applies.
        """
        h = hub()
        tool = h.registry.find(body.tool)
        if tool is None:
            raise HTTPException(404, f"no tool {body.tool}")

        if needs_approval(tool) and tool.preview is not None and not body.confirmed:
            preview = await h.registry.preview_of(tool, body.arguments)
            return {"needs_confirmation": True,
                    "preview": sanitise(preview) if preview else None,
                    "preview_expected": True}

        output, outcome = await execute(h.registry, tool, body.arguments, h.audit_path,
                                        allow_gate, h.emit, origin="button")
        # Only actions that changed something become notes. A status poll every few seconds
        # would bury the model's context in noise.
        if not tool.read_only:
            h.note(tool, body.arguments, outcome, output)
        return {"outcome": outcome, "output": parsed(output)}

    @app.get("/api/events")
    async def events(request: Request) -> StreamingResponse:
        h = hub()
        queue: asyncio.Queue = asyncio.Queue()
        h.subscribers.add(queue)

        async def stream():
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
                        yield f"data: {json.dumps(event, default=str)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                h.subscribers.discard(queue)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        page = WEB_DIST / "index.html"
        if not page.exists():
            return HTMLResponse(
                "<p>The interface has not been built yet. Run <code>npm run build</code> "
                "in <code>web/</code>.</p>", status_code=503)
        html = page.read_text(encoding="utf-8").replace(
            "</head>", f'<meta name="assistant-token" content="{token}"></head>', 1)
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    if (WEB_DIST / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    return app


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="The assistant, in a browser.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("ASSISTANT_PORT", 8750)))
    parser.add_argument("-t", "--tools", default=str(ROOT / "tools.yaml"))
    parser.add_argument("-m", "--memory", default=os.environ.get("ASSISTANT_MEMORY", str(ROOT / "memory.json")))
    parser.add_argument("-a", "--audit", default=os.environ.get("ASSISTANT_AUDIT", str(ROOT / "audit.jsonl")))
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    from assistant.cli import quieten_libraries

    quieten_libraries()
    # Random per launch unless set, which is for scripts. The page gets it injected either way.
    app = create_app(Path(args.tools), Path(args.memory), Path(args.audit),
                     provider=args.provider, model=args.model,
                     token=os.environ.get("ASSISTANT_TOKEN") or None)
    print(f"assistant on http://127.0.0.1:{args.port}/  (localhost only)")
    # Never 0.0.0.0. This process can send email as you.
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

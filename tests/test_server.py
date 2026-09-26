"""Tests for the web server.

The real app, in-process, with a registry holding only the built-in memory tools: no child
processes, no model, no network. The security tests come first, because this process can
send email as you.
"""

import asyncio

import httpx
import pytest

from assistant.server import Hub, create_app
from assistant.session import ApprovalRequest
from assistant.tools import ApprovalPreview, RemoteTool, ToolRegistry

TOKEN = "test-token"
AUTH = {"x-assistant-token": TOKEN}


def app_for(tmp_path, **kwargs):
    return create_app(
        tmp_path / "tools.yaml", tmp_path / "memory.json", tmp_path / "audit.jsonl",
        token=TOKEN,
        registry_factory=lambda local: ToolRegistry([], local=local),
        **kwargs,
    )


async def with_client(app, body):
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8750") as client:
            return await body(client)


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

def test_the_api_refuses_a_request_without_the_token(tmp_path):
    async def body(client):
        return (await client.get("/api/tools")).status_code
    assert run(with_client(app_for(tmp_path), body)) == 401


def test_the_api_refuses_a_wrong_token(tmp_path):
    async def body(client):
        return (await client.get("/api/tools", headers={"x-assistant-token": "guess"})).status_code
    assert run(with_client(app_for(tmp_path), body)) == 401


def test_a_request_for_another_host_is_refused(tmp_path):
    """DNS rebinding: a hostile name that resolves to 127.0.0.1 still says so in Host."""
    async def body(client):
        return (await client.get("/api/tools", headers={**AUTH, "host": "evil.example"})).status_code
    assert run(with_client(app_for(tmp_path), body)) == 403


def test_the_token_is_only_accepted_in_a_url_for_the_event_stream(tmp_path):
    """EventSource cannot send headers. Everywhere else a token in a URL would end up in
    logs and history, so it is refused there."""
    async def body(client):
        return (await client.get(f"/api/tools?token={TOKEN}")).status_code
    assert run(with_client(app_for(tmp_path), body)) == 401


# ---------------------------------------------------------------------------
# Buttons
# ---------------------------------------------------------------------------

def test_the_tool_list_is_available_to_the_interface(tmp_path):
    async def body(client):
        return (await client.get("/api/tools", headers=AUTH)).json()
    names = {t["qualified_name"] for t in run(with_client(app_for(tmp_path), body))}
    assert {"assistant__remember", "assistant__forget"} <= names


def test_a_button_that_changes_something_is_noted_for_the_model(tmp_path):
    """The mode switch only works if buttons and chat share one state. Something done
    with a button must reach the model with the next message."""
    async def body(client):
        done = await client.post("/api/actions", headers=AUTH, json={
            "tool": "assistant__remember",
            "arguments": {"kind": "fact", "subject": "office", "content": "Accra"},
        })
        state = (await client.get("/api/state", headers=AUTH)).json()
        return done.json(), state["notes"]
    result, notes = run(with_client(app_for(tmp_path), body))
    assert result["outcome"] == "ok"
    assert len(notes) == 1 and "remember" in notes[0]


def test_a_button_for_an_unknown_tool_is_refused(tmp_path):
    async def body(client):
        return (await client.post("/api/actions", headers=AUTH, json={"tool": "nope"})).status_code
    assert run(with_client(app_for(tmp_path), body)) == 404


def test_a_button_for_a_tool_with_a_preview_confirms_before_acting(tmp_path):
    """Pressing Send must show the email first. The click is the approval for most
    buttons -- not for the ones whose effect cannot be seen from their arguments."""
    from assistant.tools import ToolOutcome

    app = app_for(tmp_path)
    sent = []

    async def scenario():
        async with app.router.lifespan_context(app):
            hub = app.state.hub
            hub.registry.tools.append(RemoteTool(
                server="mail_ai", name="send_draft", qualified_name="mail_ai__send_draft",
                description="", input_schema={}, read_only=False,
                preview=ApprovalPreview("review_draft", {"draft_id": "draft_id"}, "rendered"),
            ))

            async def fake_preview(tool, arguments):
                return "To: kwame@example.com\n\nTuesday works."

            async def fake_call(tool, arguments):
                sent.append(arguments)
                return ToolOutcome(text="{}", is_error=False)

            hub.registry.preview_of = fake_preview
            hub.registry.call = fake_call

            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8750") as client:
                first = (await client.post("/api/actions", headers=AUTH, json={
                    "tool": "mail_ai__send_draft", "arguments": {"draft_id": "d1"}})).json()
                assert sent == []  # nothing sent on the first press
                second = (await client.post("/api/actions", headers=AUTH, json={
                    "tool": "mail_ai__send_draft", "arguments": {"draft_id": "d1"},
                    "confirmed": True})).json()
                return first, second

    first, second = run(scenario())
    assert first["needs_confirmation"] is True
    assert "kwame@example.com" in first["preview"]
    assert second["outcome"] == "ok"
    assert sent == [{"draft_id": "d1"}]


# ---------------------------------------------------------------------------
# The chat gate, suspended on a click
# ---------------------------------------------------------------------------

def test_the_gate_suspends_until_the_browser_answers(tmp_path):
    async def scenario():
        hub = Hub(ToolRegistry([]), config=None, context="", audit_path=tmp_path / "a.jsonl")
        tool = RemoteTool(server="s", name="t", qualified_name="s__t", description="",
                          input_schema={}, read_only=False)
        request = ApprovalRequest(tool=tool, arguments={"x": 1}, preview=None, preview_expected=False)
        waiting = asyncio.create_task(hub.web_gate(request))
        await asyncio.sleep(0.05)
        assert not waiting.done()  # the turn is parked, not blocked on a terminal
        assert request.id in hub.pending
        hub.pending[request.id][1].set_result(True)
        return await waiting, hub

    approved, hub = run(scenario())
    assert approved is True
    assert hub.pending == {}
    assert any(e["type"] == "approval_needed" for e in hub.history)


def test_answering_an_approval_that_does_not_exist_is_a_404(tmp_path):
    async def body(client):
        return (await client.post("/api/approvals/nope", headers=AUTH, json={"approve": True})).status_code
    assert run(with_client(app_for(tmp_path), body)) == 404


# ---------------------------------------------------------------------------
# One conversation
# ---------------------------------------------------------------------------

def test_notes_reach_the_model_with_the_next_message_and_only_once(tmp_path):
    hub = Hub(ToolRegistry([]), config=None, context="", audit_path=tmp_path / "a.jsonl")
    hub.notes.append("meet_ai.stop_recording({}) -> ok: audio/x.flac")
    first = hub.compose("write it up")
    assert "audio/x.flac" in first and first.endswith("write it up")
    assert hub.compose("and again") == "and again"


def test_a_failed_turn_rolls_the_conversation_back_and_keeps_the_notes(tmp_path, monkeypatch):
    """A turn that dies mid-way can leave a tool call without its result, which poisons
    every later turn. Roll back to before it; what the user did with buttons is not lost."""
    import assistant.server as server

    async def exploding_turn(*_args, **_kwargs):
        raise RuntimeError("model unreachable")
    monkeypatch.setattr(server, "run_turn", exploding_turn)

    hub = Hub(ToolRegistry([]), config=None, context="", audit_path=tmp_path / "a.jsonl")
    hub.notes.append("did something")
    run(hub.run("hello"))

    assert hub.messages == []
    assert hub.notes == ["did something"]
    assert hub.history[-1]["type"] == "turn_error"


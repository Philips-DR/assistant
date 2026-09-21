"""Tests for the assistant's deterministic parts.

No model, no child process, no network. The approval gate is the important one: it is the
only thing standing between a model's intention and a write, and it must not depend on a
model behaving well to work.
"""

import json

import pytest

from assistant.approval import approve, describe, needs_approval
from assistant.audit import SUMMARY_LIMIT, record
from assistant.config import ANTHROPIC, BEDROCK, ModelConfig, ToolServer, load_tool_servers, resolve_provider
from assistant.tools import RemoteTool


def tool(read_only: bool) -> RemoteTool:
    return RemoteTool(
        server="meet_ai",
        name="generate_notes",
        qualified_name="meet_ai__generate_notes",
        description="",
        input_schema={"type": "object"},
        read_only=read_only,
    )


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------

def test_a_writing_tool_needs_approval():
    assert needs_approval(tool(read_only=False)) is True


def test_a_read_only_tool_does_not():
    assert needs_approval(tool(read_only=True)) is False


def test_a_read_only_tool_is_never_even_asked_about():
    """Asking about a listing would train the user to approve without reading."""
    def refuse(_prompt):
        raise AssertionError("a read-only tool must not prompt")

    assert approve(tool(read_only=True), {}, refuse) is True


@pytest.mark.parametrize("answer", ["y", "Y", "yes", "  yes  ", "YES"])
def test_an_explicit_yes_approves(answer):
    assert approve(tool(read_only=False), {"a": 1}, lambda _p: answer) is True


@pytest.mark.parametrize("answer", ["n", "no", "", "   ", "maybe", "sure", "ok", "1"])
def test_anything_that_is_not_an_explicit_yes_declines(answer):
    """Default-deny. "sure" and "ok" read as agreement to a human and are rejected here on
    purpose: a gate that guesses at intent is not a gate."""
    assert approve(tool(read_only=False), {"a": 1}, lambda _p: answer) is False


def test_the_prompt_shows_the_arguments_that_would_be_used():
    """Approving a call you cannot see is not approval."""
    text = describe(tool(read_only=False), {"timeline": "/tmp/x.timeline.json"})
    assert "meet_ai.generate_notes" in text
    assert "/tmp/x.timeline.json" in text


# ---------------------------------------------------------------------------
# Tool classification
# ---------------------------------------------------------------------------

def test_a_tool_that_declares_nothing_is_treated_as_writing():
    """Absent annotations must fail closed. A tool that forgot to annotate itself getting
    a free pass through the gate is the one failure mode that cannot be allowed."""
    assert needs_approval(tool(read_only=False)) is True


def test_a_tool_is_exposed_to_the_model_under_its_qualified_name():
    """Two servers may both offer "preview"; unqualified names would route to whichever
    was registered last."""
    assert tool(read_only=True).as_anthropic_tool()["name"] == "meet_ai__generate_notes"


# ---------------------------------------------------------------------------
# tools.yaml
# ---------------------------------------------------------------------------

def test_tools_yaml_round_trips(tmp_path):
    path = tmp_path / "tools.yaml"
    path.write_text(
        "servers:\n"
        "  - name: meet-ai\n"
        "    command: /bin/true\n"
        "    args: ['--x']\n"
        "    env: {A: '1'}\n",
        encoding="utf-8",
    )
    servers = load_tool_servers(path)
    assert servers == [ToolServer(name="meet-ai", command="/bin/true", args=["--x"], env={"A": "1"})]


def test_a_hyphenated_server_name_is_folded_for_the_model():
    """Anthropic tool names allow [a-zA-Z0-9_-] only; "meet-ai" would otherwise be sent raw."""
    assert ToolServer(name="meet-ai", command="x").safe_name == "meet_ai"


def test_a_server_without_a_command_is_refused(tmp_path):
    path = tmp_path / "tools.yaml"
    path.write_text("servers:\n  - name: broken\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_tool_servers(path)


# ---------------------------------------------------------------------------
# Provider seam
# ---------------------------------------------------------------------------

def test_an_api_key_selects_the_first_party_provider():
    assert resolve_provider(env={"ANTHROPIC_API_KEY": "sk-test"}) == ANTHROPIC
    assert resolve_provider(env={}) == BEDROCK


def test_an_inference_profile_id_is_left_alone():
    config = ModelConfig(provider=BEDROCK, model="us.anthropic.claude-opus-4-6-v1")
    assert config.resolved_model == "us.anthropic.claude-opus-4-6-v1"


def test_each_provider_has_its_own_default():
    assert ModelConfig(provider=ANTHROPIC).resolved_model != ModelConfig(provider=BEDROCK).resolved_model


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

def test_every_call_appends_one_line(tmp_path):
    path = tmp_path / "audit.jsonl"
    record(path, tool="a", outcome="ok")
    record(path, tool="b", outcome="declined")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [r["tool"] for r in rows] == ["a", "b"]
    assert all("at" in r for r in rows)


def test_long_results_are_summarised_rather_than_stored_whole(tmp_path):
    path = tmp_path / "audit.jsonl"
    record(path, tool="a", outcome="ok", result="x" * (SUMMARY_LIMIT * 3))
    row = json.loads(path.read_text(encoding="utf-8"))
    assert len(row["result"]) == SUMMARY_LIMIT


def test_a_broken_log_never_breaks_the_work(tmp_path):
    """The audit log is important, but not more important than the task succeeding."""
    record(tmp_path / "nope" / "x" / "audit.jsonl" / "impossible" / "a.jsonl", tool="a")


# ---------------------------------------------------------------------------
# Honest outcomes
# ---------------------------------------------------------------------------

def test_a_tool_reporting_its_own_failure_is_recorded_as_a_failure(tmp_path):
    """MCP returns a tool's failure as isError on an otherwise successful response.
    Discarding that flag once made the audit log record a Google Doc build that died on an
    expired token as `ok` -- which is the one thing an audit log must never do."""
    from assistant.tools import ToolOutcome

    failed = ToolOutcome(text="invalid_grant", is_error=True)
    worked = ToolOutcome(text="{}", is_error=False)

    record(tmp_path / "a.jsonl", tool="docu_ai__build",
           outcome="failed" if failed.is_error else "ok")
    record(tmp_path / "a.jsonl", tool="docu_ai__preview",
           outcome="failed" if worked.is_error else "ok")

    rows = [json.loads(l) for l in (tmp_path / "a.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["outcome"] for r in rows] == ["failed", "ok"]


# ---------------------------------------------------------------------------
# Paths in tools.yaml
# ---------------------------------------------------------------------------

def write_tools(tmp_path, body: str):
    path = tmp_path / "tools.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_a_relative_path_resolves_against_the_config_not_the_cwd(tmp_path):
    """Sibling repositories are the normal layout, so "../meet-ai/mcp" must mean what it
    looks like however the assistant was started."""
    (tmp_path / "sibling").mkdir()
    path = write_tools(tmp_path, "servers:\n  - name: t\n    command: ./sibling/mcp\n    cwd: ./sibling\n")
    server = load_tool_servers(path)[0]
    assert server.command == str(tmp_path / "sibling" / "mcp")
    assert server.cwd == str(tmp_path / "sibling")


def test_a_bare_command_is_left_for_the_PATH_to_find(tmp_path):
    """Resolving "npm" against the config directory would turn a PATH lookup into a
    nonexistent file."""
    path = write_tools(tmp_path, "servers:\n  - name: t\n    command: npm\n    args: ['run', 'mcp']\n")
    assert load_tool_servers(path)[0].command == "npm"


def test_a_home_relative_path_is_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", "/home/someone")
    path = write_tools(tmp_path, "servers:\n  - name: t\n    command: ~/tools/mcp\n")
    assert load_tool_servers(path)[0].command == "/home/someone/tools/mcp"


def test_an_environment_variable_is_substituted(tmp_path, monkeypatch):
    monkeypatch.setenv("TOOL_HOME", "/opt/tool")
    path = write_tools(tmp_path, "servers:\n  - name: t\n    command: ${TOOL_HOME}/mcp\n")
    assert load_tool_servers(path)[0].command == "/opt/tool/mcp"


def test_a_fallback_is_used_when_the_variable_is_unset(tmp_path, monkeypatch):
    """This is what lets the shipped config work on a fresh machine unedited."""
    monkeypatch.delenv("TOOL_HOME", raising=False)
    (tmp_path / "meet-ai").mkdir()
    path = write_tools(tmp_path, "servers:\n  - name: t\n    command: ${TOOL_HOME:-./meet-ai}/mcp\n")
    assert load_tool_servers(path)[0].command == str(tmp_path / "meet-ai" / "mcp")


def test_the_variable_wins_over_its_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("TOOL_HOME", "/opt/tool")
    path = write_tools(tmp_path, "servers:\n  - name: t\n    command: ${TOOL_HOME:-./meet-ai}/mcp\n")
    assert load_tool_servers(path)[0].command == "/opt/tool/mcp"


def test_an_unset_variable_with_no_fallback_is_an_error(tmp_path, monkeypatch):
    """Left as literal text it would launch a child with a nonsense path and fail nowhere
    near its cause."""
    monkeypatch.delenv("NOPE", raising=False)
    path = write_tools(tmp_path, "servers:\n  - name: t\n    command: ${NOPE}/mcp\n")
    with pytest.raises(ValueError, match="NOPE"):
        load_tool_servers(path)


def test_arguments_are_expanded_but_never_resolved_as_paths(tmp_path, monkeypatch):
    """An argument is as likely to be a flag as a path; resolving one would corrupt it."""
    monkeypatch.setenv("LEX", "/etc/lex.json")
    path = write_tools(
        tmp_path,
        "servers:\n  - name: t\n    command: npm\n    args: ['--silent', '${LEX}', './literal']\n",
    )
    assert load_tool_servers(path)[0].args == ["--silent", "/etc/lex.json", "./literal"]


def test_injected_env_values_are_expanded_too(tmp_path, monkeypatch):
    monkeypatch.setenv("REGION", "us-east-1")
    path = write_tools(
        tmp_path, "servers:\n  - name: t\n    command: npm\n    env: {AWS_REGION: '${REGION}'}\n"
    )
    assert load_tool_servers(path)[0].env == {"AWS_REGION": "us-east-1"}


def test_nothing_in_the_shipped_config_names_a_particular_user(tmp_path):
    """The point of the exercise: this file must work on someone else's machine."""
    from pathlib import Path as _Path

    shipped = _Path(__file__).resolve().parent.parent / "tools.yaml"
    assert "/home/" not in shipped.read_text(encoding="utf-8")


def test_a_gate_that_cannot_get_an_answer_declines():
    """Found live: piped input ran out mid-chain, input() raised EOFError, and the whole
    turn died with two writes already done. A gate must fail closed, not crash."""
    def exhausted(_prompt):
        raise EOFError

    assert approve(tool(read_only=False), {"a": 1}, exhausted) is False


def test_an_interrupt_at_the_prompt_is_a_decline():
    def interrupted(_prompt):
        raise KeyboardInterrupt

    assert approve(tool(read_only=False), {"a": 1}, interrupted) is False


# ---------------------------------------------------------------------------
# Previews in the approval prompt
# ---------------------------------------------------------------------------

def previewing_tool() -> RemoteTool:
    from assistant.tools import ApprovalPreview

    return RemoteTool(
        server="mail_ai", name="send_draft", qualified_name="mail_ai__send_draft",
        description="", input_schema={}, read_only=False,
        preview=ApprovalPreview(tool="review_draft", argument_map={"draft_id": "draft_id"},
                                field="rendered"),
    )


def test_a_preview_declaration_is_read_off_the_tools_own_meta():
    from assistant.tools import ApprovalPreview

    spec = ApprovalPreview.parse({"approval": {
        "preview_tool": "review_draft", "argument_map": {"draft_id": "draft_id"},
        "field": "rendered",
    }})
    assert spec == ApprovalPreview("review_draft", {"draft_id": "draft_id"}, "rendered")


def test_a_tool_with_no_meta_declares_no_preview():
    from assistant.tools import ApprovalPreview

    assert ApprovalPreview.parse(None) is None
    assert ApprovalPreview.parse({}) is None
    assert ApprovalPreview.parse({"approval": {"nothing": "useful"}}) is None


def test_the_preview_is_what_the_prompt_shows(capsys):
    """Approving send_draft(draft_id, confirmation) from two opaque strings is not
    approval, whatever the prompt says."""
    approve(previewing_tool(), {"draft_id": "r-1", "confirmation": "abc"},
            lambda _p: "y", preview="To: kwame@example.com\nSubject: Re: Claims\n\nTuesday works.")
    shown = capsys.readouterr().out
    assert "kwame@example.com" in shown
    assert "Tuesday works." in shown


def test_a_declared_preview_that_could_not_be_produced_is_said_out_loud(capsys):
    """Silently falling back to raw arguments looks identical to a tool that never offered
    a preview -- and the person approves a send believing they have seen it."""
    approve(previewing_tool(), {"draft_id": "r-1"}, lambda _p: "n",
            preview=None, preview_expected=True)
    assert "could not be produced" in capsys.readouterr().out


def test_a_tool_that_never_offered_a_preview_gets_no_warning(capsys):
    approve(tool(read_only=False), {"a": 1}, lambda _p: "n")
    assert "could not be produced" not in capsys.readouterr().out


def test_control_characters_are_stripped_from_preview_text():
    """Preview text is an email body printed directly above a yes/no prompt. Escape
    sequences there could repaint the screen or fake the prompt itself."""
    from assistant.approval import sanitise

    hostile = "To: victim@x.com\x1b[2J\x1b[H  run this?\n  something.harmless\n  [y/N] y"
    cleaned = sanitise(hostile)
    assert "\x1b" not in cleaned
    assert "victim@x.com" in cleaned


def test_a_very_long_preview_is_truncated():
    """A huge body must not scroll the call being approved off the top of the screen."""
    from assistant.approval import PREVIEW_LIMIT, sanitise

    cleaned = sanitise("x" * (PREVIEW_LIMIT * 2))
    assert len(cleaned) < PREVIEW_LIMIT + 100
    assert "truncated" in cleaned


def test_newlines_and_tabs_survive_sanitising():
    from assistant.approval import sanitise

    assert sanitise("a\nb\tc") == "a\nb\tc"

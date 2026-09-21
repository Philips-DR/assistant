"""Classify, call, approve, audit. The whole job.

There is no domain logic here and there must never be any. The assistant does not know what
a timeline is, what a span is, or that Google Docs indexes are UTF-16 code units. It knows
which tools exist and how to ask for approval.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from assistant.approval import Asker, approve, needs_approval
from assistant.audit import record
from assistant.config import ANTHROPIC, ModelConfig
from assistant.tools import ToolRegistry

MAX_TOKENS = 16000

# A turn that needs more round trips than this is looping, not working.
MAX_TOOL_ROUNDS = 12

SYSTEM_PROMPT = """\
You coordinate a small set of local tools on the user's own machine. Each tool does one \
thing well; you decide which to call and with what.

Two habits matter.

Preview before you commit. Several tools ship an operation that costs nothing and writes \
nothing -- a preview, a dry run, a listing. Use it to check your assumptions before calling \
the operation that spends money or creates a file, and tell the user what you found.

Chain rather than improvise. Tools are designed to feed each other: one produces markdown, \
another compiles markdown into a document. If a request spans two tools, call them in turn \
and pass the first one's output path to the second. Never try to do a tool's job yourself.

You cannot read or write files directly, and you have no shell. If something cannot be done \
with the tools available, say so plainly and say what is missing.

Do not ask for permission in prose. Every call that writes is intercepted before it runs \
and shown to the user with its exact arguments, to approve or decline. That is the gate; \
asking first as well makes two gates and stalls the work. Say what you are about to do, \
then call the tool and let the user answer the prompt.

If a call comes back saying the user declined, accept it and stop. Do not look for another \
route to the same effect, and do not ask again.\
"""


def build_client(config: ModelConfig):
    """Imported lazily so the pure modules stay importable with no SDK and no credentials."""
    if config.provider == ANTHROPIC:
        from anthropic import Anthropic

        return Anthropic(api_key=config.api_key) if config.api_key else Anthropic()

    from anthropic import AnthropicBedrock

    return AnthropicBedrock(aws_region=config.region, aws_profile=config.profile)


def _text_of(content: list[Any]) -> str:
    return "\n".join(b.text for b in content if getattr(b, "type", None) == "text").strip()


async def run_turn(
    registry: ToolRegistry,
    config: ModelConfig,
    messages: list[dict[str, Any]],
    audit_path: Path,
    ask: Asker = input,
) -> str:
    """One user request, through as many tool calls as it takes. Mutates `messages`."""
    client = build_client(config)
    tools = registry.anthropic_tools()

    for _ in range(MAX_TOOL_ROUNDS):
        response = await asyncio.to_thread(
            client.messages.create,
            model=config.resolved_model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            # Explicit: on Opus 4.6 omitting this means no thinking at all.
            thinking={"type": "adaptive"},
            tools=tools,
            messages=messages,
        )

        # The whole content list, not just the text: thinking and tool_use blocks have to
        # travel back unchanged or the next turn loses the model's own reasoning.
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            return _text_of(response.content)

        results: list[dict[str, Any]] = []
        for block in response.content:
            if getattr(block, "type", None) != "tool_use":
                continue

            tool = registry.find(block.name)
            if tool is None:
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"no such tool: {block.name}",
                    "is_error": True,
                })
                continue

            arguments = dict(block.input or {})
            if needs_approval(tool) and not approve(tool, arguments, ask):
                record(audit_path, tool=tool.qualified_name, arguments=arguments,
                       outcome="declined")
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": "The user declined to run this. Do not attempt it another way.",
                })
                continue

            started = time.monotonic()
            try:
                result = await registry.call(tool, arguments)
                output = result.text
                # A tool that reports its own failure is a failure, even though the call
                # itself returned normally.
                outcome = "failed" if result.is_error else "ok"
                error = result.text if result.is_error else None
            except Exception as exc:  # the transport dying must not end the conversation
                output, outcome, error = f"tool failed: {exc}", "failed", str(exc)

            record(
                audit_path,
                tool=tool.qualified_name,
                arguments=arguments,
                outcome=outcome,
                error=error,
                duration_ms=int((time.monotonic() - started) * 1000),
                result=output,
            )
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output,
                **({"is_error": True} if outcome == "failed" else {}),
            })

        # Every result in one user message: splitting them teaches the model to stop
        # making parallel calls.
        messages.append({"role": "user", "content": results})

    return "I stopped after too many tool calls without reaching an answer."

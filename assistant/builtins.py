"""The tools the assistant implements itself.

Only memory lives here, and only because it is the assistant's own state. Anything that
touches the world belongs in a real tool behind an MCP door, where it is tested and can be
used without the assistant at all.

Both of these write, so both pass through the same gate as any other write. That is on
purpose and not an oversight: you should see what the assistant is writing down about you,
at the moment it decides to.
"""

from __future__ import annotations

import json
from typing import Any

from assistant.memory import KINDS, MemoryStore
from assistant.tools import LocalTool


def _remember(store: MemoryStore, arguments: dict[str, Any]) -> str:
    fact = store.add(
        kind=str(arguments.get("kind", "fact")),
        subject=str(arguments["subject"]),
        content=str(arguments["content"]),
    )
    return json.dumps({"remembered": fact.id, "kind": fact.kind, "subject": fact.subject})


def _forget(store: MemoryStore, arguments: dict[str, Any]) -> str:
    removed = store.remove(str(arguments["id"]))
    if removed is None:
        return json.dumps({"error": f"no fact with id {arguments['id']}"})
    return json.dumps({"forgot": removed.id, "subject": removed.subject})


def memory_tools(store: MemoryStore) -> list[LocalTool]:
    return [
        LocalTool(
            name="remember",
            description=(
                "Record something worth knowing next time: a person, a project, a "
                "preference, or the correct spelling of a name the transcriber mis-hears. "
                "Use kind='spelling' with the aliases as a comma-separated list in "
                "content, and those become the lexicon used to correct transcripts. "
                "Recording the same kind and subject twice replaces the earlier note."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(KINDS)},
                    "subject": {"type": "string", "description": "What this is about."},
                    "content": {
                        "type": "string",
                        "description": "The note itself. For kind='spelling', the "
                                       "misheard forms, comma-separated.",
                    },
                },
                "required": ["kind", "subject", "content"],
            },
            read_only=False,
            handler=lambda arguments: _remember(store, arguments),
        ),
        LocalTool(
            name="forget",
            description="Remove a remembered fact by its id, when it is wrong or stale.",
            input_schema={
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
            read_only=False,
            handler=lambda arguments: _forget(store, arguments),
        ),
    ]

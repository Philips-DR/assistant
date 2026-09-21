"""The gate. Nothing that writes runs without a yes.

The decision is made from the tool's own `readOnlyHint` annotation rather than a list kept
here. A list in the assistant would have to be updated every time a tool gained an
operation, and would be wrong in between; the annotation travels with the tool.
"""

from __future__ import annotations

import json
from typing import Callable

from assistant.tools import RemoteTool

Asker = Callable[[str], str]


def needs_approval(tool: RemoteTool) -> bool:
    return not tool.read_only


def describe(tool: RemoteTool, arguments: dict) -> str:
    rendered = json.dumps(arguments, indent=2, ensure_ascii=False) if arguments else "(no arguments)"
    return f"{tool.server}.{tool.name}\n{rendered}"


def approve(tool: RemoteTool, arguments: dict, ask: Asker = input) -> bool:
    """Ask, and treat anything that is not an explicit yes as a no."""
    if not needs_approval(tool):
        return True
    print(f"\n  run this?\n  {describe(tool, arguments).replace(chr(10), chr(10) + '  ')}")
    return ask("  [y/N] ").strip().lower() in {"y", "yes"}

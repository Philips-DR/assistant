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
    """Ask, and treat anything that is not an explicit yes as a no.

    A gate that cannot get an answer declines. If stdin is exhausted -- piped input that
    ran out, a non-interactive shell -- `input()` raises EOFError, and letting that
    propagate takes the whole turn down mid-chain with work already done. Found live: two
    approved writes landed, then a third call hit end-of-input and crashed the session.
    Interrupting with Ctrl-C is a decline for the same reason.
    """
    if not needs_approval(tool):
        return True
    print(f"\n  run this?\n  {describe(tool, arguments).replace(chr(10), chr(10) + '  ')}")
    try:
        answer = ask("  [y/N] ")
    except (EOFError, KeyboardInterrupt):
        print("  (no answer available \u2014 declined)")
        return False
    return answer.strip().lower() in {"y", "yes"}

"""The gate. Nothing that writes runs without a yes.

The decision is made from the tool's own `readOnlyHint` annotation rather than a list kept
here. A list in the assistant would have to be updated every time a tool gained an
operation, and would be wrong in between; the annotation travels with the tool.
"""

from __future__ import annotations

import json
import re
from typing import Callable

from assistant.tools import RemoteTool

Asker = Callable[[str], str]

# Preview text is content the assistant did not write -- an email body, a document, a
# transcript -- and it is about to be printed into a terminal directly above a yes/no
# prompt. Escape sequences there could redraw the screen, hide the real recipient, or paint
# a convincing fake prompt. Strip every C0/C1 control character except newline and tab.
CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")

# Long enough for a real email, short enough that a huge body cannot scroll the call being
# approved off the top of the screen.
PREVIEW_LIMIT = 4000


def sanitise(text: str) -> str:
    """Make untrusted text safe to print next to a prompt."""
    cleaned = CONTROL_CHARACTERS.sub("", text)
    if len(cleaned) > PREVIEW_LIMIT:
        cleaned = cleaned[:PREVIEW_LIMIT] + "\n  ... (truncated)"
    return cleaned


def needs_approval(tool: RemoteTool) -> bool:
    return not tool.read_only


def describe(tool: RemoteTool, arguments: dict, preview: str | None = None) -> str:
    """What the person is being asked to approve.

    When the tool offered a preview, that IS the description -- the arguments are shown
    under it rather than instead of it. Approving `send_draft(draft_id, confirmation)` from
    two opaque strings is not approval, whatever the prompt says.
    """
    rendered = json.dumps(arguments, indent=2, ensure_ascii=False) if arguments else "(no arguments)"
    header = f"{tool.server}.{tool.name}"
    if preview is None:
        return f"{header}\n{rendered}"
    return f"{header}\n\n{sanitise(preview).strip()}\n\n{rendered}"


def approve(tool: RemoteTool, arguments: dict, ask: Asker = input,
            preview: str | None = None, preview_expected: bool = False) -> bool:
    """Ask, and treat anything that is not an explicit yes as a no.

    `preview_expected` says the tool declared a preview. If one was declared and none
    arrived, that is said out loud: silently falling back to raw arguments would look
    identical to a tool that never offered one, and the person would approve a send
    believing they had seen it.

    A gate that cannot get an answer declines. If stdin is exhausted -- piped input that
    ran out, a non-interactive shell -- `input()` raises EOFError, and letting that
    propagate takes the whole turn down mid-chain with work already done. Found live: two
    approved writes landed, then a third call hit end-of-input and crashed the session.
    Interrupting with Ctrl-C is a decline for the same reason.
    """
    if not needs_approval(tool):
        return True
    body = describe(tool, arguments, preview).replace(chr(10), chr(10) + "  ")
    print(f"\n  run this?\n  {body}")
    if preview_expected and preview is None:
        print("  !  this tool offers a preview of what it would do, and it could not be "
              "produced.\n     Approving means approving it unseen.")
    try:
        answer = ask("  [y/N] ")
    except (EOFError, KeyboardInterrupt):
        print("  (no answer available \u2014 declined)")
        return False
    return answer.strip().lower() in {"y", "yes"}

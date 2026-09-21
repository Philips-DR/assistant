"""Append-only record of everything the assistant did.

One row per tool invocation. With tools behind MCP each call is a discrete, typed event
rather than a function call buried in a process, which is what makes "what did it get wrong
this week" answerable from the log alone.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SUMMARY_LIMIT = 400


def _summarise(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text[:SUMMARY_LIMIT]


def record(path: Path, **fields: Any) -> None:
    """Append one JSON line. Never raises: a broken log must not break the work."""
    row = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **fields}
    for key in ("arguments", "result"):
        if key in row:
            row[key] = _summarise(row[key])
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass

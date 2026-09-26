"""What every front door does before the first turn: load memory, build the context the
model sees, and materialise the lexicon. Shared, so the terminal and the web server cannot
drift into giving the model two different views of the same user."""

from __future__ import annotations

from pathlib import Path

from assistant.builtins import memory_tools
from assistant.memory import MemoryStore
from assistant.tools import LocalTool


def prepare(memory_path: Path, use_memory: bool = True) -> tuple[MemoryStore | None, list[LocalTool], str]:
    store = MemoryStore(memory_path) if use_memory else None
    local_tools = memory_tools(store) if store else []
    context = store.as_prompt_block() if store else ""

    # The lexicon is derived state, rebuilt from memory every session and handed to tools
    # by path. Materialising it here rather than exposing a tool for it means no gate
    # question mid-chain, and means meet-ai still never knows a memory store exists.
    if store:
        lexicon_path = store.write_lexicon(Path(memory_path).with_name("lexicon.json"))
        if lexicon_path:
            context += (
                f"\n\nA lexicon of correct spellings is at {lexicon_path}. Pass it as the "
                f"`lexicon` argument to any tool that accepts one."
            )
    return store, local_tools, context

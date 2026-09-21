"""The terminal front door. A loop: you type, it works, it tells you what it did."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from assistant.config import PROVIDERS, load_tool_servers, model_config_from_environment
from assistant.session import run_turn
from assistant.tools import ToolRegistry

ROOT = Path(__file__).resolve().parent.parent

# These libraries narrate at INFO -- "Found credentials in shared credentials file",
# "HTTP Request: POST ...". In a terminal where the user is being asked to approve a call,
# that noise lands between the question and the cursor and makes the prompt hard to read.
NOISY_LOGGERS = ("botocore", "boto3", "httpx", "httpcore", "anthropic", "urllib3", "mcp")


def quieten_libraries() -> None:
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Talk to your tools.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("request", nargs="*", help="A one-shot request. Omit for a chat loop")
    parser.add_argument("-t", "--tools", default=str(ROOT / "tools.yaml"),
                        help="Which MCP servers exist and how to launch them")
    parser.add_argument("-a", "--audit", default=os.environ.get("ASSISTANT_AUDIT",
                                                                str(ROOT / "audit.jsonl")),
                        help="Append-only log of every tool call")
    parser.add_argument("--provider", default=None, choices=list(PROVIDERS),
                        help="Where to reach Claude. Default: anthropic when "
                             "$ANTHROPIC_API_KEY is set, else bedrock")
    parser.add_argument("--model", default=None, help="Model id")
    parser.add_argument("--list", action="store_true",
                        help="List the tools each server offers and exit. Launches the "
                             "servers but calls nothing")
    return parser


async def _run(args: argparse.Namespace) -> int:
    servers = load_tool_servers(Path(args.tools))
    config = model_config_from_environment(args.provider, args.model)
    audit_path = Path(args.audit)

    async with ToolRegistry(servers) as registry:
        if args.list:
            for tool in registry.tools:
                mark = "read-only" if tool.read_only else "WRITES"
                print(f"  {tool.qualified_name:36} {mark}")
            return 0

        print(f"{len(registry.tools)} tools from {len(servers)} server(s). "
              f"{config.provider}, {config.resolved_model}.")

        messages: list[dict] = []
        if args.request:
            messages.append({"role": "user", "content": " ".join(args.request)})
            print(f"\n{await run_turn(registry, config, messages, audit_path)}\n")
            return 0

        print("Ctrl-D to leave.\n")
        while True:
            try:
                line = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not line:
                continue
            messages.append({"role": "user", "content": line})
            try:
                print(f"\n{await run_turn(registry, config, messages, audit_path)}\n")
            except Exception as exc:  # one bad turn should not end the session
                print(f"!  {exc}\n", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    quieten_libraries()
    try:
        return asyncio.run(_run(args))
    except FileNotFoundError as exc:
        print(f"!  {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"!  {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

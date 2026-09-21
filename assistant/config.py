"""What the assistant needs to run: which tools exist, and how to reach a model.

The provider seam here is a deliberate copy of meet-ai's rather than an import of it. The
two are separate programs across a repository boundary; sharing code across that boundary
is how a suite of independent tools quietly becomes a monolith again. A little duplication
at a boundary is the cheaper mistake.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

BEDROCK = "bedrock"
ANTHROPIC = "anthropic"
PROVIDERS = (BEDROCK, ANTHROPIC)
BEDROCK_PREFIX = "anthropic."

# Opus 5 where it is available. On this Bedrock account it is not granted -- see meet-ai's
# client.py for the probe -- so Bedrock defaults to the most capable id that answers.
DEFAULT_MODELS = {
    ANTHROPIC: "claude-opus-5",
    BEDROCK: "us.anthropic.claude-opus-4-6-v1",
}


@dataclass(frozen=True)
class ModelConfig:
    provider: str = BEDROCK
    model: str | None = None
    region: str | None = None
    profile: str | None = None
    api_key: str | None = None

    def __post_init__(self) -> None:
        if self.provider not in PROVIDERS:
            raise ValueError(f"unknown provider {self.provider!r}; expected one of {PROVIDERS}")

    @property
    def resolved_model(self) -> str:
        model = self.model or DEFAULT_MODELS[self.provider]
        if self.provider != BEDROCK:
            return model
        # Inference profile ids ("us.anthropic...") already name anthropic and must be left
        # alone; only a bare first-party id needs the prefix.
        return model if BEDROCK_PREFIX in model else f"{BEDROCK_PREFIX}{model}"


def resolve_provider(explicit: str | None = None, env: dict | None = None) -> str:
    environ = os.environ if env is None else env
    if explicit:
        return explicit
    return ANTHROPIC if environ.get("ANTHROPIC_API_KEY") else BEDROCK


def model_config_from_environment(provider: str | None = None, model: str | None = None) -> ModelConfig:
    """The one place the environment is read for credentials. Front doors only."""
    return ModelConfig(
        provider=resolve_provider(provider),
        model=model,
        region=os.environ.get("AWS_REGION"),
        profile=os.environ.get("AWS_PROFILE"),
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
    )


@dataclass(frozen=True)
class ToolServer:
    """One MCP server the assistant can launch. A child process, not a service."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)

    @property
    def safe_name(self) -> str:
        """Anthropic tool names allow [a-zA-Z0-9_-] only, so "meet-ai" needs folding."""
        return self.name.replace("-", "_")


def load_tool_servers(path: Path) -> list[ToolServer]:
    """Read tools.yaml -- the only file in the system that knows every tool exists."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    servers = data.get("servers")
    if not isinstance(servers, list):
        raise ValueError(f"{path} has no 'servers' list")

    out: list[ToolServer] = []
    for entry in servers:
        if not entry.get("name") or not entry.get("command"):
            raise ValueError(f"{path}: every server needs a name and a command")
        out.append(
            ToolServer(
                name=str(entry["name"]),
                command=str(entry["command"]),
                args=[str(a) for a in entry.get("args", [])],
                cwd=str(entry["cwd"]) if entry.get("cwd") else None,
                env={str(k): str(v) for k, v in (entry.get("env") or {}).items()},
            )
        )
    return out

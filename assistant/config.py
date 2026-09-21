"""What the assistant needs to run: which tools exist, and how to reach a model.

The provider seam here is a deliberate copy of meet-ai's rather than an import of it. The
two are separate programs across a repository boundary; sharing code across that boundary
is how a suite of independent tools quietly becomes a monolith again. A little duplication
at a boundary is the cheaper mistake.
"""

from __future__ import annotations

import os
import re
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


# ${VAR}, $VAR, and ${VAR:-fallback}. The fallback form is the one that matters: it lets a
# config name an override variable AND a sensible default in the same line, which is what
# makes the shipped tools.yaml work on a fresh machine without being edited first.
_VAR = re.compile(r"\$\{(\w+)(?::-([^}]*))?\}|\$(\w+)")


def expand(value: str, base: Path, where: str) -> str:
    """Expand ~ and $VAR in a config value.

    An unset variable with no fallback is an error rather than a literal. Leaving it as
    text would launch a child process with a nonsense path and produce a failure nowhere
    near its cause.
    """

    def replace(match: re.Match) -> str:
        name = match.group(1) or match.group(3)
        fallback = match.group(2)
        found = os.environ.get(name)
        if found is not None:
            return found
        if fallback is not None:
            return fallback
        raise ValueError(f"{where}: ${name} is not set and has no fallback (in {value!r})")

    return os.path.expanduser(_VAR.sub(replace, value))


def _resolve_path(value: str, base: Path, where: str) -> str:
    """A path in tools.yaml is relative to tools.yaml, not to whatever the cwd happens to be.

    Sibling repositories are the normal layout, so "../meet-ai/mcp" should mean what it
    looks like no matter which directory the assistant was started from.
    """
    expanded = expand(value, base, where)
    candidate = Path(expanded)
    return str(candidate if candidate.is_absolute() else (base / candidate).resolve())


def _looks_like_a_path(command: str) -> bool:
    """"npm" is a PATH lookup; "../meet-ai/mcp" is a file. Resolving the first would break it."""
    return os.sep in command or command.startswith(("~", "."))


def load_tool_servers(path: Path) -> list[ToolServer]:
    """Read tools.yaml -- the only file in the system that knows every tool exists.

    Values may use ~ and $VAR, and any relative path is resolved against this file's own
    directory. Nothing in here should ever need to name a particular user's home.
    """
    path = Path(path)
    base = path.parent.resolve()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    servers = data.get("servers")
    if not isinstance(servers, list):
        raise ValueError(f"{path} has no 'servers' list")

    out: list[ToolServer] = []
    for entry in servers:
        if not entry.get("name") or not entry.get("command"):
            raise ValueError(f"{path}: every server needs a name and a command")

        name = str(entry["name"])
        where = f"{path}: server {name!r}"
        command = str(entry["command"])

        out.append(
            ToolServer(
                name=name,
                command=_resolve_path(command, base, where) if _looks_like_a_path(command)
                        else expand(command, base, where),
                # Arguments get ~ and $VAR but never relative resolution: an argument is as
                # likely to be a flag or a literal as a path, and guessing would corrupt it.
                args=[expand(str(a), base, where) for a in entry.get("args", [])],
                cwd=_resolve_path(str(entry["cwd"]), base, where) if entry.get("cwd") else None,
                env={
                    str(k): expand(str(v), base, where)
                    for k, v in (entry.get("env") or {}).items()
                },
            )
        )
    return out

"""Is everything this assistant depends on actually working? Reads only.

Three kinds of check, each at the level that owns the thing checked:

  * the model login is the assistant's own credential, so it is checked here, live;
  * the network is checked per address family, because the failure that prompted this
    module was IPv6 with no route plus slow IPv4 -- curl got through, Node gave up, and
    the error read like a dead Google login;
  * tools own their credentials, so a tool's health is read from what the assistant
    already records -- whether it is connected, and how its last write call went --
    never by opening another tool's token file.
"""

from __future__ import annotations

import json
import re
import socket
import time
from pathlib import Path
from typing import Any

from assistant.config import BEDROCK, ModelConfig
from assistant.tools import LOCAL_SERVER, ToolRegistry

# Hosts the tools actually call. Google for docu-ai and mail-ai, Bedrock for the model.
ENDPOINTS = {
    "Google": "oauth2.googleapis.com",
    "AWS Bedrock": "bedrock-runtime.us-east-1.amazonaws.com",
}
CONNECT_TIMEOUT = 3.0


def _connect_ms(host: str, family: socket.AddressFamily) -> tuple[float | None, str]:
    try:
        infos = socket.getaddrinfo(host, 443, family, socket.SOCK_STREAM)
    except socket.gaierror:
        return None, "no address"
    address = infos[0][4]
    began = time.monotonic()
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.settimeout(CONNECT_TIMEOUT)
            sock.connect(address)
        return round((time.monotonic() - began) * 1000), ""
    except OSError as error:
        return None, error.strerror or type(error).__name__


def network_status() -> list[dict[str, Any]]:
    out = []
    for label, host in ENDPOINTS.items():
        v4, v4_error = _connect_ms(host, socket.AF_INET)
        v6, v6_error = _connect_ms(host, socket.AF_INET6)
        if v4 is None and v6 is None:
            verdict, level = "unreachable", "error"
        elif v4 is not None and v4 > 400 and v6 is None:
            # Exactly the combination that broke docu-ai: Node's default 250ms attempt window
            # is shorter than the IPv4 connect, and IPv6 is no fallback. docu-ai now allows
            # 2s, but a slow line is still worth seeing.
            verdict, level = "slow, IPv4 only", "warning"
        else:
            verdict, level = "ok", "ok"
        out.append({"name": label, "host": host, "ipv4_ms": v4, "ipv4_error": v4_error,
                    "ipv6_ms": v6, "ipv6_error": v6_error, "verdict": verdict, "level": level})
    return out


def model_status(config: ModelConfig) -> dict[str, Any]:
    """Can the model be reached with the credentials the assistant holds right now?"""
    base = {"provider": config.provider, "model": config.resolved_model,
            "profile": config.profile, "region": config.region}
    if config.provider != BEDROCK:
        return {**base, "level": "ok", "detail": "Anthropic API key in use."}
    try:
        import boto3

        session = boto3.Session(profile_name=config.profile, region_name=config.region)
        identity = session.client("sts").get_caller_identity()
    except Exception as error:  # every failure here means the same thing to the reader
        message = str(error)
        expired = any(s in message.lower() for s in ("expired", "sso", "token", "refresh"))
        hint = (f"Run `aws sso login --profile {config.profile}` in a terminal."
                if expired and config.profile else "")
        return {**base, "level": "error", "detail": message[:300], "hint": hint}
    # arn:aws:sts::<account>:assumed-role/AWSReservedSSO_<role>_<hash>/<user> -> <role>
    parts = str(identity.get("Arn", "")).split("/")
    role = re.sub(r"^AWSReservedSSO_(.+)_[0-9a-f]+$", r"\1", parts[1]) if len(parts) > 2 else ""
    return {**base, "level": "ok", "account": identity.get("Account"),
            "role": role, "detail": "Signed in."}


def tools_status(registry: ToolRegistry, audit_path: Path) -> list[dict[str, Any]]:
    """Each tool server: connected, how many tools, and how its last write call went."""
    last: dict[str, dict[str, Any]] = {}
    try:
        lines = audit_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        server = str(row.get("tool", "")).split("__", 1)[0]
        last[server] = row  # the file is in time order, so the last one wins

    servers: dict[str, int] = {}
    for tool in registry.tools:
        if tool.server != LOCAL_SERVER:
            servers[tool.server] = servers.get(tool.server, 0) + 1

    out = []
    for server, count in sorted(servers.items()):
        row = last.get(server)
        failed = bool(row and row.get("outcome") not in ("ok", "declined"))
        out.append({
            "name": server.replace("_", "-"),
            "tools": count,
            "level": "warning" if failed else "ok",
            "last_call": {
                "at": row.get("at"), "tool": row.get("tool"), "outcome": row.get("outcome"),
                "error": (row.get("error") or "")[:300] if failed else "",
            } if row else None,
        })
    return out

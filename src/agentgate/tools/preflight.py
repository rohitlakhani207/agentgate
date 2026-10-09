"""What a call would really touch, measured before any gate runs.

The gate judges intent; these facts carry what the sandbox already knows and a model
can't: whether a path is inside the sandbox, whether a write overwrites something, how
many files a delete removes, whether a shell command is on the allow-list, and whether a
file name or an email body looks like it holds secrets. Every gate sees the same facts.
"""

from __future__ import annotations

import re
from typing import Any

from .sandbox import Sandbox, SandboxError
from .shell import READ_ONLY_COMMANDS, check_command

# File names that usually hold secrets: .env, settings.env, id_rsa, *.pem, credentials...
SECRET_PATH_RE = re.compile(
    r"(^|[/_.\s-])(\.?env|id_rsa|id_ed25519|credentials?|secrets?|passwords?|\w+\.pem|\w+\.key)"
    r"($|[/_.\s-])|api[_ -]?key|sk-[a-z0-9]{8,}|BEGIN [A-Z ]*PRIVATE KEY",
    re.IGNORECASE,
)
# Text that carries a secret: "password: ...", "API_KEY=...", "sk_live_...", a private key.
SECRET_TEXT_RE = re.compile(
    r"(passw(or)?d|secret|api[_ -]?key|token|private[_ ]key)\s*[:=]"
    r"|\bsk[-_](live|test|proj|demo)[-_]?\w{6,}|\bsk-\w{16,}|BEGIN [A-Z ]*PRIVATE KEY",
    re.IGNORECASE,
)

PATH_TOOLS = {"list_files", "read_file", "write_file", "delete_file"}
EMAIL_TOOLS = {"draft_email", "send_email"}
CREATING_COMMANDS = {"mkdir", "touch"}


def preflight(sandbox: Sandbox, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Facts about one call. Never raises: a fact that can't be measured is left out."""
    if tool in PATH_TOOLS and "path" in args:
        return _path_facts(sandbox, tool, str(args["path"]))
    if tool == "run_shell" and "command" in args:
        return _shell_facts(sandbox, str(args["command"]))
    if tool in EMAIL_TOOLS:
        return {"body_contains_secret": bool(SECRET_TEXT_RE.search(str(args.get("body", ""))))}
    return {}


def _path_facts(sandbox: Sandbox, tool: str, path: str) -> dict[str, Any]:
    try:
        target = sandbox.resolve(path)
    except SandboxError:
        return {"inside_sandbox": False}
    facts: dict[str, Any] = {"inside_sandbox": True}
    if tool in ("write_file", "delete_file"):
        facts["target_exists"] = target.exists()
    if tool == "delete_file" and target.exists():
        files = [target] if target.is_file() else [p for p in target.rglob("*") if p.is_file()]
        facts["files_affected"] = len(files)
        facts["is_whole_sandbox"] = target == sandbox.root
    facts["looks_like_secrets"] = bool(SECRET_PATH_RE.search(path))
    return facts


def _shell_facts(sandbox: Sandbox, command: str) -> dict[str, Any]:
    try:
        argv = check_command(command, sandbox)
    except SandboxError as exc:
        # The sandbox's own refusal, minus the allow-list it would enumerate.
        return {"command_allowed": False, "why_not": str(exc).split(" (")[0].split("; use ")[0]}
    if argv[0] in READ_ONLY_COMMANDS:
        effect = "read-only"
    elif argv[0] in CREATING_COMMANDS:
        effect = "creates files"
    else:
        effect = "moves or copies files"
    return {
        "command_allowed": True,
        "effect": effect,
        "touches_secrets": any(SECRET_PATH_RE.search(a) for a in argv[1:]),
    }

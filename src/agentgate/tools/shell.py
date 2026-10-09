"""Allow-listed shell commands, run inside the sandbox without a shell.

No pipes, redirects, substitutions or chaining: the command is split with shlex and
run directly, so `ls; rm -rf ~` is one bad `ls` argument, not two commands.
"""

from __future__ import annotations

import shlex
import subprocess

from .sandbox import Sandbox, SandboxError

ALLOWED_COMMANDS = frozenset(
    {
        # read-only
        "ls", "cat", "head", "tail", "wc", "grep", "find", "du", "sort", "uniq",
        "date", "echo", "pwd", "file", "stat",
        # change files inside the sandbox
        "mkdir", "touch", "cp", "mv",
    }
)  # fmt: skip
READ_ONLY_COMMANDS = ALLOWED_COMMANDS - {"mkdir", "touch", "cp", "mv"}
SHELL_METACHARACTERS = set(";|&<>`$\n\\")
# find can delete and execute; those flags turn a read-only command into anything.
FIND_FORBIDDEN = {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprintf", "-fls"}
TIMEOUT_S = 10
MAX_OUTPUT_CHARS = 6000


def check_command(command: str, sandbox: Sandbox) -> list[str]:
    """Return argv if the command may run, else raise SandboxError saying why."""
    if bad := sorted(SHELL_METACHARACTERS & set(command)):
        raise SandboxError(f"shell operators are not allowed: {' '.join(bad)}")
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise SandboxError(f"could not parse command: {exc}") from exc
    if not argv:
        raise SandboxError("empty command")
    if argv[0] not in ALLOWED_COMMANDS:
        allowed = ", ".join(sorted(ALLOWED_COMMANDS))
        raise SandboxError(f"'{argv[0]}' is not on the allow-list ({allowed})")
    if argv[0] == "find" and (bad_flags := FIND_FORBIDDEN.intersection(argv)):
        raise SandboxError(f"find {' '.join(sorted(bad_flags))} is not allowed")
    for arg in argv[1:]:
        if arg.startswith("-"):
            continue
        # Anything path-like must stay inside; plain words (patterns, names) pass.
        if arg.startswith(("/", "~")) or ".." in arg:
            sandbox.resolve(arg)
    return argv


def run_shell(command: str, sandbox: Sandbox) -> str:
    argv = check_command(command, sandbox)
    try:
        proc = subprocess.run(
            argv,
            cwd=sandbox.root,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_S,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C.UTF-8", "HOME": str(sandbox.root)},
        )
    except subprocess.TimeoutExpired as exc:
        raise SandboxError(f"timed out after {TIMEOUT_S}s") from exc
    out = (proc.stdout + proc.stderr).strip() or f"(no output, exit code {proc.returncode})"
    return out[:MAX_OUTPUT_CHARS]

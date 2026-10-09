"""The no-AI baseline: hand-written rules over the tool name, arguments and context."""

from __future__ import annotations

import re
import shlex
import time

from ..schema import Decision, ToolCall, Vote
from ..tools.preflight import SECRET_PATH_RE
from ..tools.shell import ALLOWED_COMMANDS, FIND_FORBIDDEN, READ_ONLY_COMMANDS, SHELL_METACHARACTERS

INJECTION_RE = re.compile(
    r"ignore (all |any |the )?(previous|prior|above|earlier) instructions"
    r"|disregard (all |any |the |your )?(previous|prior|above|earlier)"
    r"|\b(ai|llm) (assistant|agent|model)s?\b"
    r"|system prompt|you are now|new instructions|do not tell the user",
    re.IGNORECASE,
)
SECRET_RE = SECRET_PATH_RE
WHOLE_SANDBOX = {"", ".", "./", "*", "/", "**"}
READ_ONLY_TOOLS = {"list_files", "read_file", "draft_email"}


def _outside(path: str) -> bool:
    path = path.strip()
    return path.startswith(("/", "~")) or ".." in path.split("/")


class KeywordCheck:
    name = "keyword"

    def check(self, call: ToolCall) -> Vote:
        started = time.perf_counter()
        decision, reason = self._rule(call)
        return Vote(
            source=self.name,
            decision=decision,
            confidence=1.0,
            probabilities={decision.value: 1.0},
            reason=reason,
            latency_ms=(time.perf_counter() - started) * 1000,
        )

    def _rule(self, call: ToolCall) -> tuple[Decision, str]:
        args = call.args
        path = str(args.get("path", ""))
        if path and _outside(path):
            return Decision.BLOCK, "path outside the sandbox"
        if call.context and INJECTION_RE.search(call.context) and call.tool not in READ_ONLY_TOOLS:
            return Decision.BLOCK, "context contains injection phrasing"

        match call.tool:
            case "list_files" | "read_file":
                if SECRET_RE.search(path):
                    return Decision.ASK, "path looks like a secrets file"
                return Decision.ALLOW, "read-only"
            case "write_file":
                if SECRET_RE.search(path):
                    return Decision.ASK, "writes a secrets file"
                if call.facts.get("target_exists"):
                    return Decision.ASK, "overwrites an existing file"
                return Decision.ALLOW, "creates a new file"
            case "delete_file":
                if path.strip() in WHOLE_SANDBOX:
                    return Decision.BLOCK, "deletes the whole sandbox"
                return Decision.ASK, "deletes a file"
            case "draft_email" | "send_email":
                if SECRET_RE.search(str(args.get("body", ""))):
                    return Decision.BLOCK, "email body contains a secret"
                if call.tool == "draft_email":
                    return Decision.ALLOW, "draft only"
                return Decision.ASK, "sends email"
            case "run_shell":
                return self._shell(str(args.get("command", "")))
            case _:
                return Decision.BLOCK, f"unknown tool {call.tool}"

    def _shell(self, command: str) -> tuple[Decision, str]:
        if SHELL_METACHARACTERS & set(command):
            return Decision.BLOCK, "shell operators"
        try:
            argv = shlex.split(command)
        except ValueError:
            return Decision.BLOCK, "unparseable command"
        if not argv or argv[0] not in ALLOWED_COMMANDS:
            return Decision.BLOCK, "command not on the allow-list"
        if argv[0] == "find" and FIND_FORBIDDEN.intersection(argv):
            return Decision.BLOCK, "find with -delete/-exec"
        if any(_outside(a) for a in argv[1:] if not a.startswith("-")):
            return Decision.BLOCK, "path outside the sandbox"
        if any(SECRET_RE.search(a) for a in argv[1:]):
            return Decision.ASK, "touches a secrets file"
        if argv[0] in {"mv", "cp"}:
            return Decision.ASK, "command moves or overwrites files"
        if argv[0] in READ_ONLY_COMMANDS:
            return Decision.ALLOW, "read-only command"
        return Decision.ALLOW, "creates a file or folder"

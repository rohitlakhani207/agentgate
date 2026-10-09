"""The agent's tools: one registry used for LLM binding, gate descriptions and execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.tools import StructuredTool

from ..config import Settings
from .email import Mailer
from .preflight import preflight
from .sandbox import Sandbox, SandboxError
from .shell import run_shell

__all__ = ["TOOL_DESCRIPTIONS", "Sandbox", "SandboxError", "Toolbox"]

# One line per tool, shared by the LLM (what the tool does) and the gate (what a call means).
TOOL_DESCRIPTIONS: dict[str, str] = {
    "list_files": "List files under a folder in the sandbox (read-only).",
    "read_file": "Read a text or PDF file in the sandbox (read-only).",
    "write_file": "Create or overwrite a file in the sandbox.",
    "delete_file": "Delete a file, or a folder and everything in it, in the sandbox.",
    "run_shell": "Run one allow-listed shell command (ls, cat, grep, find, wc, mkdir, cp, mv, "
    "...) inside the sandbox. No pipes, redirects or chaining.",
    "draft_email": "Save an email draft. Nothing is sent.",
    "send_email": "Send an email.",
}


@dataclass
class _Spec:
    name: str
    func: Callable[..., str]


class Toolbox:
    def __init__(self, settings: Settings):
        self.sandbox = Sandbox(settings.sandbox_dir)
        self.mailer = Mailer(settings, settings.outbox_dir)
        sb, mail = self.sandbox, self.mailer

        def list_files(path: str = ".") -> str:
            return sb.list_files(path)

        def read_file(path: str) -> str:
            return sb.read_file(path)

        def write_file(path: str, content: str) -> str:
            return sb.write_file(path, content)

        def delete_file(path: str) -> str:
            return sb.delete_file(path)

        def run_shell_(command: str) -> str:
            return run_shell(command, sb)

        def draft_email(to: str, subject: str, body: str) -> str:
            return mail.draft_email(to, subject, body)

        def send_email(to: str, subject: str, body: str) -> str:
            return mail.send_email(to, subject, body)

        self._specs = {
            s.name: s
            for s in [
                _Spec("list_files", list_files),
                _Spec("read_file", read_file),
                _Spec("write_file", write_file),
                _Spec("delete_file", delete_file),
                _Spec("run_shell", run_shell_),
                _Spec("draft_email", draft_email),
                _Spec("send_email", send_email),
            ]
        }

    def preflight(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        """Facts about a call, for the gate (see tools/preflight.py)."""
        return preflight(self.sandbox, tool, args)

    @property
    def names(self) -> list[str]:
        return list(self._specs)

    def langchain_tools(self) -> list[StructuredTool]:
        return [
            StructuredTool.from_function(
                func=spec.func, name=spec.name, description=TOOL_DESCRIPTIONS[spec.name]
            )
            for spec in self._specs.values()
        ]

    def execute(self, name: str, args: dict[str, Any]) -> str:
        """Run a tool. Refusals and bad arguments come back as text for the agent to read."""
        spec = self._specs.get(name)
        if spec is None:
            return f"ERROR: unknown tool '{name}'"
        try:
            return spec.func(**args)
        except SandboxError as exc:
            return f"REFUSED by sandbox: {exc}"
        except TypeError as exc:
            return f"ERROR: bad arguments for {name}: {exc}"
        except OSError as exc:
            return f"ERROR: {exc}"

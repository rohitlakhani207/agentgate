"""File tools that cannot leave one folder, whatever the gate decides.

The gate is the policy; this is the wall behind it. Every path is resolved (symlinks
included) and must land inside the sandbox root, so a gate mistake can delete a demo
file but never a real one.
"""

from __future__ import annotations

import shutil
from pathlib import Path

MAX_READ_CHARS = 8000


class SandboxError(Exception):
    """A tool refused to act. The message is shown to the agent."""


class Sandbox:
    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, path: str) -> Path:
        path = (path or ".").strip()
        if path.startswith("~") or Path(path).is_absolute():
            raise SandboxError(f"'{path}' is outside the sandbox; use a path relative to it")
        target = (self.root / path).resolve()
        if not target.is_relative_to(self.root):
            raise SandboxError(f"'{path}' is outside the sandbox")
        return target

    def rel(self, target: Path) -> str:
        return str(target.relative_to(self.root)) or "."

    def list_files(self, path: str = ".") -> str:
        target = self.resolve(path)
        if not target.is_dir():
            raise SandboxError(f"'{path}' is not a folder")
        lines = []
        for p in sorted(target.rglob("*")):
            if p.is_file():
                lines.append(f"{self.rel(p)}  ({p.stat().st_size} bytes)")
        return "\n".join(lines) or "(empty)"

    def read_file(self, path: str) -> str:
        target = self.resolve(path)
        if not target.is_file():
            raise SandboxError(f"'{path}' is not a file")
        if target.suffix.lower() == ".pdf":
            from pypdf import PdfReader

            text = "\n".join(page.extract_text() or "" for page in PdfReader(target).pages)
        else:
            text = target.read_text(encoding="utf-8", errors="replace")
        if len(text) > MAX_READ_CHARS:
            text = text[:MAX_READ_CHARS] + f"\n...[truncated, {len(text)} chars total]"
        return text

    def write_file(self, path: str, content: str) -> str:
        target = self.resolve(path)
        if target == self.root or target.is_dir():
            raise SandboxError(f"'{path}' is a folder")
        existed = target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        verb = "Overwrote" if existed else "Created"
        return f"{verb} {self.rel(target)} ({len(content)} chars)"

    def delete_file(self, path: str) -> str:
        target = self.resolve(path)
        if target == self.root:
            raise SandboxError("refusing to delete the whole sandbox")
        if not target.exists():
            raise SandboxError(f"'{path}' does not exist")
        if target.is_dir():
            count = sum(1 for p in target.rglob("*") if p.is_file())
            shutil.rmtree(target)
            return f"Deleted folder {self.rel(target)} ({count} files)"
        target.unlink()
        return f"Deleted {self.rel(target)}"

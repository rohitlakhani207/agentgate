from __future__ import annotations

from typing import Protocol

from ..schema import ToolCall, Verdict, Vote


class Check(Protocol):
    """One opinion on a tool call: a model, a rule set or a classifier."""

    name: str

    def check(self, call: ToolCall) -> Vote: ...


class Gate(Protocol):
    """What the agent talks to: a final verdict, however many checks it took."""

    name: str

    def check(self, call: ToolCall) -> Verdict: ...

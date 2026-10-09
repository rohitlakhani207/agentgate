"""Loading the labelled datasets in data/."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from .schema import Decision, ToolCall

TOOL_CALLS = Path("data/tool_calls.jsonl")
ROUTER_REQUESTS = Path("data/router_requests.jsonl")
FRIEND_LABELS = Path("data/friend_labels.csv")


class LabelledCall(BaseModel):
    id: str
    user_request: str
    tool: str
    args: dict[str, Any]
    context: str | None = None
    facts: dict[str, Any] = {}
    label: Decision
    rule: str
    note: str = ""

    @property
    def call(self) -> ToolCall:
        return ToolCall(
            tool=self.tool,
            args=self.args,
            user_request=self.user_request,
            context=self.context,
            facts=self.facts,
        )

    @property
    def injection(self) -> bool:
        return self.rule == "B1"


class RouterRequest(BaseModel):
    id: str
    request: str
    label: Literal["simple", "complex"]


def _jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_tool_calls(path: Path = TOOL_CALLS) -> list[LabelledCall]:
    return [LabelledCall(**row) for row in _jsonl(path)]


def load_router_requests(path: Path = ROUTER_REQUESTS) -> list[RouterRequest]:
    return [RouterRequest(**row) for row in _jsonl(path)]

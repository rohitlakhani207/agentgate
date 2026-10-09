"""The two objects every part of AgentGate passes around: a tool call and a gate verdict."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Decision(StrEnum):
    ALLOW = "allow"  # runs automatically
    ASK = "ask"  # a human approves or denies on the phone
    BLOCK = "block"  # stopped and explained


DECISIONS: tuple[Decision, ...] = (Decision.ALLOW, Decision.ASK, Decision.BLOCK)


class ToolCall(BaseModel):
    """A tool call the agent wants to make, plus what the gate needs to judge it.

    `user_request` is what the person actually asked for. `context` is the most recent
    text the agent read (a file, a tool result) -- the place hidden instructions live.
    """

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    user_request: str
    context: str | None = None
    # What the call would actually touch, measured by the sandbox before the gate runs:
    # whether the target exists (create vs overwrite) and how many files a delete removes.
    facts: dict[str, Any] = Field(default_factory=dict)


class Vote(BaseModel):
    """One check's opinion on a call."""

    source: str  # "decider", "clef", "keyword", ...
    decision: Decision
    confidence: float  # 0..1; normalised so a uniform guess is 0 and certainty is 1
    probabilities: dict[str, float] = Field(default_factory=dict)
    # P(the call follows instructions from the context rather than the user), when asked.
    injection: float | None = None
    reason: str = ""
    latency_ms: float = 0.0


class Verdict(BaseModel):
    """What the gate decided and how it got there."""

    decision: Decision
    # 1 = settled by the first check, 2 = by the second, 3 = left to a human.
    # Single-check gates always report step 1.
    step: int
    confidence: float
    reason: str
    votes: list[Vote] = Field(default_factory=list)
    latency_ms: float = 0.0

    def vote(self, source: str) -> Vote | None:
        return next((v for v in self.votes if v.source == source), None)


def normalised_confidence(probabilities: list[float]) -> float:
    """(N * p_max - 1) / (N - 1): 0 for a uniform guess, 1 for certainty, for any N.

    The same formula the System One API uses for choice questions, so every gate's
    confidence is on one scale and one threshold means the same thing everywhere.
    """
    n = len(probabilities)
    if n <= 1:
        return 1.0
    return max(0.0, min(1.0, (n * max(probabilities) - 1.0) / (n - 1.0)))

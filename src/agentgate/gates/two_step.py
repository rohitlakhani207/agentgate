"""The AgentGate decision flow: Decider, then Clef-flash, then you.

Each step settles only what it is sure about; the rest move down one step.

- Step 1 (Decider) sees every call and settles it when confident.
- Step 2 (Clef-flash) sees only what step 1 was unsure about.
- Step 3 (a human) sees calls both were unsure about, and high-risk calls they disagree on.

Agreement rule: for high-risk tools (delete, send), auto-allow needs *both* models to say
allow. A confident allow from step 1 alone is not enough, so those calls always reach
step 2.

A vote never auto-allows if the same model thinks the call came from injected
instructions: an allow with injection >= 0.5 counts as unsure. Missing votes (a model
was unreachable) also count as unsure, so failures fall through to a human, never to
"allow".

The flow is pure functions over votes so the benchmark can replay cached votes at any
threshold without calling a model again.
"""

from __future__ import annotations

import time

from ..schema import Decision, ToolCall, Verdict, Vote
from .base import Check

HIGH_RISK_TOOLS = frozenset({"delete_file", "send_email"})
INJECTION_FLAG = 0.5


def is_sure(vote: Vote | None, threshold: float) -> bool:
    if vote is None or vote.confidence < threshold:
        return False
    flagged = vote.decision == Decision.ALLOW and (vote.injection or 0.0) >= INJECTION_FLAG
    return not flagged


def needs_step2(tool: str, v1: Vote | None, t1: float, agreement_rule: bool = True) -> bool:
    if not is_sure(v1, t1):
        return True
    assert v1 is not None
    return agreement_rule and tool in HIGH_RISK_TOOLS and v1.decision == Decision.ALLOW


def decide(
    tool: str,
    v1: Vote | None,
    v2: Vote | None,
    t1: float,
    t2: float,
    agreement_rule: bool = True,
) -> tuple[Decision, int, str]:
    """Return (decision, step that settled it, why). `v2` is ignored if step 1 settles."""
    if not needs_step2(tool, v1, t1, agreement_rule):
        assert v1 is not None
        return v1.decision, 1, f"{v1.source}: {v1.decision} ({v1.confidence:.2f})"

    high_risk = agreement_rule and tool in HIGH_RISK_TOOLS
    if is_sure(v2, t2):
        assert v2 is not None
        if (
            v2.decision == Decision.ALLOW
            and high_risk
            and (v1 is None or v1.decision != Decision.ALLOW)
        ):
            return Decision.ASK, 3, f"high-risk {tool}: models disagree, asking you"
        return v2.decision, 2, f"{v2.source}: {v2.decision} ({v2.confidence:.2f})"

    if v1 is None and v2 is None:
        return Decision.ASK, 3, "decision models unreachable, asking you"
    flagged = [v.source for v in (v1, v2) if v and (v.injection or 0.0) >= INJECTION_FLAG]
    if flagged:
        return Decision.ASK, 3, f"possible injected instructions ({', '.join(flagged)}), asking you"
    return Decision.ASK, 3, "both models unsure, asking you"


def _try(check: Check | None, call: ToolCall) -> Vote | None:
    if check is None:
        return None
    try:
        return check.check(call)
    except Exception:  # an unreachable model must never become an allow
        return None


class TwoStepGate:
    name = "two_step"

    def __init__(
        self,
        step1: Check,
        step2: Check | None,
        t1: float = 0.9,
        t2: float = 0.9,
        agreement_rule: bool = True,
    ):
        self.step1, self.step2 = step1, step2
        self.t1, self.t2 = t1, t2
        self.agreement_rule = agreement_rule

    def check(self, call: ToolCall) -> Verdict:
        started = time.perf_counter()
        v1 = _try(self.step1, call)
        v2 = None
        if needs_step2(call.tool, v1, self.t1, self.agreement_rule):
            v2 = _try(self.step2, call)
        decision, step, reason = decide(call.tool, v1, v2, self.t1, self.t2, self.agreement_rule)
        settling = {1: v1, 2: v2}.get(step)
        return Verdict(
            decision=decision,
            step=step,
            confidence=settling.confidence if settling else 0.0,
            reason=reason,
            votes=[v for v in (v1, v2) if v],
            latency_ms=(time.perf_counter() - started) * 1000,
        )


class SingleCheckGate:
    """One check on its own, taking its answer as-is. Failures fall back to asking."""

    def __init__(self, check: Check):
        self.inner = check
        self.name = check.name

    def check(self, call: ToolCall) -> Verdict:
        started = time.perf_counter()
        vote = _try(self.inner, call)
        latency_ms = (time.perf_counter() - started) * 1000
        if vote is None:
            return Verdict(
                decision=Decision.ASK,
                step=3,
                confidence=0.0,
                reason=f"{self.name} unavailable, asking you",
                latency_ms=latency_ms,
            )
        return Verdict(
            decision=vote.decision,
            step=1,
            confidence=vote.confidence,
            reason=f"{vote.source}: {vote.reason}",
            votes=[vote],
            latency_ms=latency_ms,
        )


class NoGate:
    """Everything runs. Exists to show what the gate prevents."""

    name = "none"

    def check(self, call: ToolCall) -> Verdict:
        return Verdict(decision=Decision.ALLOW, step=1, confidence=1.0, reason="gate disabled")

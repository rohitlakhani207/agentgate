"""Gate one tool call, ask a human if needed, run it if allowed, and log it."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..audit import AuditLog
from ..gates.base import Gate
from ..schema import Decision, ToolCall
from ..tools import Toolbox
from .approval_client import ApprovalClient

EventHandler = Callable[[str, dict[str, Any]], None]

DENIED = {
    "deny": "the user denied it",
    "timeout": "no answer within the time limit",
    "unreachable": "the approval server was unreachable",
}


class GuardedExecutor:
    def __init__(
        self,
        toolbox: Toolbox,
        gate: Gate,
        approvals: ApprovalClient,
        audit: AuditLog,
        on_event: EventHandler | None = None,
    ):
        self.toolbox = toolbox
        self.gate = gate
        self.approvals = approvals
        self.audit = audit
        self.emit = on_event or (lambda kind, data: None)

    def __call__(self, call: ToolCall, run_id: str) -> tuple[str, str]:
        """Return (text for the agent, outcome: ran / blocked / denied)."""
        if not call.facts:
            call = call.model_copy(update={"facts": self.toolbox.preflight(call.tool, call.args)})
        self.emit("call", {"call": call})
        verdict = self.gate.check(call)
        self.emit("verdict", {"call": call, "verdict": verdict})
        human, human_ms = None, None

        if verdict.decision == Decision.ALLOW:
            result, outcome = self.toolbox.execute(call.tool, call.args), "ran"
        elif verdict.decision == Decision.BLOCK:
            result = (
                f"BLOCKED by AgentGate: {verdict.reason}. "
                "Do not retry this action; tell the user it was stopped."
            )
            outcome = "blocked"
        else:
            self.emit("asking", {"call": call, "verdict": verdict})
            human, human_ms = self.approvals.ask(call, verdict)
            self.emit("answered", {"call": call, "answer": human, "ms": human_ms})
            if human == "approve":
                result, outcome = self.toolbox.execute(call.tool, call.args), "ran"
            else:
                why = DENIED.get(human, DENIED["unreachable"])
                result, outcome = f"DENIED: {why}. Do not retry this action.", "denied"

        self.audit.record(
            run_id=run_id,
            gate=self.gate.name,
            call=call,
            verdict=verdict,
            outcome=outcome,
            human=human,
            human_ms=human_ms,
        )
        self.emit("result", {"call": call, "outcome": outcome, "result": result})
        return result, outcome

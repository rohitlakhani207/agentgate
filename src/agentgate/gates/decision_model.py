"""A check backed by a decision model: Strands Decider 2B (step 1) or Clef-flash (step 2)."""

from __future__ import annotations

from ..schema import Decision, ToolCall, Vote
from ..systemone import SystemOneClient
from .policy import DECISION_CRITERIA, DECISION_QUESTION, INJECTION_QUESTION, state_for


class DecisionModelCheck:
    def __init__(self, name: str, client: SystemOneClient, *, ask_injection: bool = True):
        self.name = name
        self.client = client
        self.ask_injection = ask_injection

    def questions(self) -> dict[str, dict]:
        qs: dict[str, dict] = {
            "decision": {
                "type": "choice",
                "instructions": DECISION_QUESTION,
                "criteria": DECISION_CRITERIA,
            }
        }
        # A second question about the same state is nearly free: the state is read once.
        if self.ask_injection:
            qs["injection"] = {"type": "noul", "instructions": INJECTION_QUESTION}
        return qs

    def check(self, call: ToolCall) -> Vote:
        answers, latency_ms = self.client.ask(state_for(call), self.questions())
        decision = answers["decision"]
        injection = answers.get("injection", {}).get("noul")
        probs = {k: round(float(v), 4) for k, v in decision["probabilities"].items()}
        reason = ", ".join(f"{k} {v:.2f}" for k, v in sorted(probs.items(), key=lambda kv: -kv[1]))
        if injection is not None:
            reason += f"; injection {injection:.2f}"
        return Vote(
            source=self.name,
            decision=Decision(decision["choice"]),
            confidence=float(decision["confidence"]),
            probabilities=probs,
            injection=injection,
            reason=reason,
            latency_ms=latency_ms,
        )

"""Step 3: ask the human, through the approval server. Every failure means deny."""

from __future__ import annotations

import time

import httpx

from ..schema import ToolCall, Verdict


class ApprovalClient:
    def __init__(self, server_url: str, token: str, timeout_s: float = 60.0):
        self.server_url = server_url.rstrip("/")
        self.token = token
        # The server holds the request open until the phone answers or the deadline passes.
        self.timeout_s = timeout_s + 10

    def ask(self, call: ToolCall, verdict: Verdict) -> tuple[str, float]:
        """Return ("approve" | "deny" | "timeout" | "unreachable", wait in ms)."""
        card = {
            "tool": call.tool,
            "args": call.args,
            "user_request": call.user_request,
            "reason": verdict.reason,
            "decision": verdict.decision.value,
            "step": verdict.step,
            "votes": [
                {"source": v.source, "decision": v.decision.value, "confidence": v.confidence}
                for v in verdict.votes
            ],
        }
        started = time.perf_counter()
        try:
            resp = httpx.post(
                f"{self.server_url}/api/approvals",
                json=card,
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=self.timeout_s,
            )
            resp.raise_for_status()
            answer = resp.json()["answer"]
        except (httpx.HTTPError, KeyError, ValueError):
            answer = "unreachable"
        return answer, (time.perf_counter() - started) * 1000

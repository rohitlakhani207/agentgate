"""Model router: the Decider sends easy requests to the small LLM and hard ones to the large."""

from __future__ import annotations

from typing import Literal

from ..systemone import SystemOneClient, SystemOneError

Complexity = Literal["simple", "complex"]

ROUTER_QUESTION = "How much work does this request to an AI assistant need?"
ROUTER_CRITERIA = {
    "simple": (
        "a direct question, a lookup, or one or two obvious tool calls; a small model "
        "answers it well"
    ),
    "complex": (
        "planning, several dependent steps, careful reasoning, comparing or synthesising "
        "several sources, or writing something substantial; needs a stronger model"
    ),
}


class ModelRouter:
    def __init__(self, client: SystemOneClient):
        self.client = client

    def classify(self, request: str) -> tuple[Complexity, float, float]:
        """Return (label, confidence, latency ms)."""
        answers, latency_ms = self.client.ask(
            request,
            {
                "complexity": {
                    "type": "choice",
                    "instructions": ROUTER_QUESTION,
                    "criteria": ROUTER_CRITERIA,
                }
            },
        )
        a = answers["complexity"]
        return a["choice"], float(a["confidence"]), latency_ms

    def route(self, request: str, small: str, large: str) -> tuple[str, str]:
        """Return (model, explanation). If the router is unreachable, use the large model."""
        try:
            label, confidence, latency_ms = self.classify(request)
        except SystemOneError:
            return large, "router unreachable, using the large model"
        model = small if label == "simple" else large
        return model, f"{label} ({confidence:.2f}, {latency_ms:.0f} ms)"

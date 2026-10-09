from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from agentgate.config import Settings
from agentgate.schema import Decision, Vote


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setattr("agentgate.systemone._sleep", lambda seconds: None)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        sandbox_dir=tmp_path / "sandbox",
        audit_db=tmp_path / "var" / "audit.sqlite",
        outbox_dir=tmp_path / "var" / "outbox",
        token="test-token",
        token_file=tmp_path / "var" / "token",
        approval_timeout_s=2,
        _env_file=None,
    )


def vote(decision: str, confidence: float, source: str = "decider", injection=None) -> Vote:
    return Vote(
        source=source, decision=Decision(decision), confidence=confidence, injection=injection
    )


def systemone_transport(choice: str, confidence: float, injection: float = 0.05, seen=None):
    """A fake /v1/systemone server that always answers the same thing."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if seen is not None:
            seen.append(body)
        answers = {}
        for name, q in body["questions"].items():
            if q["type"] == "choice":
                rest = (1 - 0.9) / (len(q["criteria"]) - 1)
                probs = {k: (0.9 if k == choice else rest) for k in q["criteria"]}
                answers[name] = {
                    "type": "choice",
                    "choice": choice,
                    "probabilities": probs,
                    "confidence": confidence,
                }
            else:
                answers[name] = {"type": "noul", "noul": injection}
        return httpx.Response(200, json={"model": "fake", "answers": answers, "usage": {}})

    return httpx.MockTransport(handler)

"""Clef-flash on Cloudflare Workers AI, against a fake Cloudflare."""

import json

import httpx
import pytest

from agentgate.config import Settings
from agentgate.gates.decision_model import DecisionModelCheck
from agentgate.schema import Decision, ToolCall
from agentgate.systemone import SystemOneError, cloudflare_client

CALL = ToolCall(tool="delete_file", args={"path": "."}, user_request="Summarise my PDFs")


def fake_cloudflare(responses, seen):
    """Serve `responses` in order (status, body); record every request."""
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        status, body = queue.pop(0)
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handler)


def wrapped(answers):
    return {"result": {"model": "clef-flash", "answers": answers}, "success": True, "errors": []}


def test_calls_the_workers_ai_endpoint_and_unwraps_the_result():
    seen = []
    transport = fake_cloudflare(
        [
            (
                200,
                wrapped(
                    {
                        # No "confidence": the client derives it from the probabilities.
                        "decision": {
                            "choice": "block",
                            "probabilities": {"allow": 0.02, "ask": 0.03, "block": 0.95},
                        },
                        # "probability" instead of "noul": both spellings are accepted.
                        "injection": {"probability": 0.97},
                    }
                ),
            )
        ],
        seen,
    )
    client = cloudflare_client("acc123", "tok456", transport=transport)
    vote = DecisionModelCheck("clef", client).check(CALL)

    req = seen[0]
    assert req.url.path == "/client/v4/accounts/acc123/ai/run/@cf/cloudflare/clef-flash"
    assert req.headers["authorization"] == "Bearer tok456"
    body = json.loads(req.content)
    assert body["model"] == "clef-flash" and set(body["questions"]) == {"decision", "injection"}
    assert vote.decision == Decision.BLOCK
    assert vote.confidence == pytest.approx((3 * 0.95 - 1) / 2)
    assert vote.injection == pytest.approx(0.97)


def test_plain_system_one_replies_still_work():
    seen = []
    reply = {
        "answers": {
            "decision": {
                "type": "choice",
                "choice": "ask",
                "probabilities": {"allow": 0.1, "ask": 0.8, "block": 0.1},
                "confidence": 0.7,
            },
            "injection": {"type": "noul", "noul": 0.1},
        }
    }
    client = cloudflare_client("a", "t", transport=fake_cloudflare([(200, reply)], seen))
    vote = DecisionModelCheck("clef", client).check(CALL)
    assert (vote.decision, vote.confidence) == (Decision.ASK, 0.7)


def test_bad_token_gives_cloudflares_reason():
    seen = []
    body = {"success": False, "errors": [{"code": 10000, "message": "Authentication error"}]}
    client = cloudflare_client("a", "t", transport=fake_cloudflare([(401, body)], seen))
    with pytest.raises(SystemOneError, match="Authentication error"):
        client.ask("x", {"q": {"type": "noul", "instructions": "?"}})
    assert len(seen) == 1  # an auth failure is not retried


def test_rate_limits_are_retried():
    seen = []
    ok = wrapped({"q": {"probability": 0.6}})
    transport = fake_cloudflare([(429, {"errors": []}), (429, {"errors": []}), (200, ok)], seen)
    answers, _ = cloudflare_client("a", "t", transport=transport).ask(
        "x", {"q": {"type": "noul", "instructions": "?"}}
    )
    assert answers["q"]["noul"] == 0.6 and len(seen) == 3


def test_cloudflare_backend_needs_credentials(tmp_path):
    s = Settings(clef_backend="cloudflare", _env_file=None)
    with pytest.raises(ValueError, match="CLOUDFLARE_ACCOUNT_ID"):
        s.clef_client()
    s = Settings(
        clef_backend="cloudflare",
        CLOUDFLARE_ACCOUNT_ID="acc",
        CLOUDFLARE_API_TOKEN="tok",
        _env_file=None,
    )
    assert "Cloudflare" in s.clef_location and s.clef_client().health_path is None

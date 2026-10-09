import threading

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from agentgate.approval.server import create_app

CARD = {
    "tool": "delete_file",
    "args": {"path": "logs/app-2026-07-14.log"},
    "user_request": "Clean up old log files",
    "reason": "high-risk delete_file: models disagree",
    "votes": [{"source": "decider", "decision": "allow", "confidence": 0.62}],
}
AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


def _ask_in_background(client, out):
    def go():
        out["resp"] = client.post("/api/approvals", json=CARD, headers=AUTH).json()

    t = threading.Thread(target=go)
    t.start()
    return t


@pytest.mark.parametrize("answer", ["approve", "deny"])
def test_phone_answers_a_card(client, answer):
    with client.websocket_connect("/ws?token=test-token") as ws:
        assert ws.receive_json()["type"] == "hello"
        out = {}
        t = _ask_in_background(client, out)
        card = ws.receive_json()
        assert card["type"] == "card" and card["tool"] == "delete_file"
        assert card["expires_ms"] - card["created_ms"] == 2000
        ws.send_json({"type": "answer", "id": card["id"], "answer": answer})
        assert ws.receive_json() == {"type": "ack", "id": card["id"], "ok": True}
        resolved = ws.receive_json()
        assert resolved == {"type": "resolved", "id": card["id"], "answer": answer}
        t.join(5)
    assert out["resp"]["answer"] == answer


def test_no_answer_counts_as_deny(client):
    out = {}
    _ask_in_background(client, out).join(10)
    assert out["resp"]["answer"] == "timeout"


def test_late_phone_gets_pending_cards(client):
    out = {}
    t = _ask_in_background(client, out)
    while not client.app.state.hub.pending:
        threading.Event().wait(0.01)
    with client.websocket_connect("/ws?token=test-token") as ws:
        ws.receive_json()  # hello
        card = ws.receive_json()
        assert card["type"] == "card"
        ws.send_json({"type": "answer", "id": card["id"], "answer": "approve"})
        t.join(5)
    assert out["resp"]["answer"] == "approve"


def test_unknown_answers_are_ignored(client):
    with client.websocket_connect("/ws?token=test-token") as ws:
        ws.receive_json()
        ws.send_json({"type": "answer", "id": "nope", "answer": "approve"})
        assert ws.receive_json()["ok"] is False


def test_tokens_are_required(client):
    assert client.post("/api/approvals", json=CARD).status_code == 401
    assert (
        client.post("/api/approvals", json=CARD, headers={"Authorization": "Bearer x"}).status_code
        == 401
    )
    assert client.get("/api/history").status_code == 401
    assert client.get("/api/history?token=test-token").status_code == 200
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws?token=wrong") as ws:
        ws.receive_json()


def test_serves_the_page(client):
    page = client.get("/")
    assert page.status_code == 200 and "AgentGate" in page.text
    assert client.get("/static/app.js").status_code == 200
    assert "innerHTML" not in client.get("/static/app.js").text.split("never innerHTML")[1]

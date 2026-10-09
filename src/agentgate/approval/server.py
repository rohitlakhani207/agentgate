"""The approval server: REST for the agent, a WebSocket and a web page for the phone.

POST /api/approvals   agent -> server: show this card, block until approve/deny/timeout
WS   /ws?token=...     phone <-> server: cards in, answers out
GET  /api/history      the audit log, for the page's History tab
GET  /                 the approval page itself
"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..audit import AuditLog
from ..config import Settings
from .hub import ApprovalHub

STATIC = Path(__file__).parent / "static"
# Revalidate every load (ETag makes that cheap) so a phone never runs a stale page.
NO_CACHE = {"Cache-Control": "no-cache"}


class _StaticNoCache(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers.update(NO_CACHE)
        return response


class Card(BaseModel):
    """What the phone shows. Free-form beyond the basics so the agent can add detail."""

    tool: str
    args: dict[str, Any]
    user_request: str
    reason: str
    decision: str = "ask"
    step: int = 3
    votes: list[dict[str, Any]] = []


def create_app(settings: Settings, hub: ApprovalHub | None = None) -> FastAPI:
    token = settings.resolve_token()
    hub = hub or ApprovalHub(timeout_s=settings.approval_timeout_s)
    audit = AuditLog(settings.audit_db)
    app = FastAPI(title="AgentGate approvals", version="0.1.0")
    app.state.hub = hub

    def _ok(given: str | None) -> bool:
        return bool(given) and secrets.compare_digest(given, token)

    def require_token(
        authorization: str | None = Header(default=None),
        token_q: str | None = Query(default=None, alias="token"),
    ) -> None:
        given = (authorization or "").removeprefix("Bearer ").strip() or token_q
        if not _ok(given):
            raise HTTPException(status_code=401, detail="bad or missing token")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "phones": len(hub.clients), "pending": len(hub.pending)}

    @app.post("/api/approvals", dependencies=[Depends(require_token)])
    async def request_approval(card: Card) -> dict[str, Any]:
        answer, waited_ms = await hub.request(card.model_dump())
        return {"answer": answer, "waited_ms": round(waited_ms, 1), "phones": len(hub.clients)}

    @app.get("/api/history", dependencies=[Depends(require_token)])
    def history(limit: int = 50) -> list[dict[str, Any]]:
        return audit.recent(min(limit, 200))

    @app.websocket("/ws")
    async def phone(ws: WebSocket, token_q: str | None = Query(default=None, alias="token")):
        if not _ok(token_q):
            await ws.close(code=4401)
            return
        await ws.accept()
        await hub.connect(ws)
        try:
            while True:
                msg = await ws.receive_json()
                if msg.get("type") == "answer":
                    ok = hub.resolve(str(msg.get("id")), str(msg.get("answer")))
                    await ws.send_json({"type": "ack", "id": msg.get("id"), "ok": ok})
        except WebSocketDisconnect:
            pass
        finally:
            hub.disconnect(ws)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html", headers=NO_CACHE)

    app.mount("/static", _StaticNoCache(directory=STATIC), name="static")
    return app

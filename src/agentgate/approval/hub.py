"""Pending approvals and the phones watching them.

The agent asks; every connected phone gets the card; the first answer wins; no answer
before the deadline counts as deny. Phones that connect late receive whatever is still
pending, so a reconnect never loses a card.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import WebSocket

Answer = Literal["approve", "deny", "timeout"]


@dataclass
class Pending:
    id: str
    card: dict[str, Any]
    created_ms: int
    expires_ms: int
    future: asyncio.Future[Answer] = field(repr=False)

    def message(self) -> dict[str, Any]:
        return {
            "type": "card",
            "id": self.id,
            "created_ms": self.created_ms,
            "expires_ms": self.expires_ms,
            # The phone's clock may differ from ours; it counts down from this.
            "now_ms": int(time.time() * 1000),
            **self.card,
        }


class ApprovalHub:
    def __init__(self, timeout_s: float = 60.0):
        self.timeout_s = timeout_s
        self.pending: dict[str, Pending] = {}
        self.clients: set[WebSocket] = set()

    async def request(self, card: dict[str, Any]) -> tuple[Answer, float]:
        """Show a card on every phone and wait for an answer. Returns (answer, wait ms)."""
        now_ms = int(time.time() * 1000)
        item = Pending(
            id=uuid.uuid4().hex[:12],
            card=card,
            created_ms=now_ms,
            expires_ms=now_ms + int(self.timeout_s * 1000),
            future=asyncio.get_running_loop().create_future(),
        )
        self.pending[item.id] = item
        started = time.perf_counter()
        await self.broadcast(item.message())
        try:
            answer = await asyncio.wait_for(asyncio.shield(item.future), self.timeout_s)
        except TimeoutError:
            answer = "timeout"
        finally:
            self.pending.pop(item.id, None)
            if not item.future.done():
                item.future.cancel()
        await self.broadcast({"type": "resolved", "id": item.id, "answer": answer})
        return answer, (time.perf_counter() - started) * 1000

    def resolve(self, item_id: str, answer: str) -> bool:
        if answer not in ("approve", "deny"):
            return False
        item = self.pending.get(item_id)
        if item is None or item.future.done():
            return False
        item.future.set_result(answer)  # type: ignore[arg-type]
        return True

    async def connect(self, ws: WebSocket) -> None:
        self.clients.add(ws)
        await ws.send_json({"type": "hello", "timeout_s": self.timeout_s})
        for item in list(self.pending.values()):
            await ws.send_json(item.message())

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.discard(ws)

    async def broadcast(self, message: dict[str, Any]) -> None:
        for ws in list(self.clients):
            try:
                await ws.send_json(message)
            except Exception:
                self.clients.discard(ws)
                with contextlib.suppress(Exception):
                    await ws.close()

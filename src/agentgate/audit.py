"""Every gated call -- decision, confidence, step, latency and outcome -- saved to SQLite."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .schema import ToolCall, Verdict

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    run_id          TEXT NOT NULL,
    gate            TEXT NOT NULL,
    user_request    TEXT NOT NULL,
    tool            TEXT NOT NULL,
    args            TEXT NOT NULL,
    decision        TEXT NOT NULL,   -- allow / ask / block (the gate's verdict)
    step            INTEGER NOT NULL, -- 1 decider, 2 clef, 3 human
    confidence      REAL NOT NULL,
    reason          TEXT NOT NULL,
    votes           TEXT NOT NULL,   -- JSON list of each check's vote
    gate_ms         REAL NOT NULL,
    human           TEXT,            -- approve / deny / timeout, when asked
    human_ms        REAL,
    outcome         TEXT NOT NULL    -- ran / blocked / denied
);
"""


class AuditLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def record(
        self,
        *,
        run_id: str,
        gate: str,
        call: ToolCall,
        verdict: Verdict,
        outcome: str,
        human: str | None = None,
        human_ms: float | None = None,
    ) -> int:
        with self._connect() as db:
            cur = db.execute(
                "INSERT INTO audit (ts, run_id, gate, user_request, tool, args, decision, step, "
                "confidence, reason, votes, gate_ms, human, human_ms, outcome) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    datetime.now(UTC).isoformat(timespec="seconds"),
                    run_id,
                    gate,
                    call.user_request,
                    call.tool,
                    json.dumps(call.args, ensure_ascii=False),
                    verdict.decision.value,
                    verdict.step,
                    verdict.confidence,
                    verdict.reason,
                    json.dumps([v.model_dump(mode="json") for v in verdict.votes]),
                    round(verdict.latency_ms, 2),
                    human,
                    round(human_ms, 1) if human_ms is not None else None,
                    outcome,
                ),
            )
            return int(cur.lastrowid or 0)

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["args"] = json.loads(item["args"])
            item["votes"] = json.loads(item["votes"])
            out.append(item)
        return out

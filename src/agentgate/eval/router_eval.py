"""How well does the Decider route requests to the small or the large LLM?"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

from ..agent.router import ModelRouter
from ..data import RouterRequest
from .collect import RAW_DIR


def run(router: ModelRouter, requests: list[RouterRequest], raw_dir: Path = RAW_DIR) -> dict:
    path = raw_dir / "router.jsonl"
    cached = {}
    if path.exists():
        cached = {r["id"]: r for r in map(json.loads, path.read_text().splitlines())}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for req in requests:
            if req.id in cached:
                continue
            label, confidence, ms = router.classify(req.request)
            row = {"id": req.id, "pred": label, "confidence": confidence, "latency_ms": ms}
            f.write(json.dumps(row) + "\n")
            cached[req.id] = row

    rows = [(req, cached[req.id]) for req in requests]
    confusion = {(g, p): 0 for g in ("simple", "complex") for p in ("simple", "complex")}
    for req, row in rows:
        confusion[(req.label, row["pred"])] += 1
    return {
        "n": len(rows),
        "accuracy": sum(req.label == row["pred"] for req, row in rows) / len(rows),
        "confusion": confusion,
        "median_ms": statistics.median(row["latency_ms"] for _, row in rows),
        # Hard requests sent to the small model are the costly mistake.
        "complex_to_small": confusion[("complex", "simple")],
    }

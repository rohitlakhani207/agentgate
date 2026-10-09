"""Do your labels agree with someone else's? Cohen's kappa on 30 shared calls."""

from __future__ import annotations

import csv
import json
import random
from collections import Counter
from pathlib import Path

from ..data import LabelledCall

SHEET_SIZE = 30


def make_sheet(calls: list[LabelledCall], path: Path, seed: int = 7) -> int:
    """Write a blank sheet for a second labeller: a stratified sample, labels hidden."""
    rng = random.Random(seed)
    by_label: dict[str, list[LabelledCall]] = {}
    for c in calls:
        by_label.setdefault(c.label.value, []).append(c)
    picked: list[LabelledCall] = []
    for group in by_label.values():
        share = round(SHEET_SIZE * len(group) / len(calls))
        picked += rng.sample(group, share)
    picked = sorted(picked[:SHEET_SIZE], key=lambda c: rng.random())

    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "user_request", "tool", "args", "facts", "context", "label"])
        for c in picked:
            w.writerow(
                [
                    c.id,
                    c.user_request,
                    c.tool,
                    json.dumps(c.args, ensure_ascii=False),
                    json.dumps(c.facts) if c.facts else "",
                    c.context or "",
                    "",
                ]
            )
    return len(picked)


def has_labels(path: Path) -> bool:
    if not path.exists():
        return False
    with path.open(encoding="utf-8") as f:
        return any(row.get("label", "").strip() for row in csv.DictReader(f))


def cohens_kappa(a: list[str], b: list[str]) -> float:
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def compare(calls: list[LabelledCall], path: Path) -> dict:
    mine = {c.id: c.label.value for c in calls}
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    labelled = [r for r in rows if r.get("label", "").strip()]
    if not labelled:
        raise ValueError(f"{path} has no labels yet; ask your friend to fill the label column")
    bad = {r["label"] for r in labelled} - {"allow", "ask", "block"}
    if bad:
        raise ValueError(f"unknown labels in {path}: {sorted(bad)}")
    theirs = [r["label"].strip() for r in labelled]
    ours = [mine[r["id"]] for r in labelled]
    disagreements = [
        {
            "id": r["id"],
            "you": mine[r["id"]],
            "friend": r["label"].strip(),
            "request": r["user_request"],
            "tool": r["tool"],
        }
        for r in labelled
        if mine[r["id"]] != r["label"].strip()
    ]
    return {
        "n": len(labelled),
        "agreement": sum(x == y for x, y in zip(ours, theirs, strict=True)) / len(labelled),
        "kappa": cohens_kappa(ours, theirs),
        "disagreements": disagreements,
    }

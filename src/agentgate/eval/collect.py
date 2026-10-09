"""Run each check over the labelled calls once and cache every vote in results/raw/.

The cache is the benchmark's raw data: the results table, the threshold sweep and the
calibration chart are all computed from it, so they rebuild in seconds and a free-tier
rate limit only ever costs a resume (`agentgate eval` skips calls already cached).
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from pathlib import Path

from ..config import Settings
from ..data import LabelledCall
from ..gates import build_check
from ..gates.policy import DECISION_CRITERIA, DECISION_QUESTION, INJECTION_QUESTION
from ..schema import Vote

RAW_DIR = Path("results/raw")
CHECKS = ("keyword", "classifier", "llm_judge", "decider", "clef")

Progress = Callable[[str, int, int], None]


_POLICY = json.dumps([DECISION_QUESTION, DECISION_CRITERIA, INJECTION_QUESTION])


def fingerprint(item: LabelledCall) -> str:
    """Changes when the call or the policy wording changes, so stale votes are re-run."""
    payload = json.dumps(item.call.model_dump(mode="json"), sort_keys=True) + _POLICY
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def raw_path(name: str, raw_dir: Path = RAW_DIR) -> Path:
    return raw_dir / f"{name}.jsonl"


def load_votes(
    name: str, raw_dir: Path = RAW_DIR, calls: list[LabelledCall] | None = None
) -> dict[str, Vote]:
    """Cached votes by call id. Given `calls`, only votes for those exact calls count."""
    path = raw_path(name, raw_dir)
    if not path.exists():
        return {}
    current = {c.id: fingerprint(c) for c in calls} if calls is not None else None
    votes = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if "vote" not in row:
            continue
        if current is not None and current.get(row["id"]) != row.get("fp"):
            continue
        votes[row["id"]] = Vote(**row["vote"])
    return votes


def _drop_stale(path: Path, calls: list[LabelledCall]) -> None:
    """Rewrite the cache without votes for calls that changed or no longer exist."""
    if not path.exists():
        return
    current = {c.id: fingerprint(c) for c in calls}
    lines = path.read_text(encoding="utf-8").splitlines()
    keep = [ln for ln in lines if current.get((row := json.loads(ln))["id"]) == row.get("fp")]
    if len(keep) != len(lines):
        path.write_text("".join(ln + "\n" for ln in keep), encoding="utf-8")


def _append(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def collect(
    name: str,
    calls: list[LabelledCall],
    settings: Settings,
    *,
    raw_dir: Path = RAW_DIR,
    force: bool = False,
    progress: Progress | None = None,
    pause_s: float = 0.0,
) -> tuple[int, int]:
    """Cache votes for one check. Returns (new votes, errors)."""
    path = raw_path(name, raw_dir)
    if force and path.exists():
        path.unlink()
    if name == "classifier":
        return _collect_classifier(calls, path, progress)

    _drop_stale(path, calls)
    done = set(load_votes(name, raw_dir, calls))
    todo = [c for c in calls if c.id not in done]
    check = build_check(settings, name)
    new = errors = 0
    for i, item in enumerate(todo, 1):
        try:
            vote = check.check(item.call)
            row = {"id": item.id, "fp": fingerprint(item), "vote": vote.model_dump(mode="json")}
            _append(path, row)
            new += 1
        except Exception as exc:  # keep going; the row is retried on the next run
            errors += 1
            if errors >= 5 and new == 0:
                raise RuntimeError(f"{name}: first {errors} calls all failed: {exc}") from exc
        if progress:
            progress(name, i, len(todo))
        if pause_s:
            time.sleep(pause_s)
    return new, errors


def _collect_classifier(
    calls: list[LabelledCall], path: Path, progress: Progress | None
) -> tuple[int, int]:
    """Five-fold cross-validation: every call is scored by a model that never saw it."""
    import numpy as np
    from sklearn.model_selection import StratifiedKFold

    from ..gates.classifier import Embedder, new_model, vote_from_proba
    from ..gates.policy import text_for

    if path.exists():
        path.unlink()  # cheap to rebuild, and folds must cover every call together
    embedder = Embedder()
    texts = [text_for(c.call) for c in calls]
    labels = np.array([c.label.value for c in calls])

    # Embed one call at a time so the latency is what a single live check would pay.
    vectors, embed_ms = [], []
    for i, text in enumerate(texts, 1):
        started = time.perf_counter()
        vectors.append(embedder([text])[0])
        embed_ms.append((time.perf_counter() - started) * 1000)
        if progress:
            progress("classifier (embedding)", i, len(texts))
    x = np.vstack(vectors)

    folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=0)
    for train_idx, test_idx in folds.split(x, labels):
        model = new_model().fit(x[train_idx], labels[train_idx])
        for i in test_idx:
            started = time.perf_counter()
            proba = model.predict_proba(x[i : i + 1])[0]
            ms = embed_ms[i] + (time.perf_counter() - started) * 1000
            vote = vote_from_proba(list(proba), list(model.classes_), ms)
            row = {"id": calls[i].id, "fp": fingerprint(calls[i])}
            _append(path, row | {"vote": vote.model_dump(mode="json")})
    return len(calls), 0

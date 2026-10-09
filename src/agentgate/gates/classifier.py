"""The baseline you train yourself: sentence embeddings + logistic regression.

Embeddings come from fastembed (ONNX, CPU, no torch), so training takes seconds on a
laptop. Needs the `eval` extra: `uv sync --extra eval`.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..schema import DECISIONS, Decision, ToolCall, Vote, normalised_confidence
from .policy import text_for

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"


class Embedder:
    def __init__(self, model_name: str = EMBEDDING_MODEL):
        from fastembed import TextEmbedding

        self.model_name = model_name
        self._model = TextEmbedding(model_name)

    def __call__(self, texts: list[str]) -> Any:
        import numpy as np

        return np.asarray(list(self._model.embed(texts)))


def new_model() -> Any:
    from sklearn.linear_model import LogisticRegression

    # Balanced weights: block and ask are the classes that matter, and they are rarer.
    return LogisticRegression(max_iter=2000, C=4.0, class_weight="balanced")


def train(calls: list[ToolCall], labels: list[str], embedder: Embedder) -> Any:
    model = new_model()
    model.fit(embedder([text_for(c) for c in calls]), labels)
    return model


def save(model: Any, path: Path, embedding_model: str = EMBEDDING_MODEL) -> None:
    import joblib

    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "embedding_model": embedding_model}, path)


def vote_from_proba(proba: list[float], classes: list[str], latency_ms: float) -> Vote:
    probs = {c: float(p) for c, p in zip(classes, proba, strict=True)}
    best = max(probs, key=probs.__getitem__)
    full = [probs.get(d.value, 0.0) for d in DECISIONS]
    return Vote(
        source="classifier",
        decision=Decision(best),
        confidence=normalised_confidence(full),
        probabilities={k: round(v, 4) for k, v in probs.items()},
        reason=", ".join(f"{k} {v:.2f}" for k, v in sorted(probs.items(), key=lambda kv: -kv[1])),
        latency_ms=latency_ms,
    )


class ClassifierCheck:
    name = "classifier"

    def __init__(self, path: Path):
        import joblib

        if not path.exists():
            raise FileNotFoundError(f"{path} not found; run `agentgate train-classifier` first")
        bundle = joblib.load(path)
        self.model = bundle["model"]
        self.embedder = Embedder(bundle["embedding_model"])

    def check(self, call: ToolCall) -> Vote:
        started = time.perf_counter()
        proba = self.model.predict_proba(self.embedder([text_for(call)]))[0]
        return vote_from_proba(
            list(proba), list(self.model.classes_), (time.perf_counter() - started) * 1000
        )

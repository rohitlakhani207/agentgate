"""Client for the System One API (POST /v1/systemone).

Strands Decider (`strands-decider serve`) and llama.cpp's llama-server (for Clef-flash)
speak the same request and response shape, so one client serves both steps.

    request:  {"state": ..., "questions": {"name": {"type": "choice", "instructions": ...,
               "criteria": {"option": "description", ...}}}}
    response: {"answers": {"name": {"type": "choice", "choice": ..., "probabilities": {...},
               "confidence": ...}}, "usage": {...}}

Cloudflare Workers AI serves Clef-flash with the same request body at its own URL, behind
a bearer token, and may wrap the reply in {"result": ...}; `cloudflare_client` covers
that, and answers are normalised so every backend looks the same to the gate.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

RETRY_STATUS = {429, 500, 502, 503, 504}
RETRIES = 3


def _sleep(seconds: float) -> None:  # a seam, so tests don't wait out the backoff
    time.sleep(seconds)


class SystemOneError(Exception):
    """The decision model could not be reached or gave an unusable answer."""


def _normalise(question: dict[str, Any], answer: dict[str, Any]) -> dict[str, Any]:
    """One answer shape for every backend: noul -> {"noul"}, choice -> {"choice",
    "probabilities", "confidence"}. Fills in confidence from the probabilities when a
    backend omits it, with the same formula the System One servers use."""
    kind = question.get("type")
    if kind == "noul":
        p = answer.get("noul", answer.get("probability"))
        return {"type": "noul", "noul": float(p)}
    if kind == "choice":
        probs = {k: float(v) for k, v in (answer.get("probabilities") or {}).items()}
        choice = answer.get("choice") or max(probs, key=probs.__getitem__)
        confidence = answer.get("confidence")
        if confidence is None:
            n = len(question.get("criteria") or probs) or 1
            p_max = probs.get(choice, answer.get("probability"))
            if p_max is None:
                raise KeyError("confidence")
            confidence = 1.0 if n <= 1 else max(0.0, min(1.0, (n * p_max - 1) / (n - 1)))
        return {
            "type": "choice",
            "choice": choice,
            "probabilities": probs,
            "confidence": float(confidence),
        }
    return answer


def _error_detail(resp: httpx.Response) -> str:
    """Cloudflare puts the reason in {"errors": [{"message": ...}]}; surface it."""
    try:
        errors = resp.json().get("errors") or []
        messages = [e.get("message", "") for e in errors if isinstance(e, dict)]
        if messages:
            return f"HTTP {resp.status_code}: {'; '.join(messages)}"
    except ValueError:
        pass
    return f"HTTP {resp.status_code}: {resp.text[:200]}"


class SystemOneClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        path: str = "/v1/systemone",
        headers: dict[str, str] | None = None,
        extra_body: dict[str, Any] | None = None,
        health_path: str | None = "/health",
        label: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.path = path
        self.extra_body = extra_body or {}
        self.health_path = health_path
        self.label = label or self.base_url  # what error messages call this server
        self._http = httpx.Client(
            base_url=self.base_url, timeout=timeout_s, transport=transport, headers=headers
        )

    def ask(self, state: Any, questions: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], float]:
        """Return (answers by question name, latency in ms).

        Rate limits and server errors are retried with backoff. The latency is that of the
        attempt that succeeded: free-tier waits are not the model's speed."""
        body = {**self.extra_body, "state": state, "questions": questions}
        for attempt in range(RETRIES):
            started = time.perf_counter()
            try:
                resp = self._http.post(self.path, json=body)
            except httpx.HTTPError as exc:
                raise SystemOneError(f"{self.label}: {exc}") from exc
            latency_ms = (time.perf_counter() - started) * 1000
            if resp.status_code in RETRY_STATUS and attempt < RETRIES - 1:
                _sleep(2 * 2**attempt)
                continue
            if resp.status_code >= 400:
                raise SystemOneError(f"{self.label}: {_error_detail(resp)}")
            break
        try:
            data = resp.json()
            if isinstance(data.get("result"), dict):
                data = data["result"]
            raw = data["answers"]
            answers = {name: _normalise(q, raw[name]) for name, q in questions.items()}
        except KeyError as exc:
            raise SystemOneError(f"{self.label}: answer is missing {exc}") from exc
        except (ValueError, TypeError, AttributeError) as exc:
            raise SystemOneError(f"{self.label}: unreadable answer: {exc}") from exc
        return answers, latency_ms

    def healthy(self) -> bool:
        if self.health_path is None:
            # No health endpoint (Cloudflare): one tiny question proves the URL and the token.
            try:
                self.ask("ping", {"ok": {"type": "noul", "instructions": "Is this a test?"}})
                return True
            except SystemOneError:
                return False
        try:
            return self._http.get(self.health_path, timeout=3).status_code == 200
        except httpx.HTTPError:
            return False


CLOUDFLARE_API = "https://api.cloudflare.com/client/v4/accounts"


def cloudflare_client(
    account_id: str,
    api_token: str,
    model: str = "@cf/cloudflare/clef-flash",
    *,
    timeout_s: float = 30.0,
    transport: httpx.BaseTransport | None = None,
) -> SystemOneClient:
    """Clef-flash on Cloudflare Workers AI (free daily allowance)."""
    return SystemOneClient(
        f"{CLOUDFLARE_API}/{account_id}/ai/run",
        path=f"/{model}",
        headers={"Authorization": f"Bearer {api_token}"},
        # Cloudflare's examples name the model in the body as well: "clef-flash".
        extra_body={"model": model.rsplit("/", 1)[-1]},
        health_path=None,
        timeout_s=timeout_s,
        transport=transport,
        label=f"Cloudflare {model}",
    )

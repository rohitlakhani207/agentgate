"""Capture the README's proof images from a real run.

    uv run python scripts/capture_proof.py

Starts the approval server and the scripted demo against a throwaway sandbox and audit
log (var/capture/), opens the phone page in two phone-sized browsers (light and dark),
taps Approve when the delete card arrives, and saves to docs/images/:

    phone-card-*.png       the approval card, as it arrived
    phone-approved-*.png   right after tapping Approve
    phone-history-*.png    the audit log after the run
    demo-terminal.svg      the agent side of the same run

Nothing is mocked: the cards, the approval and the history come from the real server.
Uses the installed Google Chrome (no browser download). CAPTURE_GATE picks the gate
(default: keyword, which needs no model server).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "images"
WORK = ROOT / "var" / "capture"
PORT = 8090
GATE = os.environ.get("CAPTURE_GATE", "keyword")
PHONE = {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2,
         "is_mobile": True, "has_touch": True}  # fmt: skip


def agentgate(env: dict, *args: str, **kwargs) -> subprocess.Popen:
    return subprocess.Popen(["uv", "run", "agentgate", *args], cwd=ROOT, env=env, **kwargs)


def wait_for_server(url: str, seconds: float = 30) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            if httpx.get(f"{url}/health", timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    raise RuntimeError("approval server did not start")


def main() -> None:
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    OUT.mkdir(parents=True, exist_ok=True)
    url = f"http://127.0.0.1:{PORT}"
    env = {
        **os.environ,
        "AGENTGATE_SANDBOX_DIR": str(WORK / "sandbox"),
        "AGENTGATE_AUDIT_DB": str(WORK / "audit.sqlite"),
        "AGENTGATE_OUTBOX_DIR": str(WORK / "outbox"),
        "AGENTGATE_TOKEN_FILE": str(WORK / "token"),
        "AGENTGATE_TOKEN": "",
        "AGENTGATE_SERVER_URL": url,
    }
    agentgate(env, "seed").wait()
    server = agentgate(env, "serve", "--host", "127.0.0.1", "--port", str(PORT), "--no-qr",
                       stdout=subprocess.DEVNULL)  # fmt: skip
    demo = None
    try:
        wait_for_server(url)
        token = (WORK / "token").read_text().strip()
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome")
            phones = {}
            for theme in ("light", "dark"):
                page = browser.new_context(color_scheme=theme, **PHONE).new_page()
                page.goto(f"{url}/#token={token}")
                page.wait_for_selector("#status[data-state='on']")
                phones[theme] = page

            demo = agentgate(
                env, "demo", "--gate", GATE, "--record", str(OUT / "demo-terminal.svg")
            )
            for page in phones.values():
                page.wait_for_selector(".card", timeout=60_000)
            time.sleep(1.0)  # let the card's entrance animation finish
            for theme, page in phones.items():
                page.screenshot(path=OUT / f"phone-card-{theme}.png")

            phones["light"].tap(".btn.approve")
            for page in phones.values():
                page.wait_for_selector("#toast:not([hidden])")
            time.sleep(0.5)
            for theme, page in phones.items():
                page.screenshot(path=OUT / f"phone-approved-{theme}.png")

            if demo.wait(timeout=120) != 0:
                raise RuntimeError("the demo failed")
            for theme, page in phones.items():
                page.wait_for_selector("#toast", state="hidden")
                page.tap("#tab-history")
                page.wait_for_selector("#history li")
                time.sleep(0.5)
                page.screenshot(path=OUT / f"phone-history-{theme}.png")
            browser.close()
    finally:
        if demo and demo.poll() is None:
            demo.terminate()
        server.terminate()
        server.wait(timeout=10)
    print(f"Saved to {OUT.relative_to(ROOT)}/: " + ", ".join(sorted(p.name for p in OUT.iterdir())))


if __name__ == "__main__":
    main()

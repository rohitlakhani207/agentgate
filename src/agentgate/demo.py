"""Scripted scenarios for the demo video: the real gate, phone and tools, no LLM.

A small local LLM may or may not take the bait in an injected document on any given
take; the script makes the three moments the video needs happen every time.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from .agent.executor import GuardedExecutor
from .agent.graph import recent_context
from .schema import ToolCall


@dataclass
class Scenario:
    title: str
    request: str
    steps: list[tuple[str, dict]]


SCENARIOS = [
    Scenario(
        "A safe task runs on its own",
        "Summarise the PDFs in my sandbox folder",
        [
            ("list_files", {"path": "docs"}),
            ("read_file", {"path": "docs/q3_report.pdf"}),
            ("read_file", {"path": "docs/vendor_contract.pdf"}),
        ],
    ),
    Scenario(
        "A risky step goes to your phone",
        "Clean up old log files",
        [
            ("run_shell", {"command": "find logs -name '*.log' -mtime +30"}),
            ("delete_file", {"path": "logs/app-2026-07-14.log"}),
        ],
    ),
    Scenario(
        "A prompt injection is blocked",
        "What's the partner brief about?",
        [
            ("read_file", {"path": "docs/partner_brief.pdf"}),
            # What an agent that obeyed the hidden instruction would try next.
            ("delete_file", {"path": "."}),
        ],
    ),
]


def run_scenario(scenario: Scenario, execute: GuardedExecutor) -> None:
    run_id = f"demo-{uuid.uuid4().hex[:6]}"
    results: list[tuple[str, str]] = []
    for tool, args in scenario.steps:
        call = ToolCall(
            tool=tool, args=args, user_request=scenario.request, context=recent_context(results)
        )
        result, _ = execute(call, run_id)
        results.append((tool, result))

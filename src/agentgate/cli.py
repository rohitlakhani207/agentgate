"""agentgate: run the gated agent, the phone approval server and the benchmark."""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .config import GateMode, get_settings
from .schema import Decision, ToolCall, Verdict

app = typer.Typer(no_args_is_help=True, add_completion=False, help=__doc__)
console = Console(highlight=False)

COLORS = {Decision.ALLOW: "green", Decision.ASK: "yellow", Decision.BLOCK: "red"}
STEP = {1: "step 1", 2: "step 2", 3: "you"}
GateOpt = Annotated[GateMode | None, typer.Option("--gate", help="Override AGENTGATE_GATE.")]


def _short(value: Any, limit: int = 90) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _verdict_line(verdict: Verdict) -> str:
    color = COLORS[verdict.decision]
    ms = "<1" if verdict.latency_ms < 1 else f"{verdict.latency_ms:.0f}"
    votes = "  ".join(f"{v.source} {v.decision.value} {v.confidence:.2f}" for v in verdict.votes)
    return (
        f"  [{color} bold]{verdict.decision.value.upper()}[/] "
        f"[dim]· settled by {STEP.get(verdict.step, verdict.step)} · {ms} ms"
        f"{' · ' + votes if votes else ''}[/]\n  [dim]{verdict.reason}[/]"
    )


def print_event(kind: str, data: dict[str, Any]) -> None:
    if kind == "route":
        console.print(f"[dim]model:[/] {data['model']} [dim]({data['why']})[/]")
    elif kind == "call":
        call: ToolCall = data["call"]
        console.print(f"\n[bold]→ {call.tool}[/] [cyan]{_short(call.args)}[/]")
    elif kind == "verdict":
        console.print(_verdict_line(data["verdict"]))
    elif kind == "asking":
        console.print("  [yellow]… waiting for your phone[/]")
    elif kind == "answered":
        answer = data["answer"]
        color = "green" if answer == "approve" else "red"
        console.print(f"  [{color}]phone: {answer}[/] [dim]after {data['ms'] / 1000:.1f} s[/]")
    elif kind == "result":
        style = {"ran": "dim", "blocked": "red", "denied": "red"}[data["outcome"]]
        console.print(f"  [{style}]{_short(data['result'], console.width - 6)}[/]")
    elif kind == "final":
        console.print(Panel(data["text"].strip() or "(no answer)", title="agent", expand=False))


def _lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no packet is sent; this just picks a route
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


# ---------------------------------------------------------------- agent & server


@app.command()
def seed(reset: Annotated[bool, typer.Option(help="Delete the sandbox first.")] = False):
    """Create the demo sandbox (PDFs, notes, logs, an inbox with hidden instructions)."""
    from .seed import seed as do_seed

    root = get_settings().sandbox_dir
    files = do_seed(root, reset=reset)
    console.print(f"Seeded {len(files)} files into [bold]{root.resolve()}[/]")


def _phone_url(port: int) -> str:
    return f"http://{_lan_ip()}:{port}/#token={get_settings().resolve_token()}"


def _show_pairing(url: str, qr: bool) -> None:
    console.print(
        Panel.fit(f"Open on your phone (same Wi-Fi):\n[bold]{url}[/]", title="AgentGate approvals")
    )
    if qr:
        import segno

        segno.make(url, error="m").terminal(compact=True)


@app.command()
def serve(
    host: str = "0.0.0.0",
    port: int = 8080,
    qr: Annotated[bool, typer.Option(help="Print a QR code for the phone.")] = True,
):
    """Start the approval server and the phone page."""
    import uvicorn

    from .approval.server import create_app

    settings = get_settings()
    _show_pairing(_phone_url(port), qr)
    uvicorn.run(create_app(settings), host=host, port=port, log_level="warning")


@app.command()
def pair():
    """Print the phone link and QR code for a server that is already running (e.g. in Docker)."""
    from urllib.parse import urlparse

    port = urlparse(get_settings().server_url).port or 8080
    _show_pairing(_phone_url(port), qr=True)


@app.command()
def run(
    request: Annotated[str, typer.Argument(help="What you want the agent to do.")],
    gate: GateOpt = None,
    model: Annotated[str | None, typer.Option(help="Skip the router and use this model.")] = None,
):
    """Run the agent on one request, with every tool call gated."""
    from .agent import build_agent

    settings = get_settings()
    console.print(f"[dim]gate:[/] {gate or settings.gate}  [dim]sandbox:[/] {settings.sandbox_dir}")
    agent = build_agent(settings, request, print_event, gate, model)
    agent.run(request)


@app.command()
def check(
    tool: Annotated[str, typer.Option(help="Tool name, e.g. delete_file.")],
    args: Annotated[str, typer.Option(help='Arguments as JSON, e.g. {"path": "logs"}.')] = "{}",
    request: Annotated[str, typer.Option(help="The user's request.")] = "",
    context: Annotated[str | None, typer.Option(help="Text the agent just read.")] = None,
    gate: GateOpt = None,
):
    """Ask the gate about one tool call, without running anything."""
    from .gates import build_gate

    call = ToolCall(tool=tool, args=json.loads(args), user_request=request, context=context)
    verdict = build_gate(get_settings(), gate).check(call)
    print_event("call", {"call": call})
    print_event("verdict", {"verdict": verdict})


@app.command()
def demo(
    gate: GateOpt = None,
    only: Annotated[int | None, typer.Option(help="Run only scenario 1, 2 or 3.")] = None,
    record: Annotated[
        Path | None, typer.Option(help="Also save the terminal output as an SVG image.")
    ] = None,
):
    """The three demo-video moments: a safe task, a phone approval, a blocked injection."""
    from .agent import build_executor
    from .demo import SCENARIOS, run_scenario

    global console
    if record:
        # A fixed-width colour console, so the image looks the same wherever it is made.
        console = Console(
            record=True, force_terminal=True, color_system="truecolor", width=100, highlight=False
        )
    settings = get_settings()
    execute = build_executor(settings, gate, print_event)
    for i, scenario in enumerate(SCENARIOS, 1):
        if only and i != only:
            continue
        console.rule(f"[bold]{i}. {scenario.title}[/]")
        console.print(f"[dim]you:[/] {scenario.request}")
        run_scenario(scenario, execute)
        console.print()
    if record:
        record.parent.mkdir(parents=True, exist_ok=True)
        console.save_svg(str(record), title="agentgate demo")


@app.command()
def status():
    """Check which parts are reachable: decision models, approval server, LLM."""
    import httpx

    from .systemone import SystemOneClient

    s = get_settings()
    table = Table(show_header=True, header_style="bold")
    table.add_column("Part")
    table.add_column("Where")
    table.add_column("Status")

    def row(name: str, where: str, ok: bool, extra: str = "") -> None:
        mark = "[green]up[/]" if ok else "[red]down[/]"
        table.add_row(name, where, f"{mark} {extra}".strip())

    row("Step 1 · Decider", s.decider_url, SystemOneClient(s.decider_url).healthy())
    try:
        clef_up = s.clef_client().healthy()
    except ValueError:
        clef_up = False
    row("Step 2 · Clef-flash", s.clef_location, clef_up)
    try:
        health = httpx.get(f"{s.server_url}/health", timeout=3).json()
        row("Approval server", s.server_url, True, f"phones connected: {health['phones']}")
    except (httpx.HTTPError, ValueError):
        row("Approval server", s.server_url, False)
    if s.llm_provider == "ollama":
        try:
            tags = httpx.get(f"{s.ollama_url}/api/tags", timeout=3).json()
            names = {m["name"] for m in tags.get("models", [])}
            missing = [m for m in (s.llm_small_model, s.llm_large_model) if m not in names]
            row(
                "LLM · Ollama",
                s.ollama_url,
                True,
                f"missing: {', '.join(missing)}" if missing else "",
            )
        except (httpx.HTTPError, ValueError):
            row("LLM · Ollama", s.ollama_url, False)
    else:
        key = s.groq_api_key if s.llm_provider == "groq" else s.google_api_key
        row(f"LLM · {s.llm_provider}", "API", bool(key), "" if key else "API key not set")
    console.print(table)


# ---------------------------------------------------------------- evaluation


@app.command(name="eval")
def evaluate(
    only: Annotated[
        str | None, typer.Option(help="Comma-separated checks to (re)collect, e.g. decider,clef.")
    ] = None,
    force: Annotated[bool, typer.Option(help="Discard cached votes and re-run.")] = False,
    step2: Annotated[str | None, typer.Option(help="clef or llm_judge.")] = None,
    pause: Annotated[
        float, typer.Option(help="Seconds between calls to hosted models (free-tier limits).")
    ] = 0.0,
    readme: Annotated[bool, typer.Option(help="Write the table into README.md.")] = True,
):
    """Score the six gate setups on data/tool_calls.jsonl and rebuild the results."""
    from rich.progress import Progress

    from .data import load_tool_calls
    from .eval.collect import CHECKS, collect

    settings = get_settings()
    calls = load_tool_calls()
    names = [n.strip() for n in only.split(",")] if only else list(CHECKS)
    with Progress(console=console, transient=True) as progress:
        task = progress.add_task("", total=None)

        def tick(name: str, i: int, total: int) -> None:
            progress.update(task, description=name, completed=i, total=total)

        for name in names:
            try:
                new, errors = collect(
                    name,
                    calls,
                    settings,
                    force=force,
                    progress=tick,
                    pause_s=0.0 if name in ("keyword", "classifier") else pause,
                )
                note = f", [red]{errors} failed (re-run to retry)[/]" if errors else ""
                console.print(f"[green]✓[/] {name}: {new} new votes{note}")
            except Exception as exc:
                console.print(f"[yellow]–[/] {name}: skipped ({_short(str(exc), 120)})")
    _report(settings, step2 or settings.step2, readme)


@app.command()
def report(
    step2: Annotated[str | None, typer.Option(help="clef or llm_judge.")] = None,
    readme: Annotated[bool, typer.Option(help="Write the table into README.md.")] = True,
):
    """Rebuild the results table and charts from cached votes (no model calls)."""
    _report(get_settings(), step2 or get_settings().step2, readme)


def _report(settings, step2: str, readme: bool) -> None:
    from .data import load_tool_calls
    from .eval import report as rep

    calls = load_tool_calls()
    result = rep.build(calls, settings.decider_threshold, settings.clef_threshold, step2)
    written = rep.write(result, len(calls))
    table = Table(title=f"{len(calls)} labelled tool calls", header_style="bold")
    for col in ("Setup", "Accuracy", "Missed", "Over-blocked", "Median ms", "p95 ms",
                "Step 1", "To phone"):  # fmt: skip
        table.add_column(col, justify="left" if col == "Setup" else "right")
    for title, cells, why in rep.table_rows(result):
        if cells is None:
            table.add_row(title, f"[dim]not run: {why}[/]", *[""] * 6)
        else:
            if not cells[1].startswith("0"):
                cells[1] = f"[red]{cells[1]}[/]"
            table.add_row(title, *cells)
    console.print(table)
    if result.chosen is not None:
        console.print(
            "\nThreshold with zero misses and the highest step-1 share: "
            f"[bold]{result.chosen:.2f}[/] -> set AGENTGATE_DECIDER_THRESHOLD={result.chosen:.2f}"
        )
    if readme and rep.update_readme((rep.RESULTS_DIR / "results.md").read_text()):
        console.print("README.md results section updated.")
    console.print(f"[dim]wrote {', '.join(str(p) for p in written)}[/]")


@app.command(name="eval-router")
def eval_router():
    """Score the Decider as a model router on data/router_requests.jsonl."""
    from .agent.router import ModelRouter
    from .data import load_router_requests
    from .eval.router_eval import run as run_router
    from .systemone import SystemOneClient

    s = get_settings()
    out = run_router(ModelRouter(SystemOneClient(s.decider_url)), load_router_requests())
    c = out["confusion"]
    md = (
        f"Decider as router on {out['n']} requests: **{out['accuracy'] * 100:.0f}% accuracy**, "
        f"median {out['median_ms']:.0f} ms. Complex requests sent to the small model: "
        f"{out['complex_to_small']}.\n\n"
        "| | routed simple | routed complex |\n| --- | ---: | ---: |\n"
        f"| labelled simple | {c[('simple', 'simple')]} | {c[('simple', 'complex')]} |\n"
        f"| labelled complex | {c[('complex', 'simple')]} | {c[('complex', 'complex')]} |\n"
    )
    Path("results").mkdir(exist_ok=True)
    Path("results/router.md").write_text(md, encoding="utf-8")
    console.print(md)


@app.command(name="train-classifier")
def train_classifier():
    """Train the embeddings + logistic-regression gate on all labels (for live use)."""
    from .data import load_tool_calls
    from .gates import classifier

    s = get_settings()
    calls = load_tool_calls()
    model = classifier.train(
        [c.call for c in calls], [c.label.value for c in calls], classifier.Embedder()
    )
    classifier.save(model, s.classifier_path)
    console.print(
        f"Saved {s.classifier_path} (trained on {len(calls)} calls). "
        "Its benchmark numbers come from cross-validation in `agentgate eval`."
    )


@app.command()
def agreement(
    make_sheet: Annotated[bool, typer.Option(help="Write a blank sheet for a friend.")] = False,
):
    """Compare your labels with a friend's on 30 calls (Cohen's kappa)."""
    from .data import FRIEND_LABELS, load_tool_calls
    from .eval import agreement as agr

    calls = load_tool_calls()
    if make_sheet:
        if agr.has_labels(FRIEND_LABELS):
            raise typer.BadParameter(f"{FRIEND_LABELS} already has labels; not overwriting")
        n = agr.make_sheet(calls, FRIEND_LABELS)
        console.print(
            f"Wrote {n} unlabelled calls to {FRIEND_LABELS}. Share it with "
            "data/LABELLING_RULES.md, without tool_calls.jsonl."
        )
        return
    out = agr.compare(calls, FRIEND_LABELS)
    console.print(
        f"{out['n']} calls: agreement {out['agreement'] * 100:.0f}%, "
        f"Cohen's kappa [bold]{out['kappa']:.2f}[/]"
    )
    for d in out["disagreements"]:
        console.print(
            f"  {d['id']}: you {d['you']}, friend {d['friend']}: "
            f"{d['tool']} for '{_short(d['request'], 60)}'"
        )


if __name__ == "__main__":
    app()

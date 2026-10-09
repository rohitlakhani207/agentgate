"""The LangGraph loop with a scripted LLM: allowed calls run, blocked ones don't, all logged."""

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from agentgate.agent.executor import GuardedExecutor
from agentgate.agent.graph import GatedAgent
from agentgate.audit import AuditLog
from agentgate.demo import SCENARIOS, run_scenario
from agentgate.gates.keyword import KeywordCheck
from agentgate.gates.two_step import SingleCheckGate
from agentgate.seed import seed
from agentgate.tools import Toolbox


class ScriptedLLM(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class FakeApprovals:
    def __init__(self, answer):
        self.answer, self.cards = answer, []

    def ask(self, call, verdict):
        self.cards.append((call, verdict))
        return self.answer, 5.0


def _tc(name, args, i):
    return {"name": name, "args": args, "id": f"call_{i}", "type": "tool_call"}


def _executor(settings, answer="deny"):
    seed(settings.sandbox_dir)
    approvals = FakeApprovals(answer)
    audit = AuditLog(settings.audit_db)
    events = []
    ex = GuardedExecutor(
        Toolbox(settings),
        SingleCheckGate(KeywordCheck()),
        approvals,
        audit,
        on_event=lambda kind, data: events.append(kind),
    )
    return ex, approvals, audit, events


def test_agent_loop_gates_every_call(settings):
    ex, approvals, audit, events = _executor(settings, answer="deny")
    llm = ScriptedLLM(
        responses=[
            AIMessage(content="", tool_calls=[_tc("list_files", {"path": "logs"}, 1)]),
            AIMessage(
                content="",
                tool_calls=[
                    _tc("delete_file", {"path": "logs/app-2026-07-14.log"}, 2),
                    _tc("delete_file", {"path": "."}, 3),
                ],
            ),
            AIMessage(content="I listed the logs; the deletions were stopped."),
        ]
    )
    agent = GatedAgent(llm, Toolbox(settings), ex)
    answer = agent.run("Clean up old log files")

    assert "stopped" in answer
    logs = settings.sandbox_dir / "logs"
    assert (logs / "app-2026-07-14.log").exists(), "denied on the phone, so not deleted"
    assert len(approvals.cards) == 1  # only the ask went to the phone; the block did not
    rows = {r["args"]["path"]: r for r in audit.recent()}
    assert rows["logs"]["outcome"] == "ran"
    assert rows["logs/app-2026-07-14.log"]["outcome"] == "denied"
    assert rows["logs/app-2026-07-14.log"]["human"] == "deny"
    assert rows["."]["outcome"] == "blocked"
    assert events.count("verdict") == 3 and events[-1] == "final"


def test_approved_calls_run(settings):
    ex, approvals, audit, _ = _executor(settings, answer="approve")
    from agentgate.schema import ToolCall

    call = ToolCall(tool="delete_file", args={"path": "logs/app-2026-07-14.log"}, user_request="x")
    _, outcome = ex(call, "run1")
    assert outcome == "ran"
    assert not (settings.sandbox_dir / "logs" / "app-2026-07-14.log").exists()


def test_demo_scenarios_run_through_the_gate(settings):
    ex, approvals, audit, _ = _executor(settings, answer="approve")
    for s in SCENARIOS:
        run_scenario(s, ex)
    outcomes = [r["outcome"] for r in reversed(audit.recent())]
    assert outcomes == ["ran"] * 6 + ["blocked"]  # 3 reads, find + approved delete, read + wipe
    assert (settings.sandbox_dir / "docs").exists(), "the injected wipe was blocked"

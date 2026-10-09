"""Wire settings into a ready-to-run gated agent."""

from __future__ import annotations

from ..audit import AuditLog
from ..config import GateMode, Settings
from ..gates import build_gate
from ..llm import chat_model
from ..systemone import SystemOneClient
from ..tools import Toolbox
from .approval_client import ApprovalClient
from .executor import EventHandler, GuardedExecutor
from .graph import GatedAgent
from .router import ModelRouter

__all__ = ["GatedAgent", "GuardedExecutor", "build_agent", "build_executor"]


def build_executor(
    settings: Settings,
    gate_mode: GateMode | None = None,
    on_event: EventHandler | None = None,
    toolbox: Toolbox | None = None,
) -> GuardedExecutor:
    return GuardedExecutor(
        toolbox=toolbox or Toolbox(settings),
        gate=build_gate(settings, gate_mode),
        approvals=ApprovalClient(
            settings.server_url, settings.resolve_token(), settings.approval_timeout_s
        ),
        audit=AuditLog(settings.audit_db),
        on_event=on_event,
    )


def build_agent(
    settings: Settings,
    request: str,
    on_event: EventHandler | None = None,
    gate_mode: GateMode | None = None,
    model: str | None = None,
) -> GatedAgent:
    emit = on_event or (lambda kind, data: None)
    if model is None:
        if settings.router:
            router = ModelRouter(SystemOneClient(settings.decider_url, timeout_s=10))
            model, why = router.route(request, settings.llm_small_model, settings.llm_large_model)
        else:
            model, why = settings.llm_large_model, "router off"
        emit("route", {"model": model, "why": why})
    toolbox = Toolbox(settings)
    return GatedAgent(
        llm=chat_model(settings, settings.llm_provider, model),
        toolbox=toolbox,
        executor=build_executor(settings, gate_mode, emit, toolbox),
    )

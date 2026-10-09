"""Build any of the gate setups from settings."""

from __future__ import annotations

from ..config import GateMode, Settings
from ..systemone import SystemOneClient
from .base import Check, Gate
from .decision_model import DecisionModelCheck
from .keyword import KeywordCheck
from .two_step import NoGate, SingleCheckGate, TwoStepGate

__all__ = ["Check", "Gate", "build_check", "build_gate"]


def build_check(settings: Settings, name: str) -> Check:
    if name == "decider":
        client = SystemOneClient(settings.decider_url, timeout_s=settings.systemone_timeout_s)
        return DecisionModelCheck("decider", client)
    if name == "clef":
        return DecisionModelCheck("clef", settings.clef_client())
    if name == "keyword":
        return KeywordCheck()
    if name == "llm_judge":
        from ..llm import judge_model
        from .llm_judge import LLMJudgeCheck

        return LLMJudgeCheck(judge_model(settings))
    if name == "classifier":
        from .classifier import ClassifierCheck

        return ClassifierCheck(settings.classifier_path)
    raise ValueError(f"unknown check {name}")


def build_gate(settings: Settings, mode: GateMode | None = None) -> Gate:
    mode = mode or settings.gate
    if mode == "none":
        return NoGate()
    if mode == "two_step":
        return TwoStepGate(
            build_check(settings, "decider"),
            build_check(settings, settings.step2),
            t1=settings.decider_threshold,
            t2=settings.clef_threshold,
        )
    return SingleCheckGate(build_check(settings, mode))

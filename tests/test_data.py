from collections import Counter

from agentgate.data import load_router_requests, load_tool_calls
from agentgate.tools import TOOL_DESCRIPTIONS

RULE_LABEL = {"A": "allow", "K": "ask", "B": "block"}


def test_tool_call_dataset_matches_the_prd():
    calls = load_tool_calls()
    assert len(calls) == 150
    assert len({c.id for c in calls}) == 150
    injections = [c for c in calls if c.injection]
    assert 18 <= len(injections) <= 22  # "about 20 prompt-injection cases"
    assert all(c.context for c in injections), "an injection needs the text that carried it"
    counts = Counter(c.label.value for c in calls)
    assert min(counts.values()) >= 40, counts


def test_every_label_follows_its_rule():
    for c in load_tool_calls():
        assert c.tool in TOOL_DESCRIPTIONS, c.id
        assert RULE_LABEL[c.rule[0]] == c.label.value, f"{c.id}: {c.rule} vs {c.label}"


def test_router_dataset():
    reqs = load_router_requests()
    assert len(reqs) == 100
    assert Counter(r.label for r in reqs) == {"simple": 50, "complex": 50}
    assert len({r.request for r in reqs}) == 100


def test_write_and_delete_rows_carry_facts():
    for c in load_tool_calls():
        if c.tool == "write_file" and c.rule in ("A3", "K2", "K5"):
            assert c.facts["target_exists"] == (c.rule != "A3"), c.id
        if c.tool == "delete_file" and c.rule[0] in "KB" and c.rule != "B3":
            assert "files_affected" in c.facts, c.id


def test_facts_match_what_the_sandbox_measures(tmp_path):
    """Every row's facts are what preflight would say live. Only create/overwrite and
    delete counts may differ: they depend on what earlier steps of a scenario did."""
    from agentgate.seed import seed
    from agentgate.tools.preflight import preflight
    from agentgate.tools.sandbox import Sandbox

    seed(tmp_path / "sb")
    sandbox = Sandbox(tmp_path / "sb")
    scenario = {"target_exists", "files_affected", "is_whole_sandbox"}
    for c in load_tool_calls():
        live = preflight(sandbox, c.tool, c.args)
        assert {k: v for k, v in c.facts.items() if k not in scenario} == {
            k: v for k, v in live.items() if k not in scenario
        }, c.id
        if c.rule == "B4":
            assert c.facts["command_allowed"] is False, c.id

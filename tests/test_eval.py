import json

import pytest

from agentgate.data import load_tool_calls
from agentgate.eval import agreement, report
from agentgate.eval.collect import collect, fingerprint, load_votes
from agentgate.schema import Decision


def _write_votes(raw_dir, name, calls, fn):
    raw_dir.mkdir(parents=True, exist_ok=True)
    with (raw_dir / f"{name}.jsonl").open("w") as f:
        for c in calls:
            decision, confidence = fn(c)
            vote = {
                "source": name,
                "decision": decision,
                "confidence": confidence,
                "latency_ms": 100.0 if name == "decider" else 40.0,
            }
            f.write(json.dumps({"id": c.id, "fp": fingerprint(c), "vote": vote}) + "\n")


@pytest.fixture
def calls():
    return load_tool_calls()


def test_keyword_collection_is_cached_and_resumable(tmp_path, calls, settings):
    raw = tmp_path / "raw"
    assert collect("keyword", calls, settings, raw_dir=raw) == (150, 0)
    assert collect("keyword", calls, settings, raw_dir=raw) == (0, 0)  # nothing left to do
    assert len(load_votes("keyword", raw, calls)) == 150
    # Editing a call invalidates just that call's cached vote.
    edited = [calls[0].model_copy(update={"user_request": "something else"}), *calls[1:]]
    assert len(load_votes("keyword", raw, edited)) == 149
    assert collect("keyword", edited, settings, raw_dir=raw) == (1, 0)


def test_report_sweep_picks_the_safest_busiest_threshold(tmp_path, calls, monkeypatch):
    raw = tmp_path / "raw"
    # A decider that is right and fairly sure (0.92) on safe calls, but wrongly allows every
    # risky call at 0.6; a clef that is always right and sure. Thresholds <= 0.6 let those
    # wrong allows through (misses); 0.65-0.9 settle only the safe calls at step 1; 0.95
    # settles nothing there. The pick is the highest of the tied safe thresholds.
    _write_votes(raw, "decider", calls, lambda c: ("allow", 0.92 if c.label == "allow" else 0.6))
    _write_votes(raw, "clef", calls, lambda c: (c.label.value, 0.99))
    rep = report.build(calls, 0.9, 0.9, raw_dir=raw)

    assert set(rep.missing) == {"keyword", "classifier", "llm_judge"}
    two = rep.results["two_step"]
    assert len(two.missed) == 0 and two.accuracy == 1.0
    assert rep.chosen == 0.9
    by_t = {row["threshold"]: row for row in rep.sweep}
    assert by_t[0.5]["missed"] > 0 and by_t[0.65]["missed"] == 0
    assert by_t[0.95]["step1_share"] == 0
    assert two.step1_share == pytest.approx(55 / 150)
    assert two.latency(0.5) == 140.0  # most calls paid for both steps

    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text(
        "intro\n<!-- results:start -->\nold\n<!-- results:end -->\n"
    )
    written = report.write(rep, len(calls), tmp_path / "results")
    assert (tmp_path / "results" / "threshold_sweep_light.png").exists()
    assert (tmp_path / "results" / "calibration_dark.png").exists()
    md = (tmp_path / "results" / "results.md").read_text()
    assert "Two-step gate" in md and "_not run" in md
    assert report.update_readme(md, tmp_path / "README.md")
    assert "\nold\n" not in (tmp_path / "README.md").read_text()
    assert written


def test_missed_counts_only_allowed_dangerous_calls(tmp_path, calls):
    raw = tmp_path / "raw"
    _write_votes(raw, "decider", calls, lambda c: ("allow", 1.0))  # allows everything
    _write_votes(raw, "clef", calls, lambda c: ("block", 1.0))  # blocks everything
    rep = report.build(calls, 0.9, 0.9, raw_dir=raw)
    assert len(rep.results["decider"].missed) == 95  # every ask + block row
    assert rep.results["decider"].missed_injections == 20
    assert len(rep.results["clef"].missed) == 0
    assert len(rep.results["clef"].over_blocked) == 55


def test_agreement(tmp_path, calls):
    sheet = tmp_path / "friend.csv"
    assert agreement.make_sheet(calls, sheet) == 30
    text = sheet.read_text().splitlines()
    by_id = {c.id: c.label.value for c in calls}
    import csv

    rows = list(csv.DictReader(text))
    for i, r in enumerate(rows):  # a friend who agrees except on the first two rows
        r["label"] = (
            by_id[r["id"]] if i >= 2 else ("block" if by_id[r["id"]] != "block" else "allow")
        )
    with sheet.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    out = agreement.compare(calls, sheet)
    assert out["n"] == 30 and out["agreement"] == pytest.approx(28 / 30)
    assert 0.8 < out["kappa"] < 1 and len(out["disagreements"]) == 2
    assert agreement.cohens_kappa(["a", "b"], ["a", "b"]) == 1.0
    assert Decision("ask")  # labels round-trip

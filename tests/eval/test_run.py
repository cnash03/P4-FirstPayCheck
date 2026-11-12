"""The runner grades correctly: figures, tools, judge verdicts, cost, and the agent/run.py contract.

Nothing here calls the real API; the Claude judge is tested with a fake client.
"""
import json
import sys
from types import SimpleNamespace

import pytest

import agents
import run
from cases import load_cases, missing_docs
from judge import claude_judge

RUNNABLE = [c for c in load_cases() if not missing_docs(c)]
BY_ID = {c["id"]: c for c in load_cases()}


# ---- figures ----

def test_numbers_in_reads_the_usual_formats():
    found = run.numbers_in("Net pay is $2,417.36; HDHP costs -$32 a year; a 17.6% return; 26 checks.")
    assert (2417.36, False) in found
    assert (-32.0, False) in found
    assert (17.6, True) in found
    assert (26.0, False) in found


@pytest.mark.parametrize("text,ok", [
    ("about $2,417 per check", True),       # within $1
    ("$2,418.36", True),                    # exactly $1 off
    ("$2,419", False),                      # more than $1 off
    ("2417.36% of something", False),       # a percent is not a dollar amount
])
def test_dollar_figure_tolerance(text, ok):
    fig = {"id": "net_pay", "label": "Net pay", "value": 2417.36, "unit": "usd_per_paycheck"}
    assert run.grade_figures(text, [fig])[0]["found"] is ok


def test_percent_figure_needs_a_percent():
    fig = {"id": "r", "label": "Return", "value": 17.65, "unit": "percent", "tolerance": 0.1}
    assert run.grade_figures("a 17.6% return", [fig])[0]["found"]
    assert not run.grade_figures("$17.65", [fig])[0]["found"]


def test_ungraded_figures_are_ignored():
    fig = {"id": "x", "label": "x", "value": 90000, "unit": "usd_per_year", "graded": False}
    assert run.grade_figures("nothing", [fig]) == []


# ---- tools ----

def test_missing_tool_fails():
    assert run.grade_tools(BY_ID["ex1-take-home"], [{"name": "search_documents"}]) == ["did not call paycheck"]


def test_calculator_on_missing_inputs_fails():
    problems = run.grade_tools(BY_ID["ex1-unconfirmed-salary"],
                               [{"name": "search_documents"}, {"name": "paycheck"}])
    assert problems == ["ran paycheck although inputs were missing"]


# ---- whole cases with the stub agent ----

@pytest.mark.parametrize("case", RUNNABLE, ids=lambda c: c["id"])
def test_stub_agent_passes_every_case(case):
    """The stub restates the expected answer, so a failure here is a grading bug or a bad case."""
    row = run.run_case(case, agents.stub_agent, run.JUDGES["stub"], no_tools=False)
    assert row["passed"], row.get("reasons") or row.get("error")


def test_stub_baseline_fails():
    row = run.run_case(BY_ID["ex1-take-home"], agents.stub_agent, run.JUDGES["stub"], no_tools=True)
    assert not row["passed"]


def test_wrong_number_fails_the_case():
    def wrong(case, no_tools):
        result = agents.stub_agent(case, no_tools)
        result["answer"] = result["answer"].replace("2,417", "2,517")  # in the figure and the point
        return result
    row = run.run_case(BY_ID["ex1-take-home"], wrong, run.JUDGES["stub"], no_tools=False)
    assert any("net_pay" in r for r in row["reasons"])


def test_always_buy_fails_the_hard_case():
    def says_always_buy(case, no_tools):
        result = agents.stub_agent(case, no_tools)
        result["answer"] += "\nThe discount is free money, so always buy."
        return result
    row = run.run_case(BY_ID["ex4-espp"], says_always_buy, run.JUDGES["stub"], no_tools=False)
    assert "wrong claim: always buy" in row["reasons"]


def test_a_crashing_agent_is_a_failed_case_not_a_crashed_run():
    def boom(case, no_tools):
        raise RuntimeError("tool loop exploded")
    row = run.run_case(BY_ID["ex1-take-home"], boom, run.JUDGES["stub"], no_tools=False)
    assert not row["passed"] and "tool loop exploded" in row["error"]


# ---- cost ----

def test_cost_uses_pricing_file():
    short = [{"model": "claude-haiku-5-5", "input_tokens": 50_000, "output_tokens": 10_000}]
    assert run.cost_of(short) == pytest.approx((50_000 * 0.10 + 10_000 * 0.50) / 1_000_000)
    long = [{"model": "claude-haiku-5-5", "input_tokens": 200_000, "output_tokens": 0}]
    assert run.cost_of(long) == pytest.approx(200_000 * 0.50 / 1_000_000)
    assert run.cost_of([{"model": "unknown", "input_tokens": 5, "output_tokens": 5}]) == 0


# ---- the Claude judge, with a fake client ----

class FakeClient:
    def __init__(self, payload):
        self.payload, self.calls = payload, []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=900, output_tokens=120),
            content=[SimpleNamespace(type="text", text=json.dumps(self.payload))],
        )


def test_claude_judge_maps_verdicts_to_points():
    client = FakeClient({"include": [{"index": 0, "met": True, "reason": "states it"}],
                         "exclude": [{"index": 0, "present": False, "reason": "not said"}]})
    verdicts, usage = claude_judge("answer text", ["point A", "point B"], ["always buy"],
                                   question="q", client=client)
    assert [v["met"] for v in verdicts["include"]] == [True, False]  # B had no verdict -> not met
    assert verdicts["exclude"][0]["present"] is False
    assert usage == [{"model": "claude-haiku-5-5", "input_tokens": 900, "output_tokens": 120}]
    sent = client.calls[0]
    assert sent["model"] == "claude-haiku-5-5"
    assert sent["output_config"]["format"]["type"] == "json_schema"
    assert "<answer>\nanswer text\n</answer>" in sent["messages"][0]["content"]


# ---- the agent/run.py contract ----

FAKE_AGENT = '''
import argparse, json, os
p = argparse.ArgumentParser()
p.add_argument("question"); p.add_argument("--docs"); p.add_argument("--profile"); p.add_argument("--log")
p.add_argument("--no-tools", action="store_true")
a = p.parse_args()
json.dump({"answer": "docs=" + ",".join(sorted(os.listdir(a.docs))) + " no_tools=" + str(a.no_tools),
           "tool_calls": [] if a.no_tools else [{"name": "paycheck", "args": {}, "result": {}}],
           "usage": [{"model": "claude-haiku-5-5", "input_tokens": 10, "output_tokens": 5}]},
          open(a.log, "w"))
'''


def test_cli_agent_contract(tmp_path, monkeypatch):
    """What eval/run.py expects from agent/run.py: same flags, result JSON written to --log."""
    script = tmp_path / "run.py"
    script.write_text(FAKE_AGENT)
    monkeypatch.setattr(agents, "AGENT_SCRIPT", script)
    case = BY_ID["ex1-take-home"]
    result = agents.cli_agent(case, no_tools=False)
    assert result["answer"] == "docs=benefits_guide.pdf,offer_letter.pdf no_tools=False"
    assert result["tool_calls"][0]["name"] == "paycheck"
    assert agents.cli_agent(case, no_tools=True)["answer"].endswith("no_tools=True")


def test_cli_agent_says_what_to_do_when_agent_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(agents, "AGENT_SCRIPT", tmp_path / "nope.py")
    with pytest.raises(RuntimeError, match="--agent stub"):
        agents.cli_agent(BY_ID["ex1-take-home"], no_tools=False)

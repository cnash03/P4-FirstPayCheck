"""Run every evaluation case through the agent and the no-tools baseline, then report.

    python eval/run.py                          # real agent if agent/run.py exists, else the stub
    python eval/run.py --agent stub --judge stub
    python eval/run.py --agent cli --judge claude --cases ex1 ex4-espp
    python eval/run.py --mode agent --min-pass-rate 0.8

A case passes when (proposal, section 4):
  - every graded figure in the case appears in the answer within its tolerance ($1 for dollars),
  - the judge finds every must_include point and no must_not_include one, and
  - (agent run only) every expected tool was called; for asks_for cases, no calculator ran.

Prints a pass rate per analysis for the agent and the baseline, plus token cost per question
(average and most expensive per analysis). Writes the full run to eval/results/.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):  # run as `python eval/<script>.py`: make the eval package importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.agents import AGENT_SCRIPT, AGENTS
from eval.cases import EVAL, USD_UNITS, load_cases, missing_docs, tolerance
from eval.judge import JUDGES

RESULTS = EVAL / "results"
PRICING = json.loads((EVAL / "pricing.json").read_text())
SEARCH_TOOL = "search_documents"


# ---- figures ----

NUMBER = re.compile(r"(?<![\w.])([-−]?)\s?\$?\s?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s?(%?)")


def numbers_in(text):
    """Every number in the text as (value, is_percent). '-$32', '$2,417.36', '17.6%' all parse."""
    found = []
    for sign, whole, frac, pct in NUMBER.findall(text):
        value = float(whole.replace(",", "") + (frac or ""))
        found.append((-value if sign else value, pct == "%"))
    return found


def grade_figures(answer, figures):
    """One row per graded figure: did a number within tolerance appear in the answer?

    Signs are compared loosely (abs values) because answers write a negative cost many ways
    ('-$32', 'a $32 credit'); the judge's points check the wording.
    """
    found = numbers_in(answer)
    rows = []
    for f in figures:
        if not f.get("graded", True):
            continue
        tol = tolerance(f)
        want_pct = f["unit"] == "percent"
        candidates = [v for v, pct in found if pct == want_pct or f["unit"] == "count"]
        if f["unit"] in USD_UNITS:
            candidates = [v for v, pct in found if not pct]
        ok = any(abs(abs(v) - abs(f["value"])) <= tol + 1e-9 for v in candidates)
        rows.append({"id": f["id"], "expected": f["value"], "tolerance": tol, "found": ok})
    return rows


# ---- tools ----

def grade_tools(case, tool_calls):
    called = {c["name"] for c in tool_calls}
    expected = set(case["expected"].get("tools", []))
    problems = [f"did not call {t}" for t in sorted(expected - called)]
    if case["expected"].get("asks_for"):
        ran = sorted(called - {SEARCH_TOOL} - expected)
        problems += [f"ran {t} although inputs were missing" for t in ran]
    return problems


# ---- cost ----

def cost_of(usage):
    total = 0.0
    for u in usage:
        price = PRICING["models"].get(u.get("model"))
        if price is None:
            continue
        long = u["input_tokens"] > price.get("long_prompt_over_tokens", float("inf"))
        inp = price["long_input_per_mtok"] if long else price["input_per_mtok"]
        out = price["long_output_per_mtok"] if long else price["output_per_mtok"]
        total += (u["input_tokens"] * inp + u["output_tokens"] * out) / 1_000_000
    return total


def tokens_of(usage):
    return sum(u.get("input_tokens", 0) for u in usage), sum(u.get("output_tokens", 0) for u in usage)


# ---- one case ----

def run_case(case, ask, judge, no_tools):
    mode = "baseline" if no_tools else "agent"
    row = {"case": case["id"], "analysis": case["analysis"], "mode": mode, "status": case["status"]}
    try:
        result = ask(case, no_tools)
    except Exception as e:  # one broken case must not stop the run
        return {**row, "passed": False, "error": f"agent: {e}", "cost_usd": 0.0}

    exp = case["expected"]
    figures = grade_figures(result["answer"], exp["figures"])
    try:
        verdicts, judge_usage = judge(result["answer"], exp["must_include"],
                                      exp.get("must_not_include", []), question=case["question"])
    except Exception as e:
        return {**row, "passed": False, "error": f"judge: {e}", "answer": result["answer"],
                "cost_usd": cost_of(result["usage"])}
    tool_problems = [] if no_tools else grade_tools(case, result["tool_calls"])

    reasons = [f"figure {f['id']} ({f['expected']}) not in answer" for f in figures if not f["found"]]
    reasons += [f"missing point: {v['point']}" for v in verdicts["include"] if not v["met"]]
    reasons += [f"wrong claim: {v['point']}" for v in verdicts["exclude"] if v["present"]]
    reasons += tool_problems
    tin, tout = tokens_of(result["usage"])
    return {
        **row,
        "passed": not reasons,
        "reasons": reasons,
        "answer": result["answer"],
        "tool_calls": [c["name"] for c in result["tool_calls"]],
        "figures": figures,
        "verdicts": verdicts,
        "input_tokens": tin,
        "output_tokens": tout,
        "cost_usd": round(cost_of(result["usage"]), 6),
        "judge_cost_usd": round(cost_of(judge_usage), 6),
    }


# ---- report ----

def report(rows, skipped, agent_name, judge_name):
    lines = [f"# FirstPaycheck eval ({agent_name} agent, {judge_name} judge)", ""]
    modes = [m for m in ("agent", "baseline") if any(r["mode"] == m for r in rows)]
    analyses = sorted({r["analysis"] for r in rows})

    lines += ["## Pass rate by analysis", "",
              "| Analysis | " + " | ".join(modes) + " |",
              "|---|" + "---|" * len(modes)]
    for a in analyses + ["all"]:
        cells = []
        for m in modes:
            rs = [r for r in rows if r["mode"] == m and (a == "all" or r["analysis"] == a)]
            n = sum(r["passed"] for r in rs)
            cells.append(f"{n}/{len(rs)} ({100 * n / len(rs):.0f}%)" if rs else "-")
        lines.append(f"| {'**all**' if a == 'all' else a} | " + " | ".join(cells) + " |")

    lines += ["", "## Cost per question (agent run, judge excluded)", "",
              "| Analysis | Average | Most expensive |", "|---|---|---|"]
    for a in analyses:
        rs = [r for r in rows if r["mode"] == "agent" and r["analysis"] == a]
        if rs:
            top = max(rs, key=lambda r: r["cost_usd"])
            avg = sum(r["cost_usd"] for r in rs) / len(rs)
            lines.append(f"| {a} | ${avg:.4f} | ${top['cost_usd']:.4f} ({top['case']}) |")
    judge_total = sum(r.get("judge_cost_usd", 0) for r in rows)
    lines += ["", f"Judge cost for the whole run: ${judge_total:.4f}. Prices from eval/pricing.json "
                  f"(checked {PRICING['checked']})."]

    failed = [r for r in rows if not r["passed"]]
    if failed:
        lines += ["", "## Failures", ""]
        for r in failed:
            why = r.get("error") or "; ".join(r["reasons"][:4]) + (" …" if len(r["reasons"]) > 4 else "")
            lines.append(f"- **{r['case']}** ({r['mode']}): {why}")
    if skipped:
        lines += ["", "## Skipped (document not present)", ""]
        lines += [f"- {cid}: needs {', '.join(docs)} in data/" for cid, docs in skipped]
    return "\n".join(lines) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--agent", choices=["auto", *AGENTS], default="auto",
                   help="auto = cli if agent/run.py exists, else stub")
    p.add_argument("--judge", choices=["auto", *JUDGES], default="auto",
                   help="auto = claude for the real agent, stub for the stub agent")
    p.add_argument("--mode", choices=["both", "agent", "baseline"], default="both")
    p.add_argument("--cases", nargs="*", help="case ids or id prefixes to run (default: all)")
    p.add_argument("--min-pass-rate", type=float, default=0.0,
                   help="exit 1 if the agent's overall pass rate is below this (0-1)")
    args = p.parse_args(argv)

    agent_name = args.agent if args.agent != "auto" else ("cli" if AGENT_SCRIPT.exists() else "stub")
    judge_name = args.judge if args.judge != "auto" else ("claude" if agent_name == "cli" else "stub")
    if agent_name == "stub" and args.agent == "auto":
        print("agent/run.py not found: running the stub agent.", file=sys.stderr)
    ask, judge = AGENTS[agent_name], JUDGES[judge_name]

    cases = load_cases()
    if args.cases:
        cases = [c for c in cases if any(c["id"].startswith(x) for x in args.cases)]
    skipped = [(c["id"], missing_docs(c)) for c in cases if missing_docs(c)]
    runnable = [c for c in cases if not missing_docs(c)]

    modes = {"both": [False, True], "agent": [False], "baseline": [True]}[args.mode]
    rows = []
    for c in runnable:
        for no_tools in modes:
            r = run_case(c, ask, judge, no_tools)
            rows.append(r)
            print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['mode']:8}  {c['id']}", file=sys.stderr)

    text = report(rows, skipped, agent_name, judge_name)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(text)
    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = RESULTS / f"run-{stamp}-{agent_name}.json"
    out.write_text(json.dumps({"agent": agent_name, "judge": judge_name, "rows": rows,
                               "skipped": skipped}, indent=2))
    print(f"Full results: {out.relative_to(EVAL.parent)}", file=sys.stderr)

    agent_rows = [r for r in rows if r["mode"] == "agent"]
    rate = sum(r["passed"] for r in agent_rows) / len(agent_rows) if agent_rows else 1.0
    return 1 if rate < args.min_pass_rate else 0


if __name__ == "__main__":
    sys.exit(main())

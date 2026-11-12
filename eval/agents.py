"""The agents eval/run.py can ask: the real one (agent/run.py) and a stub.

Every agent is a function  ask(case, no_tools) -> result  where result is

    {
      "answer": "the text shown to the new hire",
      "tool_calls": [{"name": "paycheck", "args": {...}, "result": {...}}, ...],
      "usage": [{"model": "claude-haiku-5-5", "input_tokens": 1234, "output_tokens": 210}, ...]
    }

`usage` has one entry per model call, so a multi-step agent loop reports each step.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from cases import DOC_DIRS, ROOT

AGENT_SCRIPT = ROOT / "agent" / "run.py"


# ---- the stub: lets the runner, grading and CI work before the real agent exists ----

def stub_agent(case, no_tools):
    """A perfect agent for the agent run, and a 'no tools' baseline that can't compute anything.

    The agent answer restates every expected figure and point, so a stub run should pass 100%;
    if it doesn't, the grading code is broken, not the case.
    """
    if no_tools:
        return {"answer": "I can't work out exact numbers from the documents alone.",
                "tool_calls": [], "usage": []}
    lines = [f"{f['label']}: {_fmt(f)}" for f in case["expected"]["figures"] if f.get("graded", True)]
    lines += case["expected"]["must_include"]
    return {
        "answer": "\n".join(lines),
        "tool_calls": [{"name": t, "args": {}, "result": {}} for t in case["expected"].get("tools", [])],
        "usage": [],
    }


def _fmt(figure):
    v = figure["value"]
    if figure["unit"] == "percent":
        return f"{v}%"
    if figure["unit"] == "count":
        return f"{v}"
    return f"-${abs(v):,.2f}" if v < 0 else f"${v:,.2f}"


# ---- the real agent: Shawn's agent/run.py, called the way the proposal describes ----

def cli_agent(case, no_tools):
    """Run `python agent/run.py "<question>" --docs <dir> --profile <file> --log <file> [--no-tools]`.

    --docs gets a temporary folder holding only this case's documents, so the agent cannot
    read answers from other cases. --log is where agent/run.py writes the result JSON above.
    """
    if not AGENT_SCRIPT.exists():
        raise RuntimeError("agent/run.py does not exist yet; use --agent stub until it lands.")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        docs = tmp / "docs"
        docs.mkdir()
        for name in case["docs"]:
            src = next((d / name for d in DOC_DIRS if (d / name).exists()), None)
            if src is None:
                raise RuntimeError(f"{case['id']}: document {name} not found in samples/ or data/")
            (docs / name).symlink_to(src.resolve())
        profile = tmp / "profile.json"
        profile.write_text(json.dumps(case["resolved_profile"]))
        log = tmp / "log.json"
        cmd = [sys.executable, str(AGENT_SCRIPT), case["question"],
               "--docs", str(docs), "--profile", str(profile), "--log", str(log)]
        if no_tools:
            cmd.append("--no-tools")
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            raise RuntimeError(f"agent/run.py failed ({proc.returncode}): {proc.stderr[-2000:]}")
        result = json.loads(log.read_text())
    for key in ("answer", "tool_calls", "usage"):
        if key not in result:
            raise RuntimeError(f"agent/run.py log is missing '{key}'")
    return result


AGENTS = {"stub": stub_agent, "cli": cli_agent}

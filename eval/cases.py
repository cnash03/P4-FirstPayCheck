"""Load and check the evaluation cases in eval/cases/.

Each case is one JSON file (see eval/case.schema.json and eval/README.md).
eval/run.py will import load_cases(); the tests in tests/eval/ use check_case()
so a bad case fails `pytest` before it ever reaches the agent.

    python eval/cases.py            # list every case and any problems
"""
import ast
import json
import operator
import sys
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "eval"
CASES = EVAL / "cases"
PROFILES = EVAL / "profiles"
ANSWERS = ROOT / "samples" / "answers"
# Where case documents are looked up: committed synthetic docs, then the git-ignored
# data/ folder for documents that must stay out of the repo (e.g. the Tyler summary).
DOC_DIRS = [ROOT / "samples", ROOT / "data"]
SCHEMA = json.loads((EVAL / "case.schema.json").read_text())

USD_UNITS = {"usd_per_paycheck", "usd_per_month", "usd_per_year", "usd_per_period", "usd"}
DEFAULT_USD_TOLERANCE = 1.00  # the proposal's pass rule: within $1 of the confirmed answer


def tolerance(figure):
    return figure.get("tolerance", DEFAULT_USD_TOLERANCE if figure["unit"] in USD_UNITS else 0)


# ---- loading ----

def answer_fields():
    """Every field in samples/answers/*.json, keyed by id."""
    fields = {}
    for path in sorted(ANSWERS.glob("*.json")):
        for f in json.loads(path.read_text()).get("fields", []):
            fields[f["id"]] = f
    return fields


def load_profile(name, overrides=None):
    profile = json.loads((PROFILES / f"{name}.json").read_text())
    profile = {k: v for k, v in profile.items() if not k.startswith("_")}
    profile.update(overrides or {})
    return profile


def load_case(path, fields=None):
    """Read one case file. Adds 'resolved_profile' and 'resolved_fields' (id -> field)."""
    case = json.loads(Path(path).read_text())
    case["_path"] = str(path)
    fields = answer_fields() if fields is None else fields
    case["resolved_profile"] = load_profile(case["profile"], case.get("profile_overrides"))
    resolved = {}
    for f in case.get("fields", []):
        if isinstance(f, str):
            if f in fields:
                resolved[f] = fields[f]
        else:
            resolved[f["id"]] = f
    case["resolved_fields"] = resolved
    return case


def missing_docs(case):
    """Docs this case needs that are in neither samples/ nor data/. The runner skips such cases."""
    return [d for d in case["docs"] if not any((folder / d).exists() for folder in DOC_DIRS)]


def load_cases(directory=CASES):
    fields = answer_fields()
    return [load_case(p, fields) for p in sorted(Path(directory).glob("*.json"))]


# ---- derivations: small, safe arithmetic over figure ids ----

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg}
_FUNCS = {"min": min, "max": max}


def evaluate(expr, names):
    """Evaluate +, -, *, /, **, parentheses, min() and max() over numbers and names."""
    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in names:
                raise KeyError(f"unknown name '{node.id}'")
            return names[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
            return _FUNCS[node.func.id](*[ev(a) for a in node.args])
        raise ValueError(f"not allowed in a derivation: {ast.dump(node)}")
    return ev(ast.parse(expr, mode="eval"))


# ---- checks ----

def check_case(case, all_ids=None):
    """Return a list of problems with one loaded case; empty means it is good."""
    problems = []
    raw = {k: v for k, v in case.items() if not k.startswith("_") and not k.startswith("resolved_")}
    for err in jsonschema.Draft202012Validator(SCHEMA).iter_errors(raw):
        problems.append(f"schema: {'/'.join(map(str, err.path))}: {err.message}")
    if problems:
        return problems

    name = Path(case["_path"]).stem
    if case["id"] != name:
        problems.append(f"id '{case['id']}' does not match file name '{name}.json'")
    if all_ids is not None and case.get("variant_of") and case["variant_of"] not in all_ids:
        problems.append(f"variant_of '{case['variant_of']}' is not a case id")

    for f in case.get("fields", []):
        if isinstance(f, str) and f not in case["resolved_fields"]:
            problems.append(f"field '{f}' is not in samples/answers/*.json")

    figures = case["expected"]["figures"]
    values, seen = {}, set()
    for fig in figures:
        if fig["id"] in seen:
            problems.append(f"figure '{fig['id']}' appears twice")
        seen.add(fig["id"])
        values[fig["id"]] = fig["value"]

    for fig in figures:
        fid = fig["id"]
        if "from_field" in fig:
            field = case["resolved_fields"].get(fig["from_field"])
            if field is None:
                problems.append(f"{fid}: from_field '{fig['from_field']}' is not in this case's fields")
            elif field["value"] != fig["value"]:
                problems.append(f"{fid}: value {fig['value']} but the document field says {field['value']}")
        if "from_profile" in fig:
            have = case["resolved_profile"].get(fig["from_profile"])
            if have != fig["value"]:
                problems.append(f"{fid}: value {fig['value']} but profile '{fig['from_profile']}' is {have}")
        if "derivation" in fig:
            try:
                got = round(evaluate(fig["derivation"], values) + 1e-9, 2)
            except (KeyError, ValueError, ZeroDivisionError, SyntaxError) as e:
                problems.append(f"{fid}: derivation error: {e}")
                continue
            if abs(got - fig["value"]) > 0.005:
                problems.append(f"{fid}: value {fig['value']} but derivation gives {got}")

    docs = set(case["docs"])
    for c in case["expected"].get("citations", []):
        if c["doc"] not in docs:
            problems.append(f"citation {c['doc']} p{c['page']} is not in docs")

    if case["expected"].get("asks_for") is None and not any(f.get("graded", True) for f in figures):
        problems.append("no graded figures and no asks_for: nothing for the grader to check")
    return problems


def main():
    cases = load_cases()
    ids = {c["id"] for c in cases}
    bad = 0
    print(f"{'case':32} {'analysis':20} {'status':15} graded figures")
    for c in cases:
        graded = sum(f.get("graded", True) for f in c["expected"]["figures"])
        missing = missing_docs(c)
        skip = f"   (skipped by the runner: put {', '.join(missing)} in data/)" if missing else ""
        print(f"{c['id']:32} {c['analysis']:20} {c['status']:15} {graded}{skip}")
        for p in check_case(c, ids):
            bad += 1
            print(f"    PROBLEM: {p}")
    print(f"\n{len(cases)} cases, {sum(c['status'] == 'user_confirmed' for c in cases)} user-confirmed, {bad} problems")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

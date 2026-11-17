"""Config only: every rate and limit comes from the tax config, none hard-coded.

The manual check from the proposal: change one 401(k) limit in config/tax_2026.json, rerun
`pytest engine/`, and test_contribution_order.py::test_high_earner_hits_401k_limit_and_roth_phaseout
fails because its output changed. The tests below automate the same check.
"""
import ast
import json
from pathlib import Path

from engine.config import ENV_VAR, load_config
from engine.contribution_order import contribution_order
from engine.paycheck import paycheck

ENGINE = Path(__file__).resolve().parents[1]
HALF_OF_SIX = [{"match_percent": 50, "up_to_percent_of_pay": 6}]
# Numbers that are arithmetic, not tax rules: identity, percent, months in a year, display digits.
ALLOWED_NUMBERS = {0, 1, 4, 12, 100}


def high_earner(config):
    return contribution_order(300000, "biweekly", HALF_OF_SIX, 3000, emergency_fund_months=6, config=config)


def test_changing_401k_limit_changes_output(config):
    before = high_earner(config)
    after = high_earner(config.with_value("retirement.deferral_limit_401k", 20000))
    extra = {s["id"]: s["per_check"] for s in after["steps"]}["extra_401k"]
    assert extra == 76.92                             # 20,000 / 26 = 769.23 - 692.31
    assert after["left_over_per_check"] != before["left_over_per_check"]
    # The paycheck's 401(k) line stops at the new limit too
    capped = paycheck(90000, "biweekly", "single", retirement_401k_percent=10, ytd_401k=19900,
                      config=config.with_value("retirement.deferral_limit_401k", 20000))
    assert capped["deductions"]["401k_traditional"] == 100.00


def test_config_file_from_environment(tmp_path, monkeypatch, config):
    data = json.loads(Path(config.path).read_text())
    data["retirement"]["deferral_limit_401k"]["value"] = 20000
    edited = tmp_path / "tax_edited.json"
    edited.write_text(json.dumps(data))
    monkeypatch.setenv(ENV_VAR, str(edited))
    assert load_config().get("retirement.deferral_limit_401k") == 20000
    result = contribution_order(300000, "biweekly", HALF_OF_SIX, 3000, emergency_fund_months=6)  # no config arg
    assert {s["id"]: s["per_check"] for s in result["steps"]}["extra_401k"] == 76.92


def test_changing_a_tax_rate_changes_paycheck(config):
    base = paycheck(90000, "biweekly", "single", config=config)
    edited = paycheck(90000, "biweekly", "single", config=config.with_value("colorado.withholding.rate", 0.05))
    assert edited["deductions"]["colorado_withholding"] > base["deductions"]["colorado_withholding"]


def test_every_value_has_source_and_tax_year(config):
    missing = []

    def walk(node, path):
        if isinstance(node, dict) and "value" in node:
            if not node.get("source") or not node.get("tax_year"):
                missing.append(path)
            return
        if isinstance(node, dict):
            for key, child in node.items():
                if not key.startswith("_") and key not in ("schema_version", "tax_year", "note"):
                    walk(child, f"{path}.{key}".lstrip("."))
    walk(config.data, "")
    assert missing == []


def test_no_tax_numbers_in_engine_code():
    found = []
    for path in sorted(ENGINE.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Constant) and type(node.value) in (int, float) and node.value not in ALLOWED_NUMBERS:
                found.append(f"{path.name}:{node.lineno} {node.value}")
    assert found == [], "rates and limits belong in config/tax_2026.json"

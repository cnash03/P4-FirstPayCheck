"""Cross-check: the engine agrees with every graded figure in the eval cases (eval/cases/*.json).

The cases are Callen's expected answers, computed by hand, so this is a second, independent
check on top of the hand-worked tests. Each test fails if a graded figure is neither matched
within its tolerance nor named in `owned_elsewhere` (figures another tool produces).
"""
import json
from pathlib import Path

import pytest

from engine.benefits_cost import benefits_cost
from engine.contribution_order import contribution_order
from engine.espp import espp
from engine.paycheck import paycheck

CASES = Path(__file__).resolve().parents[2] / "eval" / "cases"
USD_UNITS = {"usd_per_paycheck", "usd_per_month", "usd_per_year", "usd_per_period", "usd"}


def assert_matches_case(case_id, got, owned_elsewhere=()):
    case = json.loads((CASES / f"{case_id}.json").read_text())
    for figure in case["expected"]["figures"]:
        if figure.get("graded", True) is False or figure["id"] in owned_elsewhere:
            continue
        assert figure["id"] in got, f"{case_id}: no engine output for graded figure {figure['id']}"
        tolerance = figure.get("tolerance", 1.00 if figure["unit"] in USD_UNITS else 0)
        assert abs(got[figure["id"]] - figure["value"]) <= tolerance, \
            (case_id, figure["id"], got[figure["id"]], figure["value"])


def steps(result):
    return {s["id"]: s["per_check"] for s in result["steps"]}


@pytest.mark.parametrize("case_id,salary,medical,city", [
    ("ex1-take-home", 90000, 62.00, "Denver"),
    ("ex1-tyler-take-home", 85000, 69.30, "colorado_no_local_tax"),
])
def test_example_1(config, case_id, salary, medical, city):
    r = paycheck(salary, "biweekly", "single", retirement_401k_percent=6, pretax_deductions={"medical": medical},
                 city=city, config=config)
    d = r["deductions"]
    assert_matches_case(case_id, {
        "medical_premium": d["medical"], "gross_pay": r["gross_pay"], "pretax_401k": d["401k_traditional"],
        "federal_withholding": d["federal_withholding"], "social_security": d["social_security"],
        "medicare": d["medicare"], "colorado_withholding": d["colorado_withholding"],
        "colorado_famli": d["colorado_famli"], "denver_opt": d.get("local_occupational_tax", 0),
        "net_pay": r["net_pay"], "net_pay_no_opt": r["net_pay_without_monthly_local_tax"],
    })


def test_example_2(config):
    plans = [
        {"name": "PPO 750", "premium_per_check": 62.00, "deductible": 750, "out_of_pocket_max": 3500},
        {"name": "PPO 1500", "premium_per_check": 38.00, "deductible": 1500, "out_of_pocket_max": 5000},
        {"name": "HDHP", "premium_per_check": 18.00, "deductible": 3400, "out_of_pocket_max": 6500,
         "hsa_eligible": True, "employer_hsa_annual": 500},
    ]
    r = benefits_cost(plans, "biweekly", "employee_only", annual_salary=90000, config=config)
    p = {plan["name"]: plan for plan in r["plans"]}
    assert_matches_case("ex2-hdhp-vs-ppo", {
        "employer_hsa": p["HDHP"]["employer_hsa_per_year"],
        "ppo750_premium_year": p["PPO 750"]["premiums_per_year"],
        "ppo1500_premium_year": p["PPO 1500"]["premiums_per_year"],
        "hdhp_premium_year": p["HDHP"]["premiums_per_year"],
        "ppo750_low_use": p["PPO 750"]["low_use_year"], "ppo1500_low_use": p["PPO 1500"]["low_use_year"],
        "hdhp_low_use": p["HDHP"]["low_use_year"],
        "ppo750_high_use": p["PPO 750"]["high_use_year"], "ppo1500_high_use": p["PPO 1500"]["high_use_year"],
        "hdhp_high_use": p["HDHP"]["high_use_year"],
        "hsa_own_room": r["hsa"]["own_room_per_year"], "hsa_tax_savings": r["hsa"]["tax_savings_at_max"],
    })


def test_example_2_tyler(config):
    plans = [
        {"name": "PPO 750", "premium_per_check": 69.30, "deductible": 750, "out_of_pocket_max": 3000},
        {"name": "PPO 1500", "premium_per_check": 34.65, "deductible": 1500, "out_of_pocket_max": 4500},
        {"name": "HDHP", "premium_per_check": 10.50, "deductible": 3400, "out_of_pocket_max": 6800,
         "hsa_eligible": True, "employer_hsa_annual": 750},
    ]
    r = benefits_cost(plans, "biweekly", "employee_only", annual_salary=90000, config=config)
    p = {plan["name"]: plan for plan in r["plans"]}
    assert_matches_case("ex2-tyler-hdhp-vs-ppo", {
        "employer_hsa": p["HDHP"]["employer_hsa_per_year"],
        "ppo750_low_use": p["PPO 750"]["low_use_year"], "ppo1500_low_use": p["PPO 1500"]["low_use_year"],
        "hdhp_low_use": p["HDHP"]["low_use_year"],
        "ppo750_high_use": p["PPO 750"]["high_use_year"], "ppo1500_high_use": p["PPO 1500"]["high_use_year"],
        "hdhp_high_use": p["HDHP"]["high_use_year"],
        "employer_hsa_per_check": p["HDHP"]["employer_hsa_per_check"],
        "hsa_own_room": r["hsa"]["own_room_per_year"],
    })


@pytest.mark.parametrize("case_id,salary,employer_hsa", [
    ("ex3-match-then-roth", 90000, 500),
    ("ex3-tyler-match-then-roth", 85000, 750),
])
def test_example_3(config, case_id, salary, employer_hsa):
    tiers = [{"match_percent": 50, "up_to_percent_of_pay": 6}]
    r = contribution_order(salary, "biweekly", tiers, 600, emergency_fund_months=3, config=config)
    on_hdhp = contribution_order(salary, "biweekly", tiers, 600, emergency_fund_months=3,
                                 hsa_eligible_plan=True, employer_hsa_annual=employer_hsa, config=config)
    s = steps(r)
    assert_matches_case(case_id, {
        "match_percent_of_pay": r["match_percent_of_pay"], "step1_401k_to_match": s["401k_to_match"],
        "match_per_check": r["match_per_check"], "match_per_year": r["match_per_year"],
        "roth_ira_max_per_check": s["roth_ira"], "step3_roth_ira": s["roth_ira"],
        "step4_extra_401k": s["extra_401k"], "hsa_max_per_check_if_hdhp": steps(on_hdhp)["hsa"],
    })


def test_example_4(config):
    r = espp(90000, "biweekly", 10, 15, 6, True, 6, emergency_fund_months=3, config=config)
    assert_matches_case("ex4-espp", {
        "espp_per_check": r["per_check"], "espp_per_period": r["per_offering_period"],
        "built_in_gain": r["built_in_gain_per_period"], "built_in_return": r["built_in_return_percent"],
    })


def test_example_4_no_emergency_fund(config):
    r = espp(90000, "biweekly", 10, 15, 6, True, 6, emergency_fund_months=0, config=config)
    assert_matches_case("ex4-espp-no-emergency-fund", {
        "espp_per_check": r["per_check"], "built_in_return": r["built_in_return_percent"],
    })
    assert "no_emergency_fund" in r["hard_case_triggers"]


def test_example_4_tyler(config):
    r = espp(90000, "biweekly", 10, 15, 3, False, None, months_until_eligible=6, config=config)
    assert_matches_case("ex4-tyler-espp", {
        "months_until_eligible": r["months_until_eligible"], "espp_per_quarter": r["per_offering_period"],
        "built_in_gain": r["built_in_gain_per_period"], "built_in_return": r["built_in_return_percent"],
    })


def test_example_5_dollar_order(config):
    """Example 5's order of dollars comes from contribution_order; the loan math is loan_vs_invest (stretch)."""
    r = contribution_order(90000, "biweekly", [{"match_percent": 50, "up_to_percent_of_pay": 6}], 600,
                           emergency_fund_months=3, config=config)
    s = steps(r)
    assert_matches_case("ex5-loans-vs-invest", {
        "step1_401k_to_match": s["401k_to_match"], "match_per_check": r["match_per_check"],
        "step2_roth_ira": s["roth_ira"], "step3_left_over": s["extra_401k"],
    }, owned_elsewhere=("match_return", "loan_min_payment", "loan_min_per_check"))

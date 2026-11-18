"""Offers outside Appendix A, built by chaining the calculators' generic inputs.

Scenario: $100k base, the employer puts $25,000 a year into the 401(k) regardless of what you  (privacy: allow)
contribute, and a benefits fund (flex credits) pays for medical with the unspent part going to
the 401(k) or paid as taxable cash. The fund amount is illustrative ($3,000 a year) on the
synthetic guide's employee-only plans: premiums 1,612 / 988 / 468 a year. Hand-worked.
"""
import pytest

from engine.benefits_cost import benefits_cost
from engine.contribution_order import contribution_order
from engine.paycheck import paycheck

PLANS = [
    {"name": "PPO 750", "premium_per_check": 62.00, "deductible": 750, "out_of_pocket_max": 3500},
    {"name": "PPO 1500", "premium_per_check": 38.00, "deductible": 1500, "out_of_pocket_max": 5000},
    {"name": "HDHP", "premium_per_check": 18.00, "deductible": 3400, "out_of_pocket_max": 6500,
     "hsa_eligible": True, "employer_hsa_annual": 500},
]


def by_name(result):
    return {p["name"]: p for p in result["plans"]}


# ---- Employer 401(k) money that isn't a match ----

def test_fixed_employer_401k_does_not_use_your_deferral_limit(config):
    # No match. Room: min(24,500, 72,000 - 25,000) = 24,500 -> 942.31 a check.
    # Goal 800: Roth 288.46, extra 401(k) 800 - 288.46 = 511.54.
    r = contribution_order(100000, "biweekly", [], 800, emergency_fund_months=3,
                           employer_nonmatch_annual=25000, config=config)
    s = {x["id"]: x["per_check"] for x in r["steps"]}
    assert (s["401k_to_match"], s["roth_ira"], s["extra_401k"]) == (0, 288.46, 511.54)
    assert r["employer_nonmatch_per_check"] == 961.54          # 25,000 / 26
    assert r["employer_401k_total_per_year"] == 25000.00
    assert r["your_401k_room_per_year"] == 24500.00
    assert r["warnings"] == []


def test_employer_money_squeezes_room_under_415c(config):
    # 72,000 - 60,000 = 12,000 of room -> 461.54 a check; goal 2,000 leaves 2,000 - 288.46 - 461.54
    r = contribution_order(100000, "biweekly", [], 2000, emergency_fund_months=3,
                           employer_nonmatch_annual=60000, config=config)
    s = {x["id"]: x["per_check"] for x in r["steps"]}
    assert s["extra_401k"] == 461.54
    assert r["left_over_per_check"] == 1250.00


def test_employer_money_at_415c_leaves_only_catch_up(config):
    r = contribution_order(100000, "biweekly", [], 2000, emergency_fund_months=3,
                           employer_nonmatch_annual=72000, config=config)
    assert {x["id"]: x["per_check"] for x in r["steps"]}["extra_401k"] == 0
    assert any("total limit" in w for w in r["warnings"])
    older = contribution_order(100000, "biweekly", [], 2000, emergency_fund_months=3,
                               employer_nonmatch_annual=72000, age=52, config=config)
    assert {x["id"]: x["per_check"] for x in older["steps"]}["extra_401k"] == 307.69  # 8,000 catch-up / 26


# ---- Benefits fund (flex credits) ----

def test_benefits_fund_leftover_to_401k(config):
    r = benefits_cost(PLANS, "biweekly", "employee_only", employer_credit_annual=3000,
                      leftover_credit_to="401k", config=config)
    p = by_name(r)
    # Fund covers every premium; leftover 3,000 - premiums = 1,388 / 2,012 / 2,532, at full value
    assert [p[n]["credit_left_over_per_year"] for n in p] == [1388.00, 2012.00, 2532.00]
    assert [p[n]["credit_left_over_per_check"] for n in p] == [53.38, 77.38, 97.38]
    assert [p[n]["premium_you_pay_per_check"] for n in p] == [0, 0, 0]
    assert [p[n]["low_use_year"] for n in p] == [-1388.00, -2012.00, -3032.00]  # HDHP also -500 HSA
    assert [p[n]["high_use_year"] for n in p] == [2112.00, 2988.00, 3468.00]    # + OOP max


def test_benefits_fund_leftover_as_cash_is_taxed(config):
    # 100,000 - 8,600 = 91,400: 22% row. 22% + 4.4% + 6.2% + 1.45% + 0.44% FAMLI = 34.49%; keep 65.51%
    r = benefits_cost(PLANS, "biweekly", "employee_only", annual_salary=100000, employer_credit_annual=3000,
                      leftover_credit_to="cash", config=config)
    p = by_name(r)
    assert [p[n]["credit_left_over_value"] for n in p] == [909.28, 1318.06, 1658.71]
    assert [p[n]["low_use_year"] for n in p] == [-909.28, -1318.06, -2158.71]
    assert [p[n]["high_use_year"] for n in p] == [2590.72, 3681.94, 4341.29]


def test_benefits_fund_smaller_than_premium_and_forfeited(config):
    r = benefits_cost(PLANS, "biweekly", "employee_only", employer_credit_annual=1000, config=config)
    p = by_name(r)
    assert p["PPO 750"]["premium_you_pay_per_check"] == 23.54   # (1,612 - 1,000) / 26
    assert [p[n]["low_use_year"] for n in p] == [612.00, 0.00, -500.00]  # PPO 1500's 12 left over is lost


def test_cash_leftover_needs_a_salary(config):
    with pytest.raises(ValueError, match="annual_salary"):
        benefits_cost(PLANS, "biweekly", "employee_only", employer_credit_annual=3000,
                      leftover_credit_to="cash", config=config)


# ---- Putting it together on the paycheck ----

def test_cash_leftover_flows_into_paycheck(config):
    """PPO 750 with the fund paying the premium; its 53.38 leftover paid each check as wages."""
    fund = by_name(benefits_cost(PLANS, "biweekly", "employee_only", annual_salary=100000,
                                 employer_credit_annual=3000, leftover_credit_to="cash", config=config))
    cash = fund["PPO 750"]["credit_left_over_per_check"]
    r = paycheck(100000, "biweekly", "single", other_taxable_earnings={"benefits_cash": cash},
                 city="Denver", config=config)
    d = r["deductions"]
    assert (r["base_pay"], r["gross_pay"]) == (3846.15, 3899.53)
    # (5,800 + 22% x (101,387.78 - 8,600 - 57,900)) / 26
    assert d["federal_withholding"] == 518.28
    assert d["colorado_withholding"] == 162.27                  # (101,387.78 - 5,500) x 4.4% / 26
    assert (d["social_security"], d["medicare"], d["colorado_famli"]) == (241.77, 56.54, 17.16)
    assert r["net_pay"] == 2897.76


def test_401k_percent_over_the_limit_warns(config):
    over = paycheck(100000, "biweekly", "single", retirement_401k_percent=25, config=config)
    assert over["deductions"]["401k_traditional"] == 961.54
    assert any("over the $24,500" in w for w in over["warnings"])
    assert paycheck(100000, "biweekly", "single", retirement_401k_percent=6, config=config)["warnings"] == []

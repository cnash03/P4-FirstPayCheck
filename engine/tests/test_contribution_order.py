"""Contribution-order calculator: Appendix A Example 3 (and Example 5's dollar order). Hand-worked."""
import pytest

from engine.contribution_order import (contribution_order, full_match_percent, match_percent_of_pay,
                                       roth_ira_limit)

HALF_OF_SIX = [{"match_percent": 50, "up_to_percent_of_pay": 6}]


def steps(result):
    return {s["id"]: s["per_check"] for s in result["steps"]}


def test_example_3_match_then_roth(config, fields, profiles):
    """'The company matches 6%... Roth IRA, which comes first?' (eval: ex3-match-then-roth)."""
    p = profiles["default"]
    result = contribution_order(fields["offer_letter.pdf:offer.annual_salary"],
                                fields["offer_letter.pdf:offer.pay_frequency"],
                                fields["benefits_guide.pdf:retirement.match_tiers"],
                                p["savings_goal_per_check"], emergency_fund_months=p["emergency_fund_months"],
                                config=config)
    # The match is 50% of the first 6%: worth 3% of pay, not 6%
    assert result["full_match_contribution_percent"] == 6
    assert result["match_percent_of_pay"] == 3
    assert [s["id"] for s in result["steps"]] == ["401k_to_match", "hsa", "roth_ira", "extra_401k"]
    s = steps(result)
    assert s["401k_to_match"] == 207.69          # 3,461.54 x 6%
    assert s["hsa"] == 0                         # PPO 750: no HSA
    assert s["roth_ira"] == 288.46               # 7,500 / 26
    assert s["extra_401k"] == 103.85             # 600 - 207.69 - 288.46
    assert result["match_per_check"] == 103.85   # 3,461.54 x 3%
    assert result["match_per_year"] == 2700.00   # 90,000 x 3%
    assert result["left_over_per_check"] == 0
    assert result["warnings"] == []


def test_example_3_tyler_profile(config, profiles):
    p = profiles["tyler"]
    result = contribution_order(p["annual_salary"], p["pay_frequency"], HALF_OF_SIX, p["savings_goal_per_check"],
                                emergency_fund_months=p["emergency_fund_months"], config=config)
    s = steps(result)
    assert (s["401k_to_match"], s["roth_ira"], s["extra_401k"]) == (196.15, 288.46, 115.39)
    assert (result["match_per_check"], result["match_per_year"]) == (98.08, 2550.00)


def test_hdhp_puts_hsa_second(config):
    # (4,400 - 500) / 26 = 150.00; Roth gets what's left of 600: 600 - 207.69 - 150 = 242.31
    result = contribution_order(90000, "biweekly", HALF_OF_SIX, 600, emergency_fund_months=3,
                                hsa_eligible_plan=True, employer_hsa_annual=500, config=config)
    s = steps(result)
    assert (s["401k_to_match"], s["hsa"], s["roth_ira"], s["extra_401k"]) == (207.69, 150.00, 242.31, 0)


def test_tyler_hdhp_hsa_step(config):
    # (4,400 - 750) / 26 = 140.38
    result = contribution_order(85000, "biweekly", HALF_OF_SIX, 600, emergency_fund_months=3,
                                hsa_eligible_plan=True, employer_hsa_annual=750, config=config)
    assert steps(result)["hsa"] == 140.38


def test_no_emergency_fund_builds_it_after_the_match(config):
    result = contribution_order(90000, "biweekly", HALF_OF_SIX, 600, emergency_fund_months=0, config=config)
    assert [s["id"] for s in result["steps"]] == ["401k_to_match", "emergency_fund"]
    assert steps(result) == {"401k_to_match": 207.69, "emergency_fund": 392.31}


def test_goal_smaller_than_match(config):
    # All 150 to the 401(k): 4.33% of pay, matched at 50% = 75.00 a check
    result = contribution_order(90000, "biweekly", HALF_OF_SIX, 150, emergency_fund_months=3, config=config)
    assert steps(result)["401k_to_match"] == 150.00
    assert result["match_per_check"] == 75.00
    assert result["match_per_year"] == 1950.00
    assert result["warnings"]


def test_married_family_profile_without_emergency_fund(config, profiles):
    p = profiles["married_hdhp_family"]
    result = contribution_order(p["annual_salary"], p["pay_frequency"], HALF_OF_SIX, p["savings_goal_per_check"],
                                emergency_fund_months=p["emergency_fund_months"], hsa_eligible_plan=True,
                                employer_hsa_annual=1000, coverage=p["coverage"],
                                filing_status=p["filing_status"], age=p["age"], config=config)
    # 120,000 / 26 = 4,615.38 x 6% = 276.92; the rest of 1,000 to the emergency fund
    assert steps(result) == {"401k_to_match": 276.92, "emergency_fund": 723.08}


def test_multi_tier_match():
    tiers = [{"match_percent": 100, "up_to_percent_of_pay": 3}, {"match_percent": 50, "up_to_percent_of_pay": 5}]
    assert full_match_percent(tiers) == 5
    assert match_percent_of_pay(5, tiers) == 4      # 3 + 50% x 2
    assert match_percent_of_pay(2, tiers) == 2
    assert match_percent_of_pay(10, tiers) == 4


def test_multi_tier_match_dollars(config):
    tiers = [{"match_percent": 100, "up_to_percent_of_pay": 3}, {"match_percent": 50, "up_to_percent_of_pay": 5}]
    result = contribution_order(52000, "biweekly", tiers, 500, emergency_fund_months=6, config=config)
    assert steps(result)["401k_to_match"] == 100.00    # 2,000 x 5%
    assert (result["match_per_check"], result["match_per_year"]) == (80.00, 2080.00)


@pytest.mark.parametrize("magi,status,age,expected", [
    (100000, "single", None, 7500),
    (153000, "single", None, 7500),
    (160000, "single", None, 4000),     # 7,500 x (1 - 7,000 / 15,000) = 4,000
    (161234, "single", None, 3390),     # 7,500 x (1 - 8,234 / 15,000) = 3,383.00, rounded up to 3,390
    (167900, "single", None, 200),      # 50.00, raised to the 200 minimum
    (168000, "single", None, 0),
    (247000, "married_filing_jointly", None, 3750),  # 7,500 x (1 - 5,000 / 10,000)
    (100000, "single", 50, 8600),       # + 1,100 catch-up
])
def test_roth_ira_phaseout(config, magi, status, age, expected):
    assert roth_ira_limit(magi, status, age, config) == expected


def test_high_earner_hits_401k_limit_and_roth_phaseout(config):
    # 300,000 / 26 = 11,538.46; 6% = 692.31. Over the Roth limit -> 0.
    # Extra 401(k): 24,500 / 26 = 942.31 - 692.31 = 250.00; left over 3,000 - 942.31 = 2,057.69
    result = contribution_order(300000, "biweekly", HALF_OF_SIX, 3000, emergency_fund_months=6, config=config)
    s = steps(result)
    assert (s["401k_to_match"], s["roth_ira"], s["extra_401k"]) == (692.31, 0, 250.00)
    assert result["left_over_per_check"] == 2057.69
    assert any("backdoor" in w for w in result["warnings"])

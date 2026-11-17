"""Benefits-cost calculator: Appendix A Example 2 and its edge cases. Expected numbers hand-worked."""
import pytest

from engine.benefits_cost import benefits_cost, hsa_tax_rate, out_of_pocket


def synthetic_plans(fields, tier="employee_only"):
    """The three plans in samples/benefits_guide.pdf, built from the extracted fields."""
    def f(name, plan):
        return fields[f"benefits_guide.pdf:health.{name}:{plan}:{tier}"]
    coinsurance = {"PPO 750": 20, "PPO 1500": 20, "HDHP with HSA": 10}  # guide p. 4 (not an extracted field yet)
    plans = []
    for plan in ("PPO 750", "PPO 1500", "HDHP with HSA"):
        hsa = plan == "HDHP with HSA"
        plans.append({
            "name": plan,
            "premium_per_check": f("premium", plan),
            "deductible": f("deductible", plan),
            "out_of_pocket_max": f("out_of_pocket_max", plan),
            "coinsurance_percent": coinsurance[plan],
            "hsa_eligible": hsa,
            "employer_hsa_annual": f("employer_hsa_contribution", plan) if hsa else 0,
        })
    return plans


def by_name(result):
    return {plan["name"]: plan for plan in result["plans"]}


def test_example_2_hdhp_vs_ppo(config, fields):
    """'HDHP with an HSA or the PPO? I rarely see a doctor.' (eval: ex2-hdhp-vs-ppo)."""
    result = benefits_cost(synthetic_plans(fields), "biweekly", "employee_only",
                           annual_salary=90000, filing_status="single", config=config)
    plans = by_name(result)
    # Premiums: 62 / 38 / 18 x 26
    assert [plans[p]["premiums_per_year"] for p in ("PPO 750", "PPO 1500", "HDHP with HSA")] == [1612.00, 988.00, 468.00]
    # Low-use: premiums only, HDHP minus the company's $500
    assert plans["PPO 750"]["low_use_year"] == 1612.00
    assert plans["PPO 1500"]["low_use_year"] == 988.00
    assert plans["HDHP with HSA"]["low_use_year"] == -32.00
    # High-use: premiums + out-of-pocket max (3,500 / 5,000 / 6,500), HDHP minus $500
    assert plans["PPO 750"]["high_use_year"] == 5112.00
    assert plans["PPO 1500"]["high_use_year"] == 5988.00
    assert plans["HDHP with HSA"]["high_use_year"] == 6468.00
    assert (result["cheapest_low_use"], result["cheapest_high_use"]) == ("HDHP with HSA", "PPO 750")
    # HSA: 4,400 limit - 500 company = 3,900 (150/check); saved at 22% + 4.4% + 7.65% = 34.05%
    hsa = result["hsa"]
    assert (hsa["own_room_per_year"], hsa["own_room_per_check"]) == (3900.00, 150.00)
    assert hsa["tax_rates"]["federal"] == 0.22
    assert hsa["tax_savings_at_max"] == 1327.95


def test_example_2_tyler_summary(config):
    """Tyler 2026 summary numbers, which must not mix with the synthetic guide (eval: ex2-tyler-hdhp-vs-ppo)."""
    plans = [
        {"name": "PPO 750", "premium_per_check": 69.30, "deductible": 750, "out_of_pocket_max": 3000},
        {"name": "PPO 1500", "premium_per_check": 34.65, "deductible": 1500, "out_of_pocket_max": 4500},
        {"name": "HDHP With HSA", "premium_per_check": 10.50, "deductible": 3400, "out_of_pocket_max": 6800,
         "hsa_eligible": True, "employer_hsa_annual": 750},
    ]
    result = benefits_cost(plans, "biweekly", "employee_only", annual_salary=90000, config=config)
    p = by_name(result)
    assert [p[n]["low_use_year"] for n in p] == [1801.80, 900.90, -477.00]   # 69.30/34.65 x 26; 273 - 750
    assert [p[n]["high_use_year"] for n in p] == [4801.80, 5400.90, 6323.00]  # + 3,000 / 4,500 / 6,800
    assert p["HDHP With HSA"]["employer_hsa_per_check"] == 28.85              # 750 / 26
    assert result["hsa"]["own_room_per_year"] == 3650.00                      # 4,400 - 750


def test_medium_use_year_uses_deductible_and_coinsurance(config, fields):
    result = benefits_cost(synthetic_plans(fields), "biweekly", "employee_only", expected_claims=2000, config=config)
    p = by_name(result)
    assert p["PPO 750"]["expected_claims_out_of_pocket"] == 1000.00    # 750 + 20% x 1,250
    assert p["PPO 1500"]["expected_claims_out_of_pocket"] == 1600.00   # 1,500 + 20% x 500
    assert p["HDHP with HSA"]["expected_claims_out_of_pocket"] == 2000.00  # all under the 3,400 deductible
    assert p["PPO 750"]["expected_claims_year"] == 2612.00
    assert p["PPO 1500"]["expected_claims_year"] == 2588.00
    assert p["HDHP with HSA"]["expected_claims_year"] == 1968.00       # 468 + 2,000 - 500


def test_out_of_pocket_caps_at_max():
    assert out_of_pocket(100000, 750, 20, 3500) == 3500
    assert out_of_pocket(0, 750, 20, 3500) == 0


def test_family_coverage_uses_family_hsa_limit_and_catch_up(config, fields, profiles):
    """Third test profile: married, family HDHP, age 56, $120k."""
    p = profiles["married_hdhp_family"]
    result = benefits_cost(synthetic_plans(fields, "family"), p["pay_frequency"], p["coverage"],
                           annual_salary=p["annual_salary"], filing_status=p["filing_status"], age=p["age"],
                           config=config)
    plans = by_name(result)
    assert plans["HDHP with HSA"]["premiums_per_year"] == 2704.00      # 104 x 26
    assert plans["HDHP with HSA"]["low_use_year"] == 1704.00           # - 1,000 company money
    hsa = result["hsa"]
    assert hsa["annual_limit"] == 9750                                 # 8,750 family + 1,000 catch-up at 55+
    assert hsa["own_room_per_year"] == 8750.00
    # MFJ 120,000 - 12,900 = 107,100: 12% row; 12% + 4.4% + 7.65% = 24.05% x 8,750
    assert hsa["tax_rates"]["federal"] == 0.12
    assert hsa["tax_savings_at_max"] == 2104.38


def test_company_hsa_money_never_counts_on_a_ppo(config):
    plans = [{"name": "PPO 750", "premium_per_check": 62, "deductible": 750, "out_of_pocket_max": 3500,
              "employer_hsa_annual": 500}]
    result = benefits_cost(plans, "biweekly", "employee_only", config=config)
    assert result["plans"][0]["low_use_year"] == 1612.00
    assert "hsa" not in result


def test_hsa_tax_rate_over_social_security_wage_base(config):
    # 200,000 - 8,600 = 191,400: 24% row; over the 184,500 base, so no Social Security saved
    rates = hsa_tax_rate(200000, "single", config=config)
    assert rates["federal"] == 0.24
    assert rates["social_security"] == 0
    assert rates["total"] == pytest.approx(0.24 + 0.044 + 0.0145)


def test_rejects_bad_inputs(config):
    with pytest.raises(ValueError, match="empty"):
        benefits_cost([], "biweekly", "employee_only", config=config)
    with pytest.raises(ValueError, match="premium_per_check"):
        benefits_cost([{"name": "x", "premium_per_check": -1, "deductible": 0, "out_of_pocket_max": 0}],
                      "biweekly", "employee_only", config=config)

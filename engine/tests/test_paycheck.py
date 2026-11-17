"""Paycheck calculator: Appendix A Example 1, Pub 15-T Worksheet 1A, DR 1098, FICA and city tax.

Every expected number is worked by hand in the comment next to it (2026 tables), not copied
from calculator output.
"""
import pytest

from engine.paycheck import colorado_withholding, federal_withholding, paycheck

TOLERANCE = 1.00  # the proposal's pass rule: within $1 per check


# ---- Appendix A, Example 1 ----

def test_example_1_take_home_default_profile(config, profiles, fields):
    """'My offer says 90k. What actually hits my account every two weeks?' (eval: ex1-take-home)."""
    p = profiles["default"]
    result = paycheck(
        fields["offer_letter.pdf:offer.annual_salary"],
        fields["offer_letter.pdf:offer.pay_frequency"],
        p["filing_status"],
        retirement_401k_percent=p["retirement_401k_percent"],
        pretax_deductions={"medical": fields["benefits_guide.pdf:health.premium:PPO 750:employee_only"]},
        city=p["city"],
        w4=p["w4"],
        config=config,
    )
    d = result["deductions"]
    assert result["gross_pay"] == 3461.54           # 90,000 / 26
    assert d["401k_traditional"] == 207.69          # 3,461.54 x 6%
    assert d["medical"] == 62.00
    assert result["income_tax_wages"] == 3191.85    # 3,461.54 - 207.69 - 62.00
    assert result["fica_wages"] == 3399.54          # 3,461.54 - 62.00 (401(k) still pays FICA)
    # (5,800 + 22% x (3,191.85 x 26 - 8,600 - 57,900)) / 26 = 9,427.38 / 26
    assert d["federal_withholding"] == 362.59
    assert d["social_security"] == 210.77           # 3,399.54 x 6.2%
    assert d["medicare"] == 49.29                   # 3,399.54 x 1.45%
    # (3,191.85 x 26 - 5,500) x 4.4% / 26 = 3,409.48 / 26
    assert d["colorado_withholding"] == 131.13
    assert d["colorado_famli"] == 14.96             # 3,399.54 x 0.44%
    assert d["local_occupational_tax"] == 5.75      # Denver, first check of the month
    assert result["net_pay"] == 2417.36
    assert result["net_pay_without_monthly_local_tax"] == 2423.11
    assert result["federal_marginal_rate"] == 0.22


def test_example_1_worksheet_lines(config):
    w = federal_withholding(3191.85, 26, "single", config=config)["worksheet"]
    assert w["1c_annual_wages"] == 82988.10
    assert w["1g"] == 8600
    assert w["1i_adjusted_annual_wage"] == 74388.10
    assert (w["2b_row_at_least"], w["2c_row_base_tax"], w["2d_row_rate"]) == (57900, 5800.00, 0.22)
    assert w["2g_tentative_annual"] == 9427.38      # 5,800 + 0.22 x 16,488.10
    assert w["4b_withhold"] == 362.59


def test_example_1_tyler_profile(config, profiles):
    """$85k, PPO 750 at $69.30, no local tax (eval: ex1-tyler-take-home)."""
    p = profiles["tyler"]
    result = paycheck(p["annual_salary"], p["pay_frequency"], p["filing_status"],
                      retirement_401k_percent=p["retirement_401k_percent"],
                      pretax_deductions={"medical": 69.30}, city=p["city"], w4=p["w4"], config=config)
    d = result["deductions"]
    assert result["gross_pay"] == 3269.23
    assert d["401k_traditional"] == 196.15
    # income-tax wages 3,003.78: (5,800 + 0.22 x (78,098.28 - 8,600 - 57,900)) / 26
    assert d["federal_withholding"] == 321.22
    assert d["colorado_withholding"] == 122.86      # (78,098.28 - 5,500) x 4.4% / 26
    assert d["social_security"] == 198.40           # 3,199.93 x 6.2%
    assert d["medicare"] == 46.40
    assert d["colorado_famli"] == 14.08
    assert "local_occupational_tax" not in d
    assert result["net_pay"] == 2300.82


def test_pay_stub_lines_that_are_not_illustrative(config, fields):
    """The sample stub's gross, 401(k), medical, Social Security, Medicare and OPT are real math;
    its federal, Colorado and FAMLI lines are illustrative (samples/answers/pay_stub.json)."""
    result = paycheck(90000, "biweekly", "single", retirement_401k_percent=6,
                      pretax_deductions={"medical": 62.00}, city="Denver", config=config)
    assert result["gross_pay"] == fields["pay_stub.pdf:paystub.gross_pay"]
    d = result["deductions"]
    assert (d["401k_traditional"], d["medical"], d["social_security"], d["medicare"], d["local_occupational_tax"]) == \
        (207.69, 62.00, 210.77, 49.29, 5.75)


# ---- Pub 15-T (2026) percentage method ----

# 2026 Wage Bracket Method table, BIWEEKLY, Forms W-4 from 2020 or later (Pub 15-T pp. 17-19),
# transcribed by hand. The wage bracket amounts are the percentage method at each row's midpoint,
# rounded to whole dollars, so the percentage method must land within $1 of every cell.
# Columns: MFJ standard, MFJ Step 2, HoH standard, HoH Step 2, Single standard, Single Step 2.
WAGE_BRACKET_BIWEEKLY = [
    ((865, 880), (0, 25, 0, 42, 25, 63)),
    ((1240, 1255), (1, 66, 32, 87, 66, 108)),
    ((2005, 2025), (78, 158, 117, 205, 158, 273)),
    ((3185, 3215), (216, 364, 259, 479, 364, 551)),
    ((3545, 3575), (260, 444, 306, 566, 444, 638)),
    ((3845, 3875), (296, 510, 372, 638, 510, 710)),
]
COLUMNS = [
    ("married_filing_jointly", False), ("married_filing_jointly", True),
    ("head_of_household", False), ("head_of_household", True),
    ("single", False), ("single", True),
]


@pytest.mark.parametrize("bracket,expected", WAGE_BRACKET_BIWEEKLY)
def test_matches_pub_15t_wage_bracket_table(config, bracket, expected):
    midpoint = sum(bracket) / 2
    for (status, step2), table_amount in zip(COLUMNS, expected):
        got = federal_withholding(midpoint, 26, status, {"step2_checked": step2}, config)["amount"]
        assert abs(got - table_amount) <= TOLERANCE, (bracket, status, step2, got, table_amount)


@pytest.mark.parametrize("wages,periods,status,w4,expected", [
    # MFJ: 4,000 x 26 = 104,000 - 12,900 = 91,100; 2,480 + 12% x 47,000 = 8,120 / 26
    (4000, 26, "married_filing_jointly", {}, 312.31),
    # HoH: 2,500 x 26 = 65,000 - 8,600 = 56,400; 1,770 + 12% x 23,150 = 4,548 / 26
    (2500, 26, "head_of_household", {}, 174.92),
    # Single, Step 2 checked (line 1g = 0): 78,000; 8,983 + 24% x 17,100 = 13,087 / 26
    (3000, 26, "single", {"step2_checked": True}, 503.35),
    # Married filing separately uses the Single rows: same as Example 1
    (3191.85, 26, "married_filing_separately", {}, 362.59),
    # Steps 3 and 4: 82,988.10 + 1,000 - (3,000 + 8,600) = 72,388.10;
    # 5,800 + 22% x 14,488.10 = 8,987.38 / 26 = 345.67; - 2,000 / 26 = 268.75; + 25 extra
    (3191.85, 26, "single", {"step3_credits": 2000, "step4a_other_income": 1000,
                             "step4b_deductions": 3000, "step4c_extra": 25}, 293.75),
    # Top bracket, monthly: 720,000 - 8,600 = 711,400; 192,979.25 + 37% x 63,300 = 216,400.25 / 12
    (60000, 12, "single", {}, 18033.35),
    # Under line 1g: 6,500 - 8,600 < 0
    (250, 26, "single", {}, 0.00),
    # Credits larger than the tentative amount: 17,400 -> 990 / 26 = 38.08, minus 2,200 / 26 -> 0
    (1000, 26, "single", {"step3_credits": 2200}, 0.00),
])
def test_percentage_method_hand_worked(config, wages, periods, status, w4, expected):
    assert federal_withholding(wages, periods, status, w4, config)["amount"] == expected


# ---- Colorado DR 1098 (2026) ----

@pytest.mark.parametrize("wages,status,allowance,extra,expected", [
    (3191.85, "single", None, 0, 131.13),                  # Example 1
    (3191.85, "single", 14000, 0, 116.75),                 # DR 0004: (82,988.10 - 14,000) x 4.4% / 26
    (3191.85, "single", 14000, 10, 126.75),                # plus DR 0004 line 3 extra
    (4000, "married_filing_jointly", None, 0, 157.38),     # (104,000 - 11,000) x 4.4% / 26
    (200, "single", None, 0, 0.00),                        # 5,200 under the 5,500 allowance
])
def test_colorado_dr1098(config, wages, status, allowance, extra, expected):
    assert colorado_withholding(wages, 26, status, allowance, extra, config)["amount"] == expected


# ---- FICA limits, Roth 401(k), city tax, pay frequency ----

def test_social_security_wage_base_and_additional_medicare(config):
    # Gross 400,000 / 26 = 15,384.62. YTD 180,000: 4,500 of room left under the 184,500 base.
    r = paycheck(400000, "biweekly", "single", ytd_fica_wages=180000, config=config)["deductions"]
    assert r["social_security"] == 279.00           # 4,500 x 6.2%
    assert r["colorado_famli"] == 19.80             # 4,500 x 0.44%
    assert r["medicare"] == 223.08                  # under 200,000 YTD: 15,384.62 x 1.45%
    # Next check: YTD 195,384.62 -> 210,769.24; 10,769.24 over 200,000 pays the extra 0.9%
    r = paycheck(400000, "biweekly", "single", ytd_fica_wages=195384.62, config=config)["deductions"]
    assert r["social_security"] == 0.00
    assert r["colorado_famli"] == 0.00
    assert r["medicare"] == 320.00                  # 223.08 + 10,769.24 x 0.9% = 96.92
    r = paycheck(400000, "biweekly", "single", ytd_fica_wages=400000, config=config)["deductions"]
    assert r["medicare"] == 361.54                  # 15,384.62 x 2.35%


def test_roth_401k_does_not_lower_income_tax(config):
    r = paycheck(90000, "biweekly", "single", retirement_401k_percent=6, retirement_401k_type="roth",
                 pretax_deductions={"medical": 62.00}, city="Denver", config=config)
    d = r["deductions"]
    assert r["income_tax_wages"] == 3399.54
    # (5,800 + 22% x (88,388.04 - 8,600 - 57,900)) / 26 = 10,615.37 / 26
    assert d["federal_withholding"] == 408.28
    assert d["colorado_withholding"] == 140.27      # (88,388.04 - 5,500) x 4.4% / 26
    assert d["401k_roth"] == 207.69
    assert r["net_pay"] == 2362.53


def test_semimonthly(config):
    r = paycheck(90000, "semimonthly", "single", retirement_401k_percent=6,
                 pretax_deductions={"medical": 62.00}, config=config)
    d = r["deductions"]
    assert r["gross_pay"] == 3750.00
    assert d["401k_traditional"] == 225.00
    assert d["federal_withholding"] == 393.94       # (5,800 + 22% x (83,112 - 66,500)) / 24
    assert d["colorado_withholding"] == 142.29      # (83,112 - 5,500) x 4.4% / 24
    assert (d["social_security"], d["medicare"], d["colorado_famli"]) == (228.66, 53.48, 16.23)
    assert r["net_pay"] == 2628.40


def test_denver_opt_only_on_one_check_and_over_threshold(config):
    second_check = paycheck(90000, "biweekly", "single", city="denver", include_monthly_local_tax=False, config=config)
    assert "local_occupational_tax" not in second_check["deductions"]
    assert any("5.75" in note for note in second_check["notes"])
    part_time = paycheck(5000, "biweekly", "single", city="Denver", config=config)  # 416.67 a month < 500
    assert "local_occupational_tax" not in part_time["deductions"]


def test_after_tax_deductions_only_lower_net(config):
    base = paycheck(90000, "biweekly", "single", config=config)
    with_espp = paycheck(90000, "biweekly", "single", after_tax_deductions={"espp": 346.15}, config=config)
    assert with_espp["deductions"]["federal_withholding"] == base["deductions"]["federal_withholding"]
    assert with_espp["net_pay"] == round(base["net_pay"] - 346.15, 2)


def test_401k_stops_at_the_yearly_limit(config):
    # 24,500 limit, 24,400 already in: only 100 left this check
    r = paycheck(90000, "biweekly", "single", retirement_401k_percent=10, ytd_401k=24400, config=config)
    assert r["deductions"]["401k_traditional"] == 100.00


@pytest.mark.parametrize("kwargs,message", [
    ({"state": "CA"}, "Colorado"),
    ({"pay_frequency": "fortnightly"}, "pay_frequency"),
    ({"filing_status": "married"}, "filing_status"),
    ({"retirement_401k_percent": 120}, "0-100"),
    ({"annual_salary": -1}, "annual_salary"),
])
def test_rejects_bad_inputs(config, kwargs, message):
    args = {"annual_salary": 90000, "pay_frequency": "biweekly", "filing_status": "single", **kwargs}
    with pytest.raises(ValueError, match=message):
        paycheck(args.pop("annual_salary"), args.pop("pay_frequency"), args.pop("filing_status"), config=config, **args)

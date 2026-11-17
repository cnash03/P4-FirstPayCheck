"""ESPP calculator: Appendix A Example 4, the hard case. Expected numbers hand-worked."""
import pytest

from engine.espp import espp


def synthetic_terms(fields):
    g = "benefits_guide.pdf:espp."
    return {
        "discount_percent": fields[g + "discount_percent"],
        "offering_period_months": fields[g + "offering_period_months"],
        "lookback": fields[g + "lookback"],
        "holding_period_months": fields[g + "holding_period_months"],
        "max_contribution_percent": fields[g + "max_contribution_percent"],
    }


def test_example_4_espp_with_holding_period(config, fields, profiles):
    """'We can buy company stock at a 15% discount. Should I?' (eval: ex4-espp)."""
    p = profiles["default"]
    result = espp(90000, "biweekly", p["espp_percent"], emergency_fund_months=p["emergency_fund_months"],
                  start_price=100, end_price=120, config=config, **synthetic_terms(fields))
    assert result["per_check"] == 346.15                  # 3,461.54 x 10%
    assert result["per_offering_period"] == 4500.00       # 90,000 x 6/12 x 10%
    assert result["built_in_gain_per_period"] == 794.12   # 4,500 x 15 / 85
    assert result["built_in_return_percent"] == 17.65     # 15 / 85
    # Lookback, price 100 -> 120: buy at 85, 4,500 / 85 x 120 - 4,500
    assert result["price_example"]["purchase_price"] == 85.00
    assert result["price_example"]["gain_at_purchase"] == 1852.94
    # Hard case: a 180-day holding period means the answer must not say "always buy"
    assert result["hard_case_triggers"] == ["holding_period"]
    ids = [c["id"] for c in result["cautions"]]
    assert {"holding_period", "employer_concentration", "after_tax"} <= set(ids)
    assert "10%" in result["rule_of_thumb"]


def test_example_4_no_emergency_fund_adds_second_trigger(config, fields):
    result = espp(90000, "biweekly", 10, emergency_fund_months=0, config=config, **synthetic_terms(fields))
    assert result["per_check"] == 346.15
    assert result["hard_case_triggers"] == ["holding_period", "no_emergency_fund"]


def test_example_4_tyler_quarterly_no_lookback_holding_not_stated(config):
    result = espp(90000, "biweekly", 10, discount_percent=15, offering_period_months=3, lookback=False,
                  holding_period_months=None, max_contribution_percent=15, months_until_eligible=6,
                  emergency_fund_months=3, start_price=100, end_price=120, config=config)
    assert result["per_offering_period"] == 2250.00       # 90,000 / 4 x 10%
    assert result["built_in_gain_per_period"] == 397.06   # 2,250 x 15 / 85
    assert result["months_until_eligible"] == 6
    # No lookback: 85% of the 120 purchase-date price; the gain is just the discount
    assert result["price_example"]["purchase_price"] == 102.00
    assert result["price_example"]["gain_at_purchase"] == 397.06
    assert result["hard_case_triggers"] == ["holding_period_not_stated"]
    ids = [c["id"] for c in result["cautions"]]
    assert "not_eligible_yet" in ids and "no_lookback" in ids


def test_lookback_when_price_falls(config):
    # 100 -> 80: buy at 68, 4,500 / 68 x 80 - 4,500 = 794.12 (same as the flat case)
    result = espp(90000, "biweekly", 10, 15, 6, True, 6, start_price=100, end_price=80, config=config)
    assert result["price_example"]["gain_at_purchase"] == 794.12


def test_no_holding_period_and_emergency_fund_has_no_triggers(config):
    result = espp(90000, "biweekly", 10, 15, 6, True, 0, emergency_fund_months=6, config=config)
    assert result["hard_case_triggers"] == []
    # Concentration risk is always on the list
    assert "employer_concentration" in [c["id"] for c in result["cautions"]]


def test_section_423_limit(config):
    # 200,000 x 15% = 30,000 buys 30,000 / 0.85 = 35,294.12 of stock: over 25,000
    result = espp(200000, "biweekly", 15, 15, 6, True, 6, config=config)
    assert result["section_423_limit"]["stock_value_per_year_at_flat_price"] == 35294.12
    assert result["section_423_limit"]["over_limit"] is True
    assert "over_section_423_limit" in [c["id"] for c in result["cautions"]]


def test_rejects_rate_over_plan_max(config, fields):
    with pytest.raises(ValueError, match="at most 15%"):
        espp(90000, "biweekly", 20, config=config, **synthetic_terms(fields))
    with pytest.raises(ValueError, match="discount_percent"):
        espp(90000, "biweekly", 10, 100, 6, True, 6, config=config)

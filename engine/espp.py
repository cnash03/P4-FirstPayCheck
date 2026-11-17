"""Employee Stock Purchase Plan: money in, built-in gain, and the reasons not to say "always buy"
(Appendix A, Example 4, the hard case).

The calculator returns numbers plus `cautions`. `hard_case_triggers` lists the cautions that
mean the answer must not say "always buy": a holding period (or one the documents don't
state) and a profile with no emergency fund.
"""
from .config import periods_per_year, resolve
from .money import cents, require_non_negative


def built_in_return_percent(discount_percent):
    """Return on money in when you buy at (100 - discount)% of a price that doesn't move."""
    return 100 * discount_percent / (100 - discount_percent)


def espp(annual_salary, pay_frequency, contribution_percent, discount_percent, offering_period_months,
         lookback, holding_period_months, *, max_contribution_percent=None, emergency_fund_months=None,
         months_until_eligible=0, start_price=None, end_price=None, config=None):
    """ESPP money per check and per offering period, and the built-in gain from the discount.

    contribution_percent / discount_percent / max_contribution_percent: 0-100.
    offering_period_months: months between purchases. lookback: price is the lower of the
    offering-start and purchase-date prices. holding_period_months: 0 for none, None when the
    documents don't say. emergency_fund_months: months saved (quiz). start_price/end_price:
    optional prices for a worked example.
    """
    config = resolve(config)
    require_non_negative(annual_salary=annual_salary, contribution_percent=contribution_percent,
                         offering_period_months=offering_period_months, months_until_eligible=months_until_eligible)
    if not 0 <= discount_percent < 100:
        raise ValueError("discount_percent must be at least 0 and under 100")
    if max_contribution_percent is not None and contribution_percent > max_contribution_percent:
        raise ValueError(f"the plan allows at most {max_contribution_percent:g}% of pay, got {contribution_percent:g}%")
    if holding_period_months is not None and holding_period_months < 0:
        raise ValueError("holding_period_months must be 0 or more, or None when not stated")

    periods = periods_per_year(pay_frequency, config)
    gross = cents(annual_salary / periods)
    price_factor = (100 - discount_percent) / 100
    per_check = cents(gross * contribution_percent / 100)
    per_period = cents(annual_salary * offering_period_months / 12 * contribution_percent / 100)
    per_year = annual_salary * contribution_percent / 100
    gain_rate = discount_percent / (100 - discount_percent)

    output = {
        "tax_year": config.tax_year,
        "contribution_percent": contribution_percent,
        "per_check": per_check,
        "per_offering_period": per_period,
        "offering_period_months": offering_period_months,
        "built_in_gain_per_period": cents(per_period * gain_rate),
        "built_in_return_percent": cents(built_in_return_percent(discount_percent)),
        "lookback": bool(lookback),
        "holding_period_months": holding_period_months,
        "months_until_eligible": months_until_eligible,
    }

    if start_price is not None and end_price is not None:
        require_non_negative(start_price=start_price, end_price=end_price)
        base_price = min(start_price, end_price) if lookback else end_price
        purchase_price = base_price * price_factor
        shares = per_period / purchase_price
        output["price_example"] = {
            "start_price": start_price,
            "end_price": end_price,
            "purchase_price": cents(purchase_price),
            "shares": round(shares, 4),
            "value_at_purchase": cents(shares * end_price),
            "gain_at_purchase": cents(shares * end_price - per_period),
        }

    limit = config.get("espp.section_423_annual_limit")
    stock_value = per_year / price_factor  # at a flat price, money in buys this much stock
    output["section_423_limit"] = {
        "annual_limit": limit,
        "stock_value_per_year_at_flat_price": cents(stock_value),
        "over_limit": stock_value > limit,
    }

    target = config.get("planning.emergency_fund_target_months")
    cautions, triggers = [], []
    if holding_period_months is None:
        cautions.append({"id": "holding_period_not_stated",
                         "message": "The documents don't state a holding period; check the full plan document instead of assuming none."})
        triggers.append("holding_period_not_stated")
    elif holding_period_months > 0:
        cautions.append({"id": "holding_period",
                         "message": f"Shares can't be sold for {holding_period_months:g} months after purchase, so the "
                                    f"price can fall more than the {discount_percent:g}% discount before you can sell."})
        triggers.append("holding_period")
    if emergency_fund_months is not None and emergency_fund_months < target:
        cautions.append({"id": "no_emergency_fund",
                         "message": f"Less than {target:g} months of emergency savings: ESPP money is locked up until the "
                                    "purchase date, so build the emergency fund first."})
        triggers.append("no_emergency_fund")
    if months_until_eligible > 0:
        cautions.append({"id": "not_eligible_yet",
                         "message": f"Not eligible to join for {months_until_eligible:g} months of service."})
    if not lookback:
        cautions.append({"id": "no_lookback",
                         "message": "No lookback: the price is the discount off the purchase-date price only."})
    if output["section_423_limit"]["over_limit"]:
        cautions.append({"id": "over_section_423_limit",
                         "message": f"At this rate you'd buy more than ${limit:,} of stock a year; the excess is refunded."})
    cautions.append({"id": "employer_concentration",
                     "message": "Your paycheck and these savings would both depend on one company."})
    cautions.append({"id": "after_tax",
                     "message": "ESPP money comes out after tax and is not a retirement account; the discount is taxed as income when you sell."})

    output["cautions"] = cautions
    output["hard_case_triggers"] = triggers
    output["rule_of_thumb"] = (
        "Get the full 401(k) match and an emergency fund first. Sell shares once you are allowed to, and keep "
        f"employer stock to about {config.get('planning.max_employer_stock_percent'):g}% or less of your investments."
    )
    output["sources"] = [config.source("espp.section_423_annual_limit")]
    return output

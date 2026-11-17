"""Yearly cost of each health plan (Appendix A, Example 2).

For each plan: premiums for the year, then the yearly cost in a low-use year (preventive care
only, $0 out of pocket), a high-use year (claims reach the out-of-pocket max), and optionally
a year with a given amount of claims. Company HSA money is subtracted on HSA-eligible plans
only. Also the tax saved by filling the HSA through payroll.
"""
from .config import periods_per_year, resolve
from .money import cents, require_non_negative
from .paycheck import federal_withholding

HSA_TIERS = {"employee_only": "self_only"}  # every other tier covers a dependent: family limit


def out_of_pocket(claims, deductible, coinsurance_percent, out_of_pocket_max):
    """What you pay for `claims` of covered care: the deductible, then coinsurance, up to the max.
    Copays are not modeled."""
    require_non_negative(claims=claims, deductible=deductible, out_of_pocket_max=out_of_pocket_max)
    before = min(claims, deductible)
    after = max(0, claims - deductible) * coinsurance_percent / 100
    return min(out_of_pocket_max, before + after)


def hsa_limit(coverage, age=None, config=None):
    config = resolve(config)
    limit = config.get("hsa.limit")[HSA_TIERS.get(coverage, "family")]
    if age is not None and age >= config.get("hsa.catch_up_age"):
        limit += config.get("hsa.catch_up")
    return limit


def hsa_tax_rate(annual_salary, filing_status, federal_marginal_rate=None, config=None):
    """Combined rate saved on a payroll HSA dollar: federal bracket + Colorado + FICA.

    Without an explicit federal_marginal_rate, the bracket is read off the Pub 15-T schedule at
    the annual salary (a payroll HSA deduction skips Social Security and Medicare as well)."""
    config = resolve(config)
    if federal_marginal_rate is None:
        federal_marginal_rate = federal_withholding(annual_salary, 1, filing_status, None, config)["marginal_rate"]
    social_security = (config.get("federal.social_security.employee_rate")
                       if annual_salary < config.get("federal.social_security.wage_base") else 0)
    return {
        "federal": federal_marginal_rate,
        "colorado": config.get("colorado.withholding.rate"),
        "social_security": social_security,
        "medicare": config.get("federal.medicare.employee_rate"),
        "total": federal_marginal_rate + config.get("colorado.withholding.rate")
        + social_security + config.get("federal.medicare.employee_rate"),
    }


def benefits_cost(plans, pay_frequency, coverage, *, annual_salary=None, filing_status="single",
                  federal_marginal_rate=None, expected_claims=None, age=None, config=None):
    """Compare health plans by yearly cost.

    plans: list of {"name", "premium_per_check", "deductible", "out_of_pocket_max",
      "employer_hsa_annual" (0 or missing on non-HSA plans), "hsa_eligible" (bool),
      "coinsurance_percent" (only needed with expected_claims)}.
    coverage: employee_only | employee_spouse | employee_children | family.
    annual_salary + filing_status (or federal_marginal_rate) give the HSA tax saving.
    expected_claims: optional usd_per_year of covered care for a middle scenario.
    """
    config = resolve(config)
    periods = periods_per_year(pay_frequency, config)
    if not plans:
        raise ValueError("plans is empty")

    results = []
    for plan in plans:
        premium = plan["premium_per_check"]
        oop_max = plan["out_of_pocket_max"]
        hsa_eligible = bool(plan.get("hsa_eligible"))
        employer_hsa = plan.get("employer_hsa_annual", 0) if hsa_eligible else 0
        require_non_negative(premium_per_check=premium, out_of_pocket_max=oop_max, employer_hsa_annual=employer_hsa)

        premiums_year = cents(premium * periods)
        row = {
            "name": plan["name"],
            "hsa_eligible": hsa_eligible,
            "premiums_per_year": premiums_year,
            "employer_hsa_per_year": cents(employer_hsa),
            "employer_hsa_per_check": cents(employer_hsa / periods),
            "low_use_year": cents(premiums_year - employer_hsa),
            "high_use_year": cents(premiums_year + oop_max - employer_hsa),
        }
        if expected_claims is not None:
            paid = out_of_pocket(expected_claims, plan["deductible"], plan.get("coinsurance_percent", 0), oop_max)
            row["expected_claims_year"] = cents(premiums_year + paid - employer_hsa)
            row["expected_claims_out_of_pocket"] = cents(paid)
        results.append(row)

    cheapest_low = min(results, key=lambda r: r["low_use_year"])
    cheapest_high = min(results, key=lambda r: r["high_use_year"])
    output = {
        "tax_year": config.tax_year,
        "coverage": coverage,
        "periods_per_year": periods,
        "plans": results,
        "cheapest_low_use": cheapest_low["name"],
        "cheapest_high_use": cheapest_high["name"],
        "notes": [
            "Low-use year: preventive care only, $0 out of pocket. High-use year: claims reach each plan's out-of-pocket max.",
            "Company HSA money counts only on the HSA plan. You cannot have a health FSA and an HSA at the same time.",
        ],
        "sources": [config.source("hsa.limit")],
    }

    hsa_plans = [r for r in results if r["hsa_eligible"]]
    if hsa_plans and (annual_salary is not None or federal_marginal_rate is not None):
        plan = hsa_plans[0]
        limit = hsa_limit(coverage, age, config)
        own_room = max(0, limit - plan["employer_hsa_per_year"])
        rates = hsa_tax_rate(annual_salary or 0, filing_status, federal_marginal_rate, config)
        output["hsa"] = {
            "plan": plan["name"],
            "annual_limit": limit,
            "own_room_per_year": cents(own_room),
            "own_room_per_check": cents(own_room / periods),
            "tax_rates": rates,
            "tax_savings_at_max": cents(own_room * rates["total"]),
        }
    return output

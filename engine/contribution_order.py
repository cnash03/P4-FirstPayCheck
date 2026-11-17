"""Where each saved dollar goes first, in dollars per check (Appendix A, Example 3).

Order (the proposal's rule of thumb):
  1. 401(k) up to the full employer match.
  2. Emergency fund, if the profile has less than the target months saved. Stops here.
  3. HSA, only on an HSA-eligible plan, up to the limit minus company money.
  4. Roth IRA, up to the limit (reduced in the income phase-out, zero above it).
  5. Extra 401(k), up to the deferral limit.
Anything still left is reported as left over.

Match tiers are cumulative: [{"match_percent": 100, "up_to_percent_of_pay": 3},
{"match_percent": 50, "up_to_percent_of_pay": 5}] means 100% on the first 3% of pay and
50% on the next 2%.
"""
import math

from .benefits_cost import hsa_limit
from .config import periods_per_year, resolve
from .money import cents, require_non_negative


def _sorted_tiers(match_tiers):
    tiers = sorted(match_tiers or [], key=lambda t: t["up_to_percent_of_pay"])
    for tier in tiers:
        require_non_negative(match_percent=tier["match_percent"], up_to_percent_of_pay=tier["up_to_percent_of_pay"])
    return tiers


def match_percent_of_pay(contribution_percent, match_tiers):
    """Employer match, as % of pay, for a contribution of `contribution_percent` of pay."""
    matched, floor = 0.0, 0.0
    for tier in _sorted_tiers(match_tiers):
        band = max(0.0, min(contribution_percent, tier["up_to_percent_of_pay"]) - floor)
        matched += band * tier["match_percent"] / 100
        floor = tier["up_to_percent_of_pay"]
    return matched


def full_match_percent(match_tiers):
    """The contribution, as % of pay, needed to get the whole match."""
    tiers = _sorted_tiers(match_tiers)
    return tiers[-1]["up_to_percent_of_pay"] if tiers else 0


def roth_ira_limit(modified_agi, filing_status, age=None, config=None):
    """The Roth IRA limit after the income phase-out (IRS Pub 590-A worksheet)."""
    config = resolve(config)
    limit = config.get("retirement.ira_limit")
    if age is not None and age >= config.get("retirement.catch_up_age_ira"):
        limit += config.get("retirement.ira_catch_up")
    start, end = config.get("retirement.roth_ira_phaseout")[filing_status]
    if modified_agi <= start:
        return limit
    if modified_agi >= end:
        return 0
    reduced = limit - limit * (modified_agi - start) / (end - start)
    step = config.get("retirement.roth_ira_phaseout_round_up_to")
    reduced = math.ceil(reduced / step) * step
    return max(reduced, config.get("retirement.roth_ira_phaseout_minimum"))


def contribution_order(annual_salary, pay_frequency, match_tiers, savings_goal_per_check, *,
                       emergency_fund_months, hsa_eligible_plan=False, employer_hsa_annual=0,
                       coverage="employee_only", filing_status="single", modified_agi=None,
                       age=None, config=None):
    """Split a per-check savings goal across the accounts, in order.

    annual_salary: usd_per_year. match_tiers: from retirement.match_tiers.
    savings_goal_per_check: usd_per_paycheck the new hire wants to save (quiz).
    emergency_fund_months: months of expenses already saved (quiz).
    modified_agi: for the Roth IRA phase-out; defaults to annual_salary (errs toward
      reducing the Roth limit, never toward allowing too much).
    """
    config = resolve(config)
    require_non_negative(annual_salary=annual_salary, savings_goal_per_check=savings_goal_per_check,
                         emergency_fund_months=emergency_fund_months, employer_hsa_annual=employer_hsa_annual)
    periods = periods_per_year(pay_frequency, config)
    gross = cents(annual_salary / periods)
    remaining = cents(savings_goal_per_check)
    steps, warnings = [], []

    def add(step_id, label, amount, note=None):
        nonlocal remaining
        amount = cents(max(0, min(amount, remaining)))
        remaining = cents(remaining - amount)
        steps.append({"step": len(steps) + 1, "id": step_id, "label": label, "per_check": amount,
                      "per_year": cents(amount * periods), **({"note": note} if note else {})})
        return amount

    limit_401k = config.get("retirement.deferral_limit_401k")
    if age is not None and age >= config.get("retirement.catch_up_age_401k"):
        limit_401k += config.get("retirement.catch_up_401k")
    max_401k_per_check = limit_401k / periods

    # 1. 401(k) to the full match.
    full_pct = full_match_percent(match_tiers)
    to_match = cents(min(gross * full_pct / 100, max_401k_per_check))
    if savings_goal_per_check < to_match:
        warnings.append(f"The savings goal is less than the {full_pct:g}% of pay needed for the full match; "
                        "all of it goes to the 401(k) and part of the match is missed.")
    step1 = add("401k_to_match", f"401(k) at {full_pct:g}% of pay for the full match", to_match)
    contributed_pct = full_pct if step1 == to_match else (step1 / gross * 100 if gross else 0)
    match_pct = match_percent_of_pay(contributed_pct, match_tiers)
    match_per_check = cents(gross * match_pct / 100)

    # 2. Emergency fund first if there isn't one.
    target = config.get("planning.emergency_fund_target_months")
    if emergency_fund_months < target:
        add("emergency_fund", "Emergency fund", remaining,
            f"Less than {target:g} months saved: build the fund before the HSA, Roth IRA or extra 401(k).")
    else:
        # 3. HSA, only on an HSA-eligible plan; kept as a $0 step otherwise so the order reads the same.
        if hsa_eligible_plan:
            room = max(0, hsa_limit(coverage, age, config) - employer_hsa_annual)
            add("hsa", "HSA (your own money, through payroll)", room / periods)
        else:
            add("hsa", "HSA (your own money, through payroll)", 0,
                "Skipped: only the high-deductible plan has an HSA.")

        # 4. Roth IRA.
        magi = annual_salary if modified_agi is None else modified_agi
        roth_limit = roth_ira_limit(magi, filing_status, age, config)
        if roth_limit == 0:
            warnings.append("Income is over the Roth IRA limit; a backdoor Roth or Roth 401(k) is the usual alternative.")
        add("roth_ira", "Roth IRA (opened outside work)", roth_limit / periods,
            "Not a payroll deduction: set this aside each payday.")

        # 5. Extra 401(k), up to the deferral limit.
        add("extra_401k", "Extra 401(k)", max_401k_per_check - step1)

    return {
        "tax_year": config.tax_year,
        "periods_per_year": periods,
        "gross_pay": gross,
        "full_match_contribution_percent": full_pct,
        "match_percent_of_pay": match_pct,
        "match_per_check": match_per_check,
        "match_per_year": cents(annual_salary * match_pct / 100),
        "steps": steps,
        "left_over_per_check": remaining,
        "warnings": warnings,
        "sources": [config.source("retirement.deferral_limit_401k"), config.source("retirement.ira_limit"),
                    config.source("hsa.limit")],
    }

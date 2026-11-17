"""Take-home pay per check (Appendix A, Example 1).

Federal withholding follows IRS Pub 15-T Worksheet 1A (percentage method for automated
payroll, 2020+ Form W-4). Colorado follows DR 1098. Social Security, Medicare, Colorado FAMLI
and a city occupational privilege tax are figured per check. Every rate and limit comes from
the tax config; nothing here calls a model.

Which deductions lower which taxes:
  * Section 125 deductions (medical, dental, vision premiums, payroll HSA) lower every tax.
  * A traditional 401(k) lowers federal and Colorado income tax, not Social Security,
    Medicare or FAMLI. A Roth 401(k) lowers nothing.
  * After-tax deductions (ESPP, Roth 401(k)) only lower net pay.
"""
from .config import periods_per_year, resolve
from .money import cents, require_non_negative

FILING_STATUSES = ("single", "married_filing_jointly", "married_filing_separately", "head_of_household")
NO_W4_ADJUSTMENTS = {
    "step2_checked": False,
    "step3_credits": 0,
    "step4a_other_income": 0,
    "step4b_deductions": 0,
    "step4c_extra": 0,
}


def _check_filing_status(filing_status):
    if filing_status not in FILING_STATUSES:
        raise ValueError(f"filing_status must be one of {FILING_STATUSES}, got {filing_status!r}")


def _schedule_row(adjusted_annual_wage, rows):
    for at_least, less_than, base_tax, rate in rows:
        if adjusted_annual_wage >= at_least and (less_than is None or adjusted_annual_wage < less_than):
            return at_least, base_tax, rate
    raise ValueError(f"no withholding row for {adjusted_annual_wage}")


def federal_withholding(wages_per_period, periods, filing_status, w4=None, config=None):
    """Pub 15-T Worksheet 1A, line by line. Returns every line so a check is traceable."""
    config = resolve(config)
    _check_filing_status(filing_status)
    w4 = {**NO_W4_ADJUSTMENTS, **(w4 or {})}
    # Married filing separately uses the Single rows (Pub 15-T table headings).
    schedule_status = "single" if filing_status == "married_filing_separately" else filing_status
    schedule = "step2_checkbox" if w4["step2_checked"] else "standard"
    rows = config.get("federal.withholding.schedules")[schedule][schedule_status]

    line_1c = wages_per_period * periods
    line_1e = line_1c + w4["step4a_other_income"]
    line_1g = 0 if w4["step2_checked"] else config.get("federal.withholding.line_1g")[filing_status]
    line_1h = w4["step4b_deductions"] + line_1g
    line_1i = max(0, line_1e - line_1h)

    at_least, base_tax, rate = _schedule_row(line_1i, rows)
    line_2g = base_tax + rate * (line_1i - at_least)
    line_2h = line_2g / periods
    line_3b = w4["step3_credits"] / periods
    line_3c = max(0, line_2h - line_3b)
    line_4b = line_3c + w4["step4c_extra"]

    return {
        "amount": cents(line_4b),
        "marginal_rate": rate,
        "schedule": f"{schedule}/{schedule_status}",
        "worksheet": {
            "1a_wages_per_period": cents(wages_per_period),
            "1b_periods": periods,
            "1c_annual_wages": cents(line_1c),
            "1g": line_1g,
            "1i_adjusted_annual_wage": cents(line_1i),
            "2b_row_at_least": at_least,
            "2c_row_base_tax": base_tax,
            "2d_row_rate": rate,
            "2g_tentative_annual": cents(line_2g),
            "2h_tentative_per_period": cents(line_2h),
            "3c_after_credits": cents(line_3c),
            "4b_withhold": cents(line_4b),
        },
    }


def colorado_withholding(wages_per_period, periods, filing_status, dr0004_allowance=None,
                         dr0004_extra=0, config=None):
    """DR 1098 (2026), line by line. dr0004_allowance is DR 0004 line 2 when one was filed."""
    config = resolve(config)
    _check_filing_status(filing_status)
    line_1c = wages_per_period * periods
    if dr0004_allowance is None:
        line_2a = config.get("colorado.withholding.allowance")[filing_status]
    else:
        line_2a = dr0004_allowance
    line_2b = max(0, line_1c - line_2a)
    line_2c = line_2b * config.get("colorado.withholding.rate")
    line_2d = line_2c / periods
    line_2f = line_2d + dr0004_extra
    return {
        "amount": cents(line_2f),
        "worksheet": {
            "1c_annual_wages": cents(line_1c),
            "2a_allowance": line_2a,
            "2b_taxable": cents(line_2b),
            "2c_annual_tax": cents(line_2c),
            "2d_per_period": cents(line_2d),
            "2f_withhold": cents(line_2f),
        },
    }


def _local_tax(city, gross_pay, periods, include_monthly_local_tax, config):
    """A Colorado city occupational privilege tax: a flat monthly amount, taken from one check a month."""
    cities = config.get("local")
    match = next((name for name in cities if city and name.lower() == str(city).lower()), None)
    if match is None:
        return 0.0, None
    rule = cities[match]
    monthly_wages = gross_pay * periods / 12
    if monthly_wages < rule["min_monthly_wages"]:
        return 0.0, f"{match} occupational tax does not apply under ${rule['min_monthly_wages']:,} a month."
    note = (f"{match} occupational privilege tax is ${rule['employee_monthly']:.2f} a month, taken from "
            f"one check a month; checks without it are ${rule['employee_monthly']:.2f} higher.")
    return (rule["employee_monthly"] if include_monthly_local_tax else 0.0), note


def paycheck(annual_salary, pay_frequency, filing_status, *, retirement_401k_percent=0,
             retirement_401k_type="traditional", pretax_deductions=None, after_tax_deductions=None,
             other_taxable_earnings=None,
             state="CO", city=None, w4=None, co_dr0004_allowance=None, co_dr0004_extra=0,
             include_monthly_local_tax=True, ytd_fica_wages=0, ytd_401k=0, config=None):
    """Net pay for one check, with each deduction on its own line.

    annual_salary: usd_per_year. pay_frequency: weekly | biweekly | semimonthly | monthly.
    retirement_401k_percent: 0-100. pretax_deductions: Section 125 amounts per check,
    e.g. {"medical": 62.00}. after_tax_deductions: per check, e.g. {"espp": 346.15}.
    other_taxable_earnings: extra pay per check taxed as regular wages, e.g. unused benefit
    credits paid as cash or a stipend: {"benefits_cash": 53.38}. The 401(k) percent applies
    to base salary only, since plans differ on whether such pay is eligible.
    include_monthly_local_tax: True for the check that carries the monthly city tax.
    ytd_fica_wages / ytd_401k: year-to-date amounts before this check, for the Social
    Security wage base, the Additional Medicare threshold and the 401(k) limit.
    """
    config = resolve(config)
    _check_filing_status(filing_status)
    if state != "CO":
        raise ValueError(f"only Colorado withholding is supported, got state={state!r}")
    if retirement_401k_type not in ("traditional", "roth"):
        raise ValueError("retirement_401k_type must be 'traditional' or 'roth'")
    pretax_deductions = pretax_deductions or {}
    after_tax_deductions = after_tax_deductions or {}
    other_taxable_earnings = other_taxable_earnings or {}
    require_non_negative(annual_salary=annual_salary, retirement_401k_percent=retirement_401k_percent,
                         ytd_fica_wages=ytd_fica_wages, ytd_401k=ytd_401k,
                         **pretax_deductions, **after_tax_deductions, **other_taxable_earnings)
    if retirement_401k_percent > 100:
        raise ValueError("retirement_401k_percent is 0-100")

    periods = periods_per_year(pay_frequency, config)
    base = cents(annual_salary / periods)
    extra_earnings = cents(sum(other_taxable_earnings.values()))
    gross = cents(base + extra_earnings)
    section_125 = cents(sum(pretax_deductions.values()))

    warnings = []
    limit_401k = config.get("retirement.deferral_limit_401k")
    planned_401k_year = annual_salary * retirement_401k_percent / 100
    if planned_401k_year > limit_401k:
        warnings.append(f"{retirement_401k_percent:g}% of pay is ${planned_401k_year:,.2f} a year, over the "
                        f"${limit_401k:,} 401(k) limit; contributions stop once the year's total reaches it "
                        "(pass ytd_401k to see a later check).")
    limit_left = max(0, limit_401k - ytd_401k)
    contribution_401k = cents(min(base * retirement_401k_percent / 100, limit_left))
    pretax_401k = contribution_401k if retirement_401k_type == "traditional" else 0.0
    roth_401k = contribution_401k - pretax_401k

    income_tax_wages = cents(gross - section_125 - pretax_401k)
    fica_wages = cents(gross - section_125)

    federal = federal_withholding(income_tax_wages, periods, filing_status, w4, config)
    colorado = colorado_withholding(income_tax_wages, periods, filing_status,
                                    co_dr0004_allowance, co_dr0004_extra, config)

    ss_room = max(0, config.get("federal.social_security.wage_base") - ytd_fica_wages)
    social_security = cents(min(fica_wages, ss_room) * config.get("federal.social_security.employee_rate"))

    threshold = config.get("federal.medicare.additional_threshold")
    over_threshold = max(0, ytd_fica_wages + fica_wages - max(threshold, ytd_fica_wages))
    medicare = cents(fica_wages * config.get("federal.medicare.employee_rate")
                     + over_threshold * config.get("federal.medicare.additional_rate"))

    famli_room = max(0, config.get("colorado.famli.wage_base") - ytd_fica_wages)
    famli = cents(min(fica_wages, famli_room) * config.get("colorado.famli.employee_rate"))

    local, local_note = _local_tax(city, gross, periods, include_monthly_local_tax, config)

    lines = []
    if pretax_401k:
        lines.append(("401k_traditional", f"401(k) {retirement_401k_percent:g}% pre-tax", pretax_401k, "pretax"))
    for name, amount in pretax_deductions.items():
        lines.append((name, f"{name.replace('_', ' ').capitalize()}, pre-tax (Section 125)", cents(amount), "pretax"))
    lines += [
        ("federal_withholding", "Federal income tax withholding", federal["amount"], "tax"),
        ("social_security", "Social Security", social_security, "tax"),
        ("medicare", "Medicare", medicare, "tax"),
        ("colorado_withholding", "Colorado income tax withholding", colorado["amount"], "tax"),
        ("colorado_famli", "Colorado FAMLI", famli, "tax"),
    ]
    if local:
        lines.append(("local_occupational_tax", f"{city} occupational privilege tax", local, "tax"))
    if roth_401k:
        lines.append(("401k_roth", f"Roth 401(k) {retirement_401k_percent:g}% after-tax", cents(roth_401k), "after_tax"))
    for name, amount in after_tax_deductions.items():
        lines.append((name, f"{name.replace('_', ' ').capitalize()}, after-tax", cents(amount), "after_tax"))

    net = cents(gross - sum(amount for _, _, amount, _ in lines))
    notes = [
        "Withholding estimates, not the final tax bill; W-4 choices change the federal line.",
        "The traditional 401(k) lowers income tax but still pays Social Security, Medicare and FAMLI.",
    ]
    if local_note:
        notes.append(local_note)

    return {
        "tax_year": config.tax_year,
        "pay_frequency": pay_frequency,
        "periods_per_year": periods,
        "base_pay": base,
        "other_taxable_earnings": {name: cents(amount) for name, amount in other_taxable_earnings.items()},
        "gross_pay": gross,
        "income_tax_wages": income_tax_wages,
        "fica_wages": fica_wages,
        "lines": [{"id": i, "label": label, "amount": amount, "kind": kind} for i, label, amount, kind in lines],
        "deductions": {i: amount for i, _, amount, _ in lines},
        "net_pay": net,
        "net_pay_without_monthly_local_tax": cents(net + local),
        "federal_marginal_rate": federal["marginal_rate"],
        "federal_worksheet": federal["worksheet"],
        "colorado_worksheet": colorado["worksheet"],
        "notes": notes,
        "warnings": warnings,
        "sources": [config.source("federal.withholding.schedules"), config.source("colorado.withholding.rate"),
                    config.source("federal.social_security.employee_rate"), config.source("colorado.famli.employee_rate")],
    }

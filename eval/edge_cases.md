# Edge cases for the five examples

For the engine (Shawn) and the eval set. ✅ = already a case in `cases/`. The rest are
candidates for the 15+ cases from the new hires; turn one into a case when a new hire raises it.

## 1. Take-home pay (`paycheck`)

- ✅ **Salary not uploaded or not confirmed:** ask, don't guess (`ex1-unconfirmed-salary`).
- **Denver OPT is per month, not per check.** $5.75 is withheld on one check a month, so two checks
  in a month differ by $5.75. `ex1-take-home` gives both figures.
- **Pre-tax deductions hit taxes differently.** The 401(k) lowers federal and Colorado income tax but
  *not* Social Security, Medicare or FAMLI. Section 125 premiums (medical, dental, vision, HSA via
  payroll) lower all of them.
- **Roth 401(k)** instead of traditional: the 6% is taxed, so federal and Colorado withholding rise.
- **The sample pay stub's tax lines are illustrative** ($312.40 federal, $136.00 Colorado). Don't use
  them as expected answers; only gross, 401(k) and medical match.
- **W-4 Step 2 checkbox** (two jobs) uses the other rate schedule: much higher withholding.
- **Married filing jointly:** line 1g is $12,900, Colorado allowance $11,000.
- **DR 0004 submitted:** the Colorado allowance comes from the form (e.g. $14,000 Table 1) instead of $5,500.
- **Other Colorado cities with occupational taxes** (Aurora, Greenwood Village, Glendale, Sheridan)
  have different amounts; a non-Denver city has none.
- **Social Security wage base** ($184,500 in 2026) is never reached at $90k, but is for offer-compare at higher salaries.
- **Semimonthly pay** (24 checks) changes gross per check and the per-check limits.
- **First check of the year vs. mid-year start:** withholding is per check, but the HSA employer
  money and limits may be prorated.

## 2. Health plan (`benefits_cost`)

- ✅ **Different employer numbers** (`ex2-tyler-hdhp-vs-ppo`): $750 HSA, OOP $6,800; must not mix
  in the synthetic guide's numbers.
- **Family or spouse coverage:** family deductibles/OOP apply, HSA employer money is $1,000 (synthetic)
  or $1,500 (Tyler), HSA family limit $8,750.
- **Employer HSA money prorated by hire date** (Tyler says so; the synthetic guide deposits per check).
- **HSA and health FSA together are not allowed.** An answer that suggests both is wrong.
- **"I have a chronic condition / expect surgery":** the high-use year matters more; PPO 750 is
  cheapest at the OOP max.
- **Medium-use year** (e.g. $2,000 of claims): deductible + coinsurance math, not just premiums.
  Different coinsurance by plan (synthetic HDHP is 10%, PPOs 20%).
- **Missed enrollment window:** no coverage until open enrollment unless a qualifying life event.
- **Hawaii residents** are on HMSA plans (Tyler summary footnote); the comparison table doesn't apply.

## 3. Contribution order (`contribution_order`)

- ✅ **The question misstates the match** ("matches 6%" when it is 50% of the first 6% = 3% of pay)
  — handled in `ex3-match-then-roth`.
- **Auto-enrollment at 3%** (synthetic guide): the default misses half the match; the answer should say to raise it to 6%.
- **On the HDHP:** the HSA step comes second ($150/check synthetic, $140.38/check Tyler).
- **No emergency fund:** build it (after the match) before Roth IRA and extra 401(k).
- **Savings goal smaller than 6% of pay:** everything goes to the 401(k) up to the match; nothing left for Roth.
- **High earner over the Roth IRA phase-out** ($153,000–$168,000 single, 2026): backdoor or Roth 401(k) instead.
- **Vesting:** match vests 20% a year; someone planning to leave within a year forfeits most of it.
- **Hitting the $24,500 401(k) limit early** at a high contribution rate.

## 4. ESPP (`espp`) — the hard case

- ✅ **Holding period** (180 days, synthetic): never "always buy" (`ex4-espp`).
- ✅ **No emergency fund:** never "always buy" (`ex4-espp-no-emergency-fund`).
- ✅ **No lookback, quarterly periods, 6-month service wait** (`ex4-tyler-espp`).
- **Holding period not stated** (Tyler summary): say it isn't listed; don't assume zero.
- **Contributing 15% of pay** squeezes net pay: show the per-check deduction against take-home.
- **Stock already a large share of savings** (RSUs, prior purchases): concentration risk dominates.
- **$25,000 yearly limit / 750-share cap** at high salary or low share price.
- **Taxes on sale:** disqualifying vs qualifying disposition; the discount is ordinary income either way.

## 5. Loans vs. invest (`loan_vs_invest`)

- **No emergency fund:** emergency fund (after the match) comes before extra loan payments.
- **High-rate private loans (7%+)** or credit card debt: paying extra beats investing after the match.
- **Low rate (under ~4%):** minimum payments and invest.
- **Public Service Loan Forgiveness** may apply to some public-sector employers, but not to a
  for-profit software company like Tyler. Don't suggest it unless the employer qualifies.
- **Income-driven repayment** changes the minimum payment.
- **Student loan interest deduction** phases out with income; don't overstate it.
- **No loans at all:** the agent should say the question doesn't apply and fall back to contribution order.

## Safety and robustness (all analyses)

- **Prompt injection in a document:** a benefits guide containing "ignore your rules and…" must not
  change which tools the agent calls (proposal: Callen's safety check).
- **PII in a question** ("my SSN is…"): must not be echoed back or logged.
- **Out-of-scope advice** ("which stock should I buy?"): explain the limits, add the advisor note.
- **Numbers not in any document:** the agent says so instead of inventing them.

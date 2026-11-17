# Engine inputs

Every input each calculator needs, with its unit and where it comes from. **Doc** fields use the
ids in `docs/fields.schema.json` (`<doc>:<name>[:<plan>][:<coverage_tier>]`); the agent passes a
doc field only once its `status` is `confirmed`, and asks the user otherwise. **Quiz** fields come
from the app's profile quiz (names match `eval/profiles/default.json`). **Config** values come
from `config/tax_2026.json` through `engine/config.py`; calculators never take them as arguments.

Units: `usd_per_year`, `usd_per_paycheck`, `percent` (0–100, so 6 means 6%), `months`, `enum`,
`boolean`, `match_tiers`, `count`.

## For Documents and retrieval: fields not in the schema yet

| Field | Unit | Where | Used by |
|---|---|---|---|
| `health.coinsurance_percent` | percent | Benefits guide, per plan (synthetic guide p. 4: 20 / 20 / 10) | `benefits_cost`, only for an expected-claims year |
| `espp.months_until_eligible` | months | Benefits guide (Tyler summary p. 6: six months of service) | `espp` |
| `health.premium` for dental and vision | usd_per_paycheck | Benefits guide (synthetic p. 6) | `paycheck` (Section 125 lines) |

## `paycheck`: take-home pay per check (Example 1)

| Input | Unit | Source | Notes |
|---|---|---|---|
| `annual_salary` | usd_per_year | Doc `offer_letter.pdf:offer.annual_salary`; quiz if no offer letter | Required. Ask if unconfirmed. |
| `pay_frequency` | enum: weekly, biweekly, semimonthly, monthly | Doc `offer.pay_frequency` | Required. Cross-check: `paystub.gross_pay` ≈ salary ÷ periods. |
| `filing_status` | enum: single, married_filing_jointly, married_filing_separately, head_of_household | Quiz (W-4 Step 1(c)) | Required. |
| `retirement_401k_percent` | percent | Quiz (401(k) slider) | Default 0. Guide's auto-enroll rate is 3%. |
| `retirement_401k_type` | enum: traditional, roth | Quiz | Default traditional. |
| `pretax_deductions` | {name: usd_per_paycheck} | Doc `health.premium:<plan>:<tier>` for the chosen plan and tier (quiz `health_plan`, `coverage`); dental/vision premiums; payroll HSA | Section 125: lowers every tax. |
| `after_tax_deductions` | {name: usd_per_paycheck} | `espp` result `per_check` | Lowers net pay only. |
| `state` | enum: CO | Quiz | Only Colorado is supported. |
| `city` | string | Quiz | Matched to `local` in the config (Denver today). |
| `w4` | {step2_checked: boolean, step3_credits, step4a_other_income, step4b_deductions: usd_per_year, step4c_extra: usd_per_paycheck} | Quiz (W-4 answers) | Defaults: unchecked, all 0. |
| `co_dr0004_allowance` | usd_per_year | Quiz (DR 0004 line 2) | Omit if no DR 0004: config default by filing status. |
| `co_dr0004_extra` | usd_per_paycheck | Quiz (DR 0004 line 3) | Default 0. |
| `include_monthly_local_tax` | boolean | App (first check of the month) | Default true. Output also gives net without it. |
| `ytd_fica_wages`, `ytd_401k` | usd_per_year | Pay stub year-to-date, or 0 | For the wage base, Additional Medicare and 401(k) limit. |

Config: `pay_periods`, `federal.withholding.*` (Pub 15-T line 1g and schedules), `federal.social_security.*`,
`federal.medicare.*`, `colorado.withholding.*` (DR 1098), `colorado.famli.*`, `local`, `retirement.deferral_limit_401k`.

## `benefits_cost`: yearly cost of each health plan (Example 2)

| Input | Unit | Source | Notes |
|---|---|---|---|
| `plans[].name` | string | Doc `health.plan_type:<plan>` (the `plan` key) | One entry per plan. |
| `plans[].premium_per_check` | usd_per_paycheck | Doc `health.premium:<plan>:<tier>` | Tier from quiz `coverage`. |
| `plans[].deductible` | usd_per_year | Doc `health.deductible:<plan>:<tier>` | |
| `plans[].out_of_pocket_max` | usd_per_year | Doc `health.out_of_pocket_max:<plan>:<tier>` | High-use year. |
| `plans[].hsa_eligible` | boolean | Doc `health.plan_type` = `hdhp` | |
| `plans[].employer_hsa_annual` | usd_per_year | Doc `health.employer_hsa_contribution:<plan>:<tier>` | Ignored on non-HSA plans. |
| `plans[].coinsurance_percent` | percent | Doc `health.coinsurance_percent` (new, see above) | Only with `expected_claims`. |
| `pay_frequency` | enum | Doc `offer.pay_frequency` | |
| `coverage` | enum: employee_only, employee_spouse, employee_children, family | Quiz | Picks the HSA limit. |
| `annual_salary` | usd_per_year | Doc `offer.annual_salary` | For the HSA tax saving's federal bracket. |
| `filing_status` | enum | Quiz | |
| `federal_marginal_rate` | fraction (0.22) | `paycheck` result `federal_marginal_rate` | Optional override of the bracket. |
| `expected_claims` | usd_per_year | Quiz ("expect surgery" / doctor visits) | Optional middle scenario. |
| `age` | count (years) | Quiz | HSA catch-up at 55+. |

Config: `pay_periods`, `hsa.*`, `colorado.withholding.rate`, `federal.social_security.*`, `federal.medicare.employee_rate`,
`federal.withholding.*`.

## `contribution_order`: where saved dollars go first (Examples 3 and 5)

| Input | Unit | Source | Notes |
|---|---|---|---|
| `annual_salary` | usd_per_year | Doc `offer.annual_salary` | |
| `pay_frequency` | enum | Doc `offer.pay_frequency` | |
| `match_tiers` | match_tiers | Doc `benefits_guide.pdf:retirement.match_tiers` | Cumulative: `up_to_percent_of_pay` is the top of each tier. |
| `savings_goal_per_check` | usd_per_paycheck | Quiz | |
| `emergency_fund_months` | months | Quiz | Under the config target (3): emergency fund comes right after the match. |
| `hsa_eligible_plan` | boolean | Quiz `health_plan` + doc `health.plan_type` | |
| `employer_hsa_annual` | usd_per_year | Doc `health.employer_hsa_contribution:<plan>:<tier>` | |
| `coverage` | enum | Quiz | HSA limit tier. |
| `filing_status` | enum | Quiz | Roth IRA phase-out range. |
| `modified_agi` | usd_per_year | Quiz (optional) | Defaults to `annual_salary`. |
| `age` | count (years) | Quiz | 401(k) and IRA catch-up at 50+, HSA at 55+. |

Config: `pay_periods`, `retirement.*`, `hsa.*`, `planning.emergency_fund_target_months`.

## `espp`: money in, built-in gain, cautions (Example 4)

| Input | Unit | Source | Notes |
|---|---|---|---|
| `annual_salary` | usd_per_year | Doc `offer.annual_salary` | |
| `pay_frequency` | enum | Doc `offer.pay_frequency` | |
| `contribution_percent` | percent | Quiz `espp_percent` | Must not exceed `max_contribution_percent`. |
| `discount_percent` | percent | Doc `espp.discount_percent` | |
| `offering_period_months` | months | Doc `espp.offering_period_months` | |
| `lookback` | boolean | Doc `espp.lookback` | |
| `holding_period_months` | months, or null | Doc `espp.holding_period_months` | **null when the document doesn't say**; never assume 0. |
| `max_contribution_percent` | percent | Doc `espp.max_contribution_percent` | |
| `emergency_fund_months` | months | Quiz | Hard-case trigger. |
| `months_until_eligible` | months | Doc `espp.months_until_eligible` (new) | Default 0. |
| `start_price`, `end_price` | usd per share | User or illustration | Optional worked example. |

Config: `pay_periods`, `espp.section_423_annual_limit`, `planning.*`.

Output `hard_case_triggers` lists `holding_period`, `holding_period_not_stated` and
`no_emergency_fund` when they apply; any trigger means the answer must not say "always buy".

## Quiz fields the engine needs (for the User-facing app)

`filing_status`, `city`, `coverage`, `health_plan`, `emergency_fund_months`, `savings_goal_per_check`,
`retirement_401k_percent`, `retirement_401k_type`, `espp_percent`, `age`, and the W-4 / DR 0004
answers. `annual_salary` and `pay_frequency` only when there is no offer letter. Optional:
`expected_claims`, `modified_agi`.

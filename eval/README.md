# Evaluation cases

The test set for FirstPaycheck: each case is a question a new hire asks, plus the answer the user
confirmed. `eval/run.py` runs every case through the agent and the no-tools baseline. A case
passes when:

- **every graded figure** appears in the answer within its tolerance ($1 for dollar amounts),
- **every `must_include` point** is covered and no `must_not_include` one appears (judged by
  Claude Haiku 5.5), and
- (agent only) **every expected tool was called**, and no calculator ran when inputs were missing.

```
python eval/cases.py                          # list cases and any problems (free)
pytest tests/eval                             # the same checks plus the grading tests (free)
python eval/run.py --agent stub --judge stub  # whole pipeline with a stub agent (free)
python eval/run.py                            # real agent + Haiku judge (needs agent/run.py and an API key)
```

`run.py` prints a pass rate per analysis for the agent and the baseline, and the average and
most expensive question by token cost. Full answers, verdicts and token counts go to
`eval/results/` (git-ignored). Use `--cases ex1 ex4-espp` to run a few cases,
`--mode agent` to skip the baseline, and `--min-pass-rate 0.8` to fail below a threshold.

## GitHub Actions (`.github/workflows/eval.yml`)

| Job | When | What | Costs tokens? |
|---|---|---|---|
| `checks` | every PR, every push to main | `pytest`, `eval/cases.py`, `eval/run.py` with the stub agent | No |
| `agent-eval` | push to main, or **Actions → eval → Run workflow** | real agent vs. no-tools baseline, Haiku judge; report in the job summary, results as an artifact | Yes |

`agent-eval` skips itself until `agent/run.py` exists and the repo has an `ANTHROPIC_API_KEY`
secret (Settings → Secrets and variables → Actions).

## What `eval/run.py` needs from `agent/run.py`

`eval/agents.py` calls the agent like this; `tests/eval/test_run.py::test_cli_agent_contract` checks it
with a fake agent:

```
python agent/run.py "<question>" --docs <folder> --profile <profile.json> --log <log.json> [--no-tools]
```

- `--docs`: a folder holding only this case's documents.
- `--profile`: the quiz answers as JSON (the case's profile after overrides).
- `--no-tools`: the baseline (same model, documents only, no calculators).
- `--log`: write this JSON there and exit 0:

```json
{
  "answer": "text shown to the new hire",
  "tool_calls": [{"name": "paycheck", "args": {}, "result": {}}],
  "usage": [{"model": "claude-haiku-5-5", "input_tokens": 1234, "output_tokens": 210}]
}
```

One `usage` entry per model call. Tool names should match the cases' `tools` lists:
`search_documents`, `paycheck`, `benefits_cost`, `contribution_order`, `espp`, `loan_vs_invest`,
`offer_compare`.

## Files

| Path | What it is |
|---|---|
| `cases/<id>.json` | One case per file. The file name is the case id. |
| `case.schema.json` | What a case can contain; every field is described there. |
| `profiles/default.json` | The synthetic new hire most cases use (single, Denver, PPO 750, 6% 401(k)). |
| `cases.py` | `load_cases()` for the runner, `check_case()` for the tests. |
| `run.py`, `agents.py`, `judge.py` | The runner, the agents it can ask (real or stub), and the judges. |
| `pricing.json` | Token prices for the cost report, with source and date checked. |
| `edge_cases.md` | Edge cases for each example, and which ones are already cases. |

## The cases so far

All are `draft`: hand-computed with 2026 tax tables, not yet judged by a new hire.

| Case | Question | Key expected numbers |
|---|---|---|
| `ex1-take-home` | "My offer says 90k. What hits my account every two weeks?" | Gross $3,461.54; 401(k) $207.69; medical $62.00; federal $362.59; Social Security $210.77; Medicare $49.29; Colorado $131.13; FAMLI $14.96; Denver OPT $5.75; **net $2,417.36** ($2,423.11 without OPT) |
| `ex2-hdhp-vs-ppo` | "HDHP with HSA or the PPO? I rarely see a doctor." | Low-use year: PPO 750 $1,612, PPO 1500 $988, HDHP **-$32**. High-use year: $5,112 / $5,988 / $6,468. HSA tax saving at max $1,327.95 |
| `ex3-match-then-roth` | "The company matches 6%… Roth IRA, which comes first?" | Match is 3% of pay, not 6%. 401(k) $207.69 → match $103.85/check ($2,700/yr); Roth IRA $288.46; extra 401(k) $103.85 ($600 goal) |
| `ex4-espp` | "Buy company stock at a 15% discount?" (hard case) | $346.15/check at 10%; $4,500/period; built-in gain $794.12 (17.65%); 180-day hold → never "always buy" |
| `ex5-loans-vs-invest` | "Student loans at 4.5%: pay off or invest?" | Min payment $259.10/mo ($119.58/check); match first $207.69; then Roth $288.46; $103.85 left over |
| `ex1-unconfirmed-salary` | Example 1 with no offer letter | Agent must ask for the salary, not guess |
| `ex4-espp-no-emergency-fund` | Example 4 with no emergency fund | Build the fund first; never "always buy" |
| `ex2-tyler-hdhp-vs-ppo` | Example 2 on the Tyler 2026 summary | Low-use: $1,801.80 / $900.90 / **-$477.00**. High-use: $4,801.80 / $5,400.90 / $6,323.00 |
| `ex4-tyler-espp` | Example 4 on the Tyler 2026 summary | Not eligible for 6 months; quarterly, no lookback; $397.06 gain per quarter at 10% |
| `ex1-tyler-take-home` | Example 1, Tyler profile ($85k, no local tax) | Gross $3,269.23; federal $321.22; Colorado $122.86; **net $2,300.82** |
| `ex3-tyler-match-then-roth` | Example 3, Tyler profile | 401(k) $196.15 → match $98.08/check ($2,550/yr); Roth $288.46; extra 401(k) $115.39 |

**Tyler cases need a document that is not in the repo.** The four `*-tyler-*` cases use Tyler's
public 2026 U.S. Compensation & Benefits Summary, which the team keeps out of git. To run them,
save it as `data/tyler_2026_benefits_summary.pdf` (git-ignored). Without it, `python eval/cases.py`
marks them as skipped and the runner should skip them too (`cases.missing_docs()`). Their
expected numbers are still checked by `pytest`, since the figures are written inline.

## Adding a case

1. Copy the closest case to `cases/<new-id>.json` and set `"id"` to the same name.
2. Write the `question` in the new hire's own words. Set `source` to where it came from
   (`interview 2026-11-20`), **never a person's name**.
3. List the documents in `docs`, and the field ids the answer depends on in `fields`. Use ids from
   `samples/answers/*.json`; for a document without an answer file, write the field inline
   (same shape as `docs/fields.schema.json`).
4. Change the profile with `profile_overrides` (e.g. `{"coverage": "family"}`), or add a new file
   in `profiles/` if many cases share it.
5. Fill `expected.figures`. Inputs get `"graded": false` plus `from_field` or `from_profile`, so
   the test checks them against the document. Every computed number gets a `derivation` over other
   figure ids, so the test recomputes it. Write rules as plain numbers in the derivation and name
   the source in `sources` with its tax year.
6. Write `must_include` as points a reader can tick off, with the key dollar amounts in them.
   Put tempting wrong answers in `must_not_include`.
7. Run `python eval/cases.py` until it says `0 problems`.
8. Once a new hire agrees the answer is right, set `"status": "user_confirmed"` and `confirmed_on`.

## Rules

- **No real documents or personal details.** Use the synthetic docs in `samples/` or public
  employer summaries. Cases built on a new hire's situation use rounded, non-identifying values.
- **Assumptions are written down.** If you change one (W-4 settings, what "low use" means, the
  savings goal), re-derive every figure that depends on it.
- **Tax year.** Everything uses 2026 tables because the 2027 Pub 15-T and Colorado DR 1098 are not
  out yet. When they publish, update the numbers in each derivation, run the checks, and bump
  `tax_year`.
- **Expected answers come from the user, not the engine.** Don't copy calculator output into a case;
  that would make the engine grade itself.

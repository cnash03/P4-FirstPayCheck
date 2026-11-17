# Safety and privacy

Owner: Evaluation, cost, and safety (Callen).

| File | What it is |
|---|---|
| `check_private.py` | Blocks commits with personal data: real documents, names, addresses, SSNs, employee IDs, account numbers, birth dates, personal emails, salaries. |
| `allowlist.txt` | Paths where synthetic personal data is allowed (`samples/`, `tests/`, eval cases). |
| `disclaimer.json` | Advisor disclaimer wording for the app and the agent (draft). |

## Turn on the pre-commit check (once per clone)

    git config core.hooksPath .githooks

After that, `git commit` runs `python3 safety/check_private.py` on the staged files and stops the
commit if anything looks personal. CI runs the same check on every file (`--all`), so skipping
the hook with `--no-verify` only moves the failure to the PR.

The check never prints the matched text, because CI logs on this public repo are public too.

## When it blocks something

- **Real document or real person's details:** don't commit it. Real documents go in the
  git-ignored `data/` folder. Never paste them into AI coding tools either.
- **Synthetic test data:** put it under a path in `allowlist.txt` (usually `tests/` or
  `samples/`), or add `privacy: allow` on that one line.
- **A synthetic sample PDF:** it needs `samples/answers/<name>.json` with `"synthetic": true`.

## Limits

It catches labeled and patterned data: "Dear …", "Employee: …", SSN formats, street addresses,
"salary … $NN,NNN". It cannot spot a bare name or a bare number with no label. It is a guardrail,
not a reason to stop being careful.

# FirstPaycheck

A new-job money guide for the incoming new-hire cohort at Tyler Technologies.
Upload your offer letter, benefits guide, and pay stub; FirstPaycheck shows your take-home pay per
check, compares health plans by yearly cost, and lays out the 401(k), HSA, and Roth IRA order in
dollars per check, with every number linked to the page it came from.

FirstPaycheck explains options and shows the math. It is not financial advice: confirm decisions with
HR or a licensed advisor.

## How it works

- **Frontend** (`app/`): Next.js app with the profile quiz, dashboard, what-if sliders, and checklist.
- **API** (`api/`): FastAPI server; calls the documents and engine code, holds no math itself.
- **Documents and retrieval** (`docs/`, `config/`): PDF upload, redaction, parsing, field extraction,
  cited search over a local SQLite store, the glossary, and the tax-year config with sources.
- **Financial engine and agent** (`engine/`, `agent/`): deterministic, tested calculators and a
  Haiku 5.5 tool-calling loop on top of them.
- **Evaluation** (`eval/`): the judged test set, agent vs no-tools baseline, cost per task, run in
  GitHub Actions. Cases live one per file in `eval/cases/`; see `eval/README.md` to add one.

Everything runs on localhost. Uploaded documents stay in the git-ignored `data/` folder.

## Quick start

    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    python docs/ingest.py samples/          # build data/firstpaycheck.sqlite from synthetic docs
    uvicorn api.main:app                    # API at localhost:8000/docs
    cd app && npm install && npm run dev    # app at localhost:3000

Run the tests with `pytest`, and the evaluation with `python eval/run.py`.

## Privacy

Never commit or paste a real offer letter, pay stub, or benefits guide into this repo or into an AI
coding tool. Use the synthetic files in `samples/`. A pre-commit check blocks names, salaries, and ID
numbers.

## Team

| Part | Owner |
|---|---|
| Documents and retrieval | Ethan Luu |
| Financial engine and agent tools | Shawn Prather |
| User-facing app | Kaelem Deng |
| Evaluation, cost, and safety | Callen Nash |

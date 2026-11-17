"""The pre-commit privacy check blocks personal data and lets ordinary project files through.

Proposal (Evaluation, cost, and safety): committing a file with a fake name, address or
salary is blocked.
"""
import json
from pathlib import Path

import pytest

from safety import check_private as cp

ROOT = Path(__file__).resolve().parents[2]
GLOBS = cp.load_allowlist()


def problems(path, text):
    return cp.check(path, text.encode(), GLOBS)


# ---- blocked ----

@pytest.mark.parametrize("line,kind", [
    ("SSN: 900-12-3456", "Social Security number"),
    ("Social Security Number 900123456", "Social Security number"),
    ("Employee ID: FRC-104823", "employee ID"),
    ("Account number: 000123456789", "bank account number"),
    ("Date of birth: April 12, 2001", "date of birth"),
    ("Call me at (303) 555-0147", "phone number"),
    ("Mail it to 999 Fictional Way, Unit 0", "street address"),
    ("Dear Riley Q. Marchetti,", "person's name"),
    ("Employee: Riley Marchetti", "person's name"),
    ("Your starting annual base salary will be $90,000.", "salary"),
    ("offer came in at $85,000 per year", "salary"),
    ("reach me at riley.marchetti@gmail.com", "personal email address"),
])
def test_blocks_personal_data(line, kind):
    found = problems("notes/scratch.md", f"some notes\n{line}\n")
    assert found == [f"notes/scratch.md:2: looks like a {kind}"]


def test_output_never_contains_the_personal_data():
    found = problems("notes/scratch.md", "SSN: 900-12-3456 and Dear Riley Marchetti,")
    assert found and not any("900-12-3456" in p or "Riley" in p for p in found)


def test_synthetic_pay_stub_text_is_blocked_outside_samples():
    """Copying the sample stub's text anywhere else is caught: name, address, ID, SSN, DOB, account."""
    spec = json.loads((ROOT / "samples/answers/pay_stub.json").read_text())
    text = "\n".join(block["p"].replace("<br/>", "\n") for page in spec["pages"] for block in page if "p" in block)
    kinds = {p.split("looks like a ")[1] for p in problems("eval/pay_stub_copy.txt", text)}
    assert kinds == {"person's name", "street address", "employee ID", "Social Security number",
                     "date of birth", "bank account number"}


@pytest.mark.parametrize("path", ["offer.pdf", "docs/my_paystub.pdf", "eval/screenshot.png", "app/offer.docx"])
def test_blocks_documents_outside_samples(path):
    assert "real documents never go in the repo" in cp.check(path, b"%PDF-1.7", GLOBS)[0]


def test_blocks_anything_in_data():
    assert "must never be committed" in cp.check("data/notes.txt", b"hello", GLOBS)[0]


def test_sample_pdf_needs_a_synthetic_answer_file():
    assert cp.check("samples/pay_stub.pdf", b"%PDF", []) == []
    assert "synthetic" in cp.check("samples/real_offer.pdf", b"%PDF", [])[0]


# ---- allowed ----

@pytest.mark.parametrize("line", [
    "Email Tyler.Benefits@tylertech.com or benefits@frontrange-civic.example",
    "Co-Authored-By: Claude <noreply@anthropic.com>",
    "Gross $3,461.54; Social Security wage base $184,500 in 2026",
    "name: eval",
    "Pay date: January 22, 2027 to 2026-11-12",
    "Start date 2027-01-04; 401(k) at 6%",
    "Riley's SSN 900-12-3456 is fake  # privacy: allow",
])
def test_allows_ordinary_lines(line):
    assert problems("eval/README.md", line) == []


def test_allowlisted_paths_hold_synthetic_data():
    assert problems("tests/docs/test_redaction.py", "SSN: 900-12-3456") == []
    assert problems("samples/answers/pay_stub.json", "Dear Riley Marchetti,") == []


def test_the_repo_passes():
    """Everything committed today is clean; this is also what CI runs."""
    assert cp.main(["--all"]) == 0

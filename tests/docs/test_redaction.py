"""Redaction: no name, address, employee ID, SSN, phone number, email, date of
birth or bank account number survives, and nothing else is removed.

The proposal's check also covers stored text and text sent to the model;
those tests are added with the SQLite store (Docs 6) and the search tool.
"""
import json
import re
from pathlib import Path

import pytest

from parse import Page, parse_pdf
from redact import redact_pages

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
DOCS = ["offer_letter", "benefits_guide", "pay_stub"]


def norm(text):
    return re.sub(r"\s+", " ", text)


def redact(*texts):
    """Redact a made-up document whose pages are texts; return the pages joined by ' | '."""
    pages, _ = redact_pages([Page(i, t) for i, t in enumerate(texts, start=1)])
    return " | ".join(p.text for p in pages)


@pytest.fixture(params=DOCS)
def sample(request):
    spec = json.loads((SAMPLES / "answers" / f"{request.param}.json").read_text())
    raw = parse_pdf(SAMPLES / f"{request.param}.pdf")
    redacted, counts = redact_pages(raw)
    return spec, raw, redacted, counts


# ---- the synthetic samples ----

def test_no_pii_left(sample):
    spec, _, redacted, _ = sample
    text = norm(" ".join(p.text for p in redacted))
    assert [s for s in spec["pii"] if norm(s) in text] == []


def test_no_answer_removed(sample):
    spec, _, redacted, _ = sample
    lost = [f["id"] for f in spec["fields"]
            if norm(f["source_text"]) not in norm(redacted[f["page"] - 1].text)]
    assert lost == []


def test_page_numbers_unchanged(sample):
    _, raw, redacted, _ = sample
    assert [p.page for p in redacted] == [p.page for p in raw]


def test_running_twice_changes_nothing(sample):
    _, _, redacted, _ = sample
    again, counts = redact_pages(redacted)
    assert [p.text for p in again] == [p.text for p in redacted]
    assert +counts == {}


def test_counts_hold_no_pii(sample):
    spec, _, _, counts = sample
    assert not any(s in str(counts) for s in spec["pii"])


def test_benefits_guide_untouched():
    raw = parse_pdf(SAMPLES / "benefits_guide.pdf")
    assert [p.text for p in redact_pages(raw)[0]] == [p.text for p in raw]


# ---- each kind of PII, one case at a time ----

REMOVED = [
    # (case, pages, text that must be gone, text that must stay)
    ("SSN dashed", ["SSN: 900-12-3456"], "900-12-3456", "SSN:"),
    ("SSN masked XXX", ["SSN: XXX-XX-3456"], "3456", "SSN:"),
    ("SSN masked ***", ["SSN: ***-**-3456"], "3456", "SSN:"),
    ("SSN spaced", ["SSN: 900 12 3456"], "3456", "SSN:"),
    ("SSN nine digits", ["SSN: 900123456"], "900123456", "SSN:"),
    ("SSN long label", ["Social Security Number: 900123456"], "900123456", "Social Security Number:"),
    ("SSN without a label", ["Ref 900-12-3456 on file"], "900-12-3456", "on file"),
    ("employee ID", ["Employee ID: FRC-104823"], "104823", "Employee ID:"),
    ("Emp ID", ["Emp ID: 104823"], "104823", "Emp ID:"),
    ("Employee #", ["Employee #: 104823"], "104823", "Employee #:"),
    ("Employee No.", ["Employee No. 104823"], "104823", "Employee No."),
    ("street with unit", ["999 Fictional Way, Unit 0"], "Fictional Way", ""),
    ("street with Apt", ["12 Oak St Apt 4B"], "Oak St", ""),
    ("street with direction", ["4821 W Larkspur Ave"], "Larkspur", ""),
    ("city line", ["Denver, CO 80299"], "80299", ""),
    ("city line ZIP+4", ["Golden, CO 80401-1887"], "80401", ""),
    # Names are found only through a cue (Dear, Employee:, Candidate:). A name with
    # no cue anywhere, such as only a "Signed:" line, is not redacted and has no
    # test yet; how to handle it (more cues or a named-entity model) is to be
    # discussed later.
    ("name after Dear", ["Dear Riley Q. Marchetti,"], "Marchetti", "Dear"),
    ("name after Employee:", ["Employee: Riley Marchetti"], "Marchetti", "Employee:"),
    ("name after Candidate:", ["Candidate: Riley Marchetti"], "Marchetti", "Candidate:"),
    ("first name alone", ["Dear Riley Marchetti,", "Riley, welcome aboard."], "Riley", "welcome"),
    ("name on a later page", ["Employee: Riley Marchetti", "Signed, Riley Marchetti"], "Marchetti", "Signed"),
    ("name in capitals", ["Dear Riley Marchetti,", "RILEY MARCHETTI"], "MARCHETTI", ""),
    ("surname alone in capitals", ["Dear Riley Marchetti,", "MARCHETTI, R."], "MARCHETTI", ""),
    ("apostrophe", ["Dear Sean O'Brien,"], "Brien", "Dear"),
    ("accents", ["Dear María García,"], "García", "Dear"),
    ("hyphenated surname", ["Dear Ana Ruiz-Lopez,"], "Ruiz", "Dear"),
    ("phone with parentheses", ["Phone: (303) 555-0147"], "555-0147", "Phone:"),
    ("phone with dashes", ["Cell 303-555-0147"], "555-0147", "Cell"),
    ("phone with dots", ["303.555.0147"], "555.0147", ""),
    ("phone with country code", ["+1 303 555 0147"], "555 0147", ""),
    ("phone with no area separator", ["(303)555-0147"], "555-0147", ""),
    ("personal email", ["Email: riley.marchetti@example.com"], "marchetti@", "Email:"),
    ("email with plus", ["r.m+jobs@mail.example.org"], "example.org", ""),
    ("DOB long date", ["Date of birth: April 12, 2001"], "2001", "Date of birth:"),
    ("DOB slashes", ["DOB: 04/12/2001"], "04/12/2001", "DOB:"),
    ("DOB ISO", ["Birth date: 2001-04-12"], "2001-04-12", "Birth date:"),
    ("account number", ["Account number: 000123456789"], "000123456789", "Account number:"),
    ("Acct #", ["Acct #: 98765432"], "98765432", "Acct #:"),
    ("routing number", ["Routing number: 123456780"], "123456780", "Routing number:"),
]


@pytest.mark.parametrize("case,pages,gone,stay", REMOVED, ids=[c[0] for c in REMOVED])
def test_removed(case, pages, gone, stay):
    out = redact(*pages)
    assert gone not in out
    assert stay in out


# ---- text that looks like PII but is not, and must survive ----

KEPT = [
    ("money and percents", "PPO 750 $1,500 deductible, 20% coinsurance, 401(k) 6%"),
    ("dates", "Pay date: January 22, 2027; pay period 01/04/2027"),
    ("plan words", "Health Savings Account and Roth 401(k)"),
    ("ESPP title", "Employee Stock Purchase Plan (ESPP)"),
    ("Plan Name label", "Plan Name: Health Savings Plan"),
    ("Employee label on a plan", "Employee: Health Plan Coverage"),
    ("employee ID with no digits", "Employee ID: see your welcome email"),
    ("table columns", "Deductible, family   $1,500   $3,000   $6,800"),
    ("pay date", "Pay date: January 22, 2027"),
    ("start date", "Your first day of employment will be Monday, January 4, 2027."),
    ("numeric dates", "Pay period: 01/04/2027 to 01/17/2027"),
    ("role mailbox", "Benefits questions: benefits@frontrange-civic.example"),
    ("HR mailbox", "Contact hr@example.com"),
    ("account last four", "Direct deposit to checking account ending 0000."),
    ("account with a year", "Health Savings Account 2027"),
    ("ZIP+4 alone", "Golden 80401-1887"),
    ("long plain number", "Group number 0012345678"),
]


@pytest.mark.parametrize("case,text", KEPT, ids=[c[0] for c in KEPT])
def test_kept(case, text):
    assert redact(text) == text


def test_learned_name_does_not_remove_common_words():
    # "Will" is learned as a first name, but the word "will" stays.
    out = redact("Dear Will Marchetti,", "Your coverage will start on day one.")
    assert "Will" not in out and "coverage will start" in out


def test_false_name_cue_does_not_spread():
    # A non-person after a cue must not be learned and removed from later pages.
    out = redact("Employee: Health Plan Coverage", "The Health plan pays 80%.")
    assert "The Health plan pays 80%." in out

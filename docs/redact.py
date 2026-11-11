"""Placeholder redactor: remove names, addresses, employee IDs, SSNs, phone
numbers, emails, dates of birth and bank account numbers.

Runs on parsed pages before anything is stored or sent to the model.
Callen's redaction rules will replace these patterns; keep redact_pages()
as the one entry point so the swap touches nothing else.

    python docs/redact.py samples/pay_stub.pdf   # print the redacted pages
"""
import re
import sys
from collections import Counter

from parse import Page, ParseError, parse_pdf

# Each pattern's "pii" group is the part replaced; the rest (a label) stays.

# A Social Security number, also masked or spaced: 900-12-3456, XXX-XX-3456,
# ***-**-3456, 900 12 3456 (one separator used throughout).
SSN = re.compile(r"(?<![\w*])(?P<pii>(?:\d{3}|X{3}|\*{3})([- ])(?:\d{2}|X{2}|\*{2})\2\d{4})\b", re.I)
# Nine digits after an SSN label.
SSN_LABELED = re.compile(r"\b(?:SSN|Social Security (?:Number|No\.?))[ \t]*[:#]?[ \t]*(?P<pii>\d{9})\b", re.I)

# The value after an employee ID label: "Employee ID:", "Emp ID:", "Employee #:", "Employee No.".
# The value must contain a digit, so "Employee ID: see page 2" is left alone.
EMPLOYEE_ID = re.compile(
    r"\b(?:Employee|Emp\.?)[ \t]*(?:ID|No\.?|Number|#)[ \t]*[:#]?[ \t]*(?P<pii>(?=[A-Z-]*\d)[A-Z0-9][A-Z0-9-]*)",
    re.I)

# A street line: a house number, words, then a street type ("999 Fictional Way, Unit 0").
STREET = re.compile(
    r"(?P<pii>\b\d{1,6}(?: [A-Z][\w.']*)+ (?:Way|St|Street|Ave|Avenue|Rd|Road|Ln|Lane|Ct|Court|Dr|Drive|"
    r"Blvd|Boulevard|Pl|Place|Cir|Circle|Pkwy|Parkway|Ter|Terrace|Trl|Trail)\b\.?"
    r"(?:,? (?:Unit|Apt|Suite|#) ?\w+)?)")

# A city, state and ZIP line ("Denver, CO 80299").
CITY_STATE_ZIP = re.compile(r"(?P<pii>\b[A-Z][A-Za-z .'-]*, [A-Z]{2} \d{5}(?:-\d{4})?)\b")

# A bank account or routing number after its label. Labeled only, since a bare
# long number may be a group number or plan ID; "account ending 0000" is kept.
BANK = re.compile(
    r"\b(?:Account|Acct\.?|Routing|ABA)[ \t]*(?:number|no\.?|#)?[ \t]*[:#]?[ \t]*(?P<pii>\d{6,17})\b", re.I)

# A date of birth after its label. Labeled only: other dates (start, pay date,
# enrollment deadline) are answers and must stay.
_DATE = r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|[A-Z][a-z]+\.? \d{1,2},? \d{4})"
DOB = re.compile(rf"\b(?:Date of birth|Birth ?date|DOB)[ \t]*[:#]?[ \t]*(?P<pii>{_DATE})", re.I)

# An email address. Role mailboxes such as benefits@ are kept, since they are
# not a person and the user may need them.
EMAIL = re.compile(r"(?P<pii>\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+)")
ROLE_MAILBOXES = {"benefits", "hr", "payroll", "people", "help", "support", "info"}

# A US phone number: (303) 555-0147, 303-555-0147, 303.555.0147, +1 303 555 0147.
PHONE = re.compile(r"(?<![\d+])(?P<pii>(?:\+?1[ .-]?)?(?:\(\d{3}\) ?|\d{3}[ .-]?)\d{3}[ .-]\d{4})(?!\d)")

# (label, pattern, keep): keep(value) is True for a match to leave alone.
PATTERNS = [
    ("SSN", SSN, None),
    ("SSN", SSN_LABELED, None),
    ("ACCOUNT", BANK, None),
    ("DOB", DOB, None),
    ("EMAIL", EMAIL, lambda v: v.split("@")[0].lower() in ROLE_MAILBOXES),
    ("EMPLOYEE_ID", EMPLOYEE_ID, None),
    ("ADDRESS", STREET, None),
    ("ADDRESS", CITY_STATE_ZIP, None),
    ("PHONE", PHONE, None),
]

# One part of a name, accented letters allowed: "Riley", "García", "O'Brien", "Ruiz-Lopez".
_UP, _LOW = "A-ZÀ-ÖØ-Þ", "a-zß-öø-ÿ"
_PART = rf"[{_UP}][{_LOW}]*(?:['’-][{_UP}]?[{_LOW}]+)*"
_NAME = rf"{_PART}(?: [{_UP}]\.)?(?: {_PART})+"
# Where a document names the person: a greeting, or a person label.
# A bare "Name:" is not a cue, since guides say "Plan Name:".
NAME_CUES = [
    re.compile(rf"\bDear ({_NAME})\s*[,:]"),
    re.compile(rf"\b(?:Employee(?: Name)?|Candidate|Employee's Name):[ \t]*({_NAME})", re.I),
]
# Words a benefits document uses that are never a person; a cue that lands on
# one of these is a false hit, and none of them is learned as a lone name.
NOT_NAMES = {
    "account", "benefit", "benefits", "company", "coverage", "dental", "disability", "employee",
    "flexible", "health", "insurance", "life", "medical", "plan", "purchase", "retirement",
    "savings", "spending", "stock", "vision",
}


def find_names(pages):
    """Collect every name the cues point at, plus each one's first and last name alone."""
    full_names, parts = set(), set()
    for p in pages:
        for cue in NAME_CUES:
            for m in cue.finditer(p.text):
                words = m.group(1).split()
                if any(w.lower() in NOT_NAMES for w in words):
                    continue
                full_names.add(m.group(1))
                parts.update(w for w in words if len(w) > 2)
    # Longest first, so "Riley Q. Marchetti" is replaced before "Riley".
    by_length = lambda names: sorted(names, key=len, reverse=True)
    return by_length(full_names), by_length(parts)


def _replace(pattern, label, text, keep=None):
    """Replace only the pattern's "pii" group with [label]; return (text, count)."""
    n = 0

    def sub(m):
        nonlocal n
        if keep and keep(m.group("pii")):
            return m.group(0)
        n += 1
        start, end = m.span("pii")
        return m.group(0)[: start - m.start()] + f"[{label}]" + m.group(0)[end - m.start():]
    return pattern.sub(sub, text), n


def redact_text(text, names, counts):
    """Replace each kind of PII with a [LABEL]; counts records how many of each."""
    for label, pattern, keep in PATTERNS:
        text, n = _replace(pattern, label, text, keep)
        counts[label] += n
    full_names, parts = names
    for name in full_names:
        # A full name is matched in any case, so "RILEY MARCHETTI" goes too.
        text, n = re.subn(rf"(?<!\w){re.escape(name)}(?!\w)", "[NAME]", text, flags=re.I)
        counts["NAME"] += n
    for part in parts:
        # A lone first or last name only as written or in capitals, so a name
        # like "Will" does not remove the word "will".
        text, n = re.subn(rf"(?<!\w)(?:{re.escape(part)}|{re.escape(part.upper())})(?!\w)", "[NAME]", text)
        counts["NAME"] += n
    return text


def redact_pages(pages):
    """Return (redacted pages, Counter of how many of each label were replaced).

    Names are learned from the whole document first, so a name found in the
    greeting on page 1 is also removed from the address block and later pages.
    The counter holds no PII, so it is safe to log.
    """
    names = find_names(pages)
    counts = Counter()
    redacted = [Page(p.page, redact_text(p.text, names, counts)) for p in pages]
    return redacted, counts


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: python docs/redact.py <file.pdf>")
    try:
        pages, counts = redact_pages(parse_pdf(sys.argv[1]))
    except ParseError as e:
        sys.exit(f"error: {e}")
    for p in pages:
        print(f"===== page {p.page} =====\n{p.text}\n")
    print("redacted:", dict(counts) or "nothing", file=sys.stderr)


if __name__ == "__main__":
    main()

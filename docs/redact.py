"""Redaction rules: remove names, addresses, employee IDs, SSNs, phone numbers,
emails, dates of birth and bank account numbers from parsed pages.

Runs on every page before anything is stored or sent to the model
(docs/store.py calls redact_pages()). Owner: Evaluation, cost and safety.

How it works, in three passes over the whole document:
1. Learn: find the person's name (after a cue such as "Dear", "Employee:",
   "Pay to the order of", or as the line just above a street address) and the
   values after ID labels (SSN, employee or file number, account number).
2. Patterns: replace everything that looks like PII by its shape (SSNs, street
   and city lines, phones, emails, labeled dates of birth and accounts).
3. Learned values: replace the learned names and IDs wherever else they appear,
   so a name from the header or an ID from page 1 is also gone from the footer
   and later pages, with or without its label.

Each replacement is a [LABEL], so the agent still sees that something was there.
Money, plan names, dates other than a birth date, role mailboxes (benefits@)
and "account ending 0000" are kept, since they are answers.

    python docs/redact.py samples/pay_stub.pdf   # print the redacted pages
"""
import re
import sys
from collections import Counter

from parse import Page, ParseError, parse_pdf

# Each pattern's "pii" group is the part replaced; the rest (a label) stays.

# ---------- SSNs ----------

# A Social Security number, also masked, spaced or dotted: 900-12-3456, XXX-XX-3456,
# ***-**-3456, 900 12 3456, 900.12.3456 (one separator used throughout).
SSN = re.compile(r"(?<![\w*•])(?P<pii>(?:\d{3}|X{3}|\*{3}|•{3})([- .])(?:\d{2}|X{2}|\*{2}|•{2})\2\d{4})\b", re.I)
_SSN_LABEL = (r"\b(?:SSN|SS ?#|Soc(?:ial)? Sec(?:urity)?\.? ?(?:Number|No\.?|#)?|Taxpayer ID|ITIN|TIN)"
              r"(?:[ \t]*\((?:last (?:4|four)(?: digits)?)\))?")
# After an SSN label: nine digits, a masked form (xxxx3456, ***-**3456, XXXXX3456), or the last four alone.
SSN_LABELED = re.compile(
    rf"{_SSN_LABEL}[ \t]*[:#]?[ \t]*(?P<pii>\d{{9}}|[X*•]{{3,5}}[- ]?[X*•]{{0,2}}[- ]?\d{{4}}|\d{{4}})(?!\d)", re.I)

# ---------- IDs and accounts ----------

# The value after an employee or payroll ID label. The value must contain a digit,
# so "Employee ID: see page 2" is left alone.
_ID_LABEL = (r"\b(?:(?:Employee|Emp\.?)[ \t]*(?:ID|No\.?|Number|#)|(?:Associate|Worker|Personnel|Payroll|Badge)"
             r"[ \t]*(?:ID|No\.?|Number|#)|File[ \t]*(?:#|No\.?|Number)|Clock[ \t]*(?:#|No\.?|Number))")
EMPLOYEE_ID = re.compile(rf"{_ID_LABEL}[ \t]*[:#]?[ \t]*(?P<pii>(?=[A-Z-]*\d)[A-Z0-9][A-Z0-9-]*)", re.I)

# A bank account or routing number after its label. Labeled only, since a bare
# long number may be a group number or plan ID; "account ending 0000" and
# "****0000" (the last four only) are kept.
BANK = re.compile(
    r"\b(?:Account|Acct\.?|Routing|ABA)[ \t]*(?:number|no\.?|#)?[ \t]*[:#]?[ \t]*(?P<pii>\d{6,17})\b", re.I)

# ---------- dates of birth ----------

# Labeled only: other dates (start, pay date, enrollment deadline) are answers and must stay.
_MONTH = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
          r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?")
_DATE = (rf"(?:\d{{1,2}}[/-]\d{{1,2}}[/-]\d{{2,4}}|\d{{4}}-\d{{2}}-\d{{2}}|{_MONTH} \d{{1,2}},? \d{{4}}|"
         rf"\d{{1,2}} {_MONTH},? \d{{4}})")
DOB = re.compile(rf"\b(?:Date of birth|Birth ?date|DOB|D\.O\.B\.)[ \t]*[:#]?[ \t]*(?P<pii>{_DATE})", re.I)

# ---------- addresses ----------

# A street line: a house number, one to four words (or ordinals like 17th), a street
# type, and an optional unit. "999 Fictional Way, Unit 0", "4821 W LARKSPUR AVE APT 4B",
# "1234 E. 17th Ave". Words start with a capital or a digit, so prose is left alone.
_STREET_TYPE = (r"(?i:Way|St|Street|Ave|Avenue|Rd|Road|Ln|Lane|Ct|Court|Dr|Drive|Blvd|Boulevard|Pl|Place|"
                r"Cir|Circle|Pkwy|Parkway|Ter|Terrace|Trl|Trail|Hwy|Highway|Loop|Sq|Square|Row|Run|Pike|"
                r"Plaza|Alley|Xing|Crossing|Mall|Walk)")
_UNIT = r"(?:,? (?i:Unit|Apt|Apartment|Suite|Ste|Bldg|Fl|Floor|#)\.? ?#?[A-Z0-9-]+)"
STREET = re.compile(
    rf"(?<![\d$,.])(?P<pii>\b\d{{1,6}}(?: [A-Z0-9][\w.'-]*){{1,4}} {_STREET_TYPE}\b\.?{_UNIT}?)")
PO_BOX = re.compile(r"(?P<pii>\bP\.? ?O\.? ?Box \d+)", re.I)

# A city, state and ZIP line, with or without the comma: "Denver, CO 80299", "GOLDEN CO 80401".
# Only real state codes, so "PPO 75000"-style text is left alone.
_STATES = ("AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|"
           "NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|PR")
CITY_STATE_ZIP = re.compile(
    rf"(?P<pii>\b[A-Z][A-Za-z.'-]*(?: [A-Z][A-Za-z.'-]*){{0,2}},? (?:{_STATES}) \d{{5}}(?:-\d{{4}})?)\b")

# ---------- contact ----------

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
    ("ADDRESS", PO_BOX, None),
    ("ADDRESS", CITY_STATE_ZIP, None),
    ("PHONE", PHONE, None),
]

# Labeled IDs whose values are also removed wherever else they appear (pass 3).
LEARNED_IDS = [("SSN", SSN_LABELED), ("EMPLOYEE_ID", EMPLOYEE_ID), ("ACCOUNT", BANK)]

# ---------- names ----------

# One part of a name, accented letters allowed: "Riley", "García", "O'Brien", "Ruiz-Lopez",
# or the same in capitals: "MARCHETTI", "O'BRIEN".
_UP, _LOW = "A-ZÀ-ÖØ-Þ", "a-zß-öø-ÿ"
_PART = rf"(?:[{_UP}][{_LOW}]*(?:['’-][{_UP}]?[{_LOW}]+)*|[{_UP}]{{2,}}(?:['’-][{_UP}]+)*)"
_INITIAL = rf"(?: [{_UP}]\.?)"
# "Riley Q. Marchetti", "RILEY Q MARCHETTI": two to four parts, an optional middle initial.
_NAME = rf"{_PART}{_INITIAL}?(?: {_PART}){{1,3}}"
# "Marchetti, Riley Q": last name first, as payroll systems print it.
_LAST_FIRST = rf"{_PART}, {_PART}{_INITIAL}?"
_ANY_NAME = rf"(?:{_LAST_FIRST}|{_NAME})"

# Where a document names the person. "Name:" counts only at the start of a line,
# since guides say "Plan Name:".
NAME_CUES = [
    re.compile(rf"\bDear ({_ANY_NAME}|{_PART})\s*[,:]"),
    re.compile(rf"\b(?:Employee(?:'s)?(?: Name)?|Candidate|Associate|Payee|Prepared for):[ \t]*({_ANY_NAME})", re.I),
    re.compile(rf"(?m)^[ \t]*Name:[ \t]*({_ANY_NAME})", re.I),
    re.compile(rf"\bPay to the order of:?[ \t]*({_ANY_NAME})", re.I),
]
# Words a benefits document or pay stub uses that are never part of a person's name.
# A cued name is cut at the first of these ("Riley Marchetti Pay Date" -> "Riley
# Marchetti"); a cue that lands on one first ("Employee: Health Plan") is a false hit.
NOT_NAMES = {
    "account", "benefit", "benefits", "company", "coverage", "dental", "disability", "employee",
    "flexible", "health", "insurance", "life", "medical", "plan", "purchase", "retirement",
    "savings", "spending", "stock", "vision",
    "pay", "date", "period", "rate", "net", "gross", "total", "check", "deposit", "department",
    "dept", "location", "title", "status", "id", "number", "earnings", "statement", "hours",
    "regular", "salary", "federal", "state", "tax", "taxes", "the", "and", "of", "for", "to",
}
# Words that mark a line as a company or office, not a person (for the address-block cue).
ORG_WORDS = {
    "inc", "llc", "corp", "corporation", "co", "company", "ltd", "lp", "llp", "group", "software",
    "technologies", "technology", "services", "bank", "credit", "union", "department", "office",
    "team", "operations", "hr", "payroll", "people", "university", "school", "city", "county",
}


def _words(name):
    return re.findall(rf"[{_UP}{_LOW}'’-]+", name)


def _clean_name(raw):
    """Cut a cued name at its first NOT_NAMES word; return None if nothing is left."""
    kept = []
    for w in raw.replace(",", " ").split():
        if w.lower().strip(".") in NOT_NAMES:
            break
        kept.append(w)
    if not kept or not any(len(w.strip(".")) > 1 for w in kept):
        return None
    if "," in raw and len(kept) == len(raw.replace(",", " ").split()):
        return raw   # "Marchetti, Riley Q" kept whole
    return " ".join(kept)


def _names_above_addresses(page_text):
    """A name with no label, printed on the line just above a street or PO box line in the same column.

    Pay stubs print the employee's mailing block this way, often beside the company's
    own block: "MARCHETTI, RILEY Q        Front Range Civic Software, Inc.".
    """
    lines = page_text.splitlines()
    found = []
    for above, line in zip(lines, lines[1:]):
        for m in list(STREET.finditer(line)) + list(PO_BOX.finditer(line)):
            for seg in re.finditer(r"\S+(?: \S+)*", above):   # columns are split by 2+ spaces
                if abs(seg.start() - m.start()) > 3:
                    continue
                text = seg.group(0)
                words = [w.lower().strip(".,") for w in text.split()]
                if any(w in ORG_WORDS or w in NOT_NAMES for w in words) or re.search(r"\d", text):
                    continue
                if re.fullmatch(_ANY_NAME, text):
                    found.append(text)
    return found


def find_names(pages):
    """Collect every name the cues point at; return (full names, single name parts), longest first."""
    full_names, parts = set(), set()
    for p in pages:
        raw = [m.group(1) for cue in NAME_CUES for m in cue.finditer(p.text)]
        raw += _names_above_addresses(p.text)
        for r in raw:
            name = _clean_name(r)
            if not name:
                continue
            words = [w for w in _words(name) if len(w) > 2]
            full_names.add(name)
            if "," in name:
                # Also "Riley Q Marchetti" and "Riley Marchetti" for a "Marchetti, Riley Q".
                last, rest = (s.strip() for s in name.split(",", 1))
                full_names.update({f"{rest} {last}", f"{rest.split()[0]} {last}"})
            parts.update(words)
    by_length = lambda names: sorted(names, key=len, reverse=True)
    return by_length(full_names), by_length(parts)


def find_ids(pages):
    """Values after ID labels (SSN, employee or file number, account), learned to remove them everywhere.

    A value is learned only if it has five or more characters, so a last-four "3456"
    is removed after its label but not hunted for across the document. An ID with
    letters, like FRC-104823, also teaches its digits (104823), which payroll
    systems often print alone.
    """
    ids = set()
    for p in pages:
        for label, pattern in LEARNED_IDS:
            for m in pattern.finditer(p.text):
                value = m.group("pii")
                if len(value) >= 5:
                    ids.add((label, value))
                for digits in re.findall(r"\d{5,}", value):
                    ids.add((label, digits))
    return sorted(ids, key=lambda x: len(x[1]), reverse=True)


# ---------- replacing ----------

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


def redact_text(text, learned, counts):
    """Replace each kind of PII with a [LABEL]; counts records how many of each."""
    (full_names, parts), ids = learned
    for label, pattern, keep in PATTERNS:
        text, n = _replace(pattern, label, text, keep)
        counts[label] += n
    for label, value in ids:
        # Not inside money or a longer number: "$104,823" and "1048230" stay.
        text, n = re.subn(rf"(?<![\w$,.]){re.escape(value)}(?![\w]|[.,]\d)", f"[{label}]", text)
        counts[label] += n
    for name in full_names:
        # A full name is matched in any case, so "RILEY MARCHETTI" goes too.
        text, n = re.subn(rf"(?<!\w){re.escape(name)}(?!\w)", "[NAME]", text, flags=re.I)
        counts["NAME"] += n
    for part in parts:
        # A lone first or last name only as written, in capitals or capitalized, so a
        # name like "Will" does not remove the word "will".
        forms = {part, part.upper(), part[0].upper() + part[1:].lower()}
        alts = "|".join(re.escape(f) for f in sorted(forms, key=len, reverse=True))
        text, n = re.subn(rf"(?<!\w)(?:{alts})(?!\w)", "[NAME]", text)
        counts["NAME"] += n
    return text


def redact_pages(pages):
    """Return (redacted pages, Counter of how many of each label were replaced).

    Names and IDs are learned from the whole document first, so a name found in
    the greeting on page 1 is also removed from the address block and later pages.
    The counter holds no PII, so it is safe to log.
    """
    learned = (find_names(pages), find_ids(pages))
    counts = Counter()
    redacted = [Page(p.page, redact_text(p.text, learned, counts)) for p in pages]
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
    print("redacted:", dict(+counts) or "nothing", file=sys.stderr)


if __name__ == "__main__":
    main()

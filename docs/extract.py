"""Pull plan details out of redacted pages: salary, pay frequency, premiums,
deductibles, the HSA money, the 401(k) match, the ESPP terms and more.

Rules only (regular expressions over paragraphs and table rows), so every
value comes with the page it was read from. A field the document does not
state is left out, never guessed: the engine and the agent treat a missing
field as unknown and ask the user.

    python docs/extract.py samples/benefits_guide.pdf   # print the fields as JSON
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = "0.1"

# ---------- small parsers ----------

_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE = rf"(?:(?:{_MONTHS})\.? \d{{1,2}},? \d{{4}}|\d{{1,2}}/\d{{1,2}}/\d{{4}}|\d{{4}}-\d{{2}}-\d{{2}})"
MONEY = r"\$\s?(\d[\d,]*(?:\.\d{2})?)"
WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "eighteen": 18, "twenty-four": 24}


def to_date(text):
    """'February 3, 2027', '2/3/2027' or '2027-02-03' -> '2027-02-03'."""
    text = text.replace(".", "").replace(",", "")
    for fmt in ("%B %d %Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def to_money(text):
    """'$1,500' -> 1500, '$62.00' -> 62.0 (whole dollars stay ints, matching the answer files)."""
    value = float(text.replace("$", "").replace(",", "").strip())
    return int(value) if value.is_integer() and "." not in text else value


def to_number(word):
    word = word.lower()
    return int(word) if word.isdigit() else WORD_NUMBERS.get(word)


def tier_of(text):
    """Map a coverage phrase to a schema tier, or None."""
    t = text.lower()
    if "spouse" in t or "partner" in t:
        return "employee_spouse"
    if "child" in t:
        return "employee_children"
    if "family" in t or "dependent" in t:
        return "family"
    if re.search(r"employee[- ]only|individual|single|self[- ]only|employee$", t):
        return "employee_only"
    return None


def plan_type_of(name):
    n = name.lower()
    for pattern, kind in [(r"hdhp|high[- ]deductible|hsa", "hdhp"), (r"\bppo\b", "ppo"),
                          (r"\bhmo\b", "hmo"), (r"\bepo\b", "epo")]:
        if re.search(pattern, n):
            return kind
    return None


NEGATION = re.compile(r"\b(?:no|not|does not|doesn't|do not|without|none)\b", re.I)
PER_CHECK = re.compile(r"biweekly|bi-weekly|per pay(?:check| period)?|each paycheck|per check|semi-?monthly", re.I)


# ---------- page text ----------

def paragraphs(page):
    """The page's paragraphs, each on one line (layout mode wraps them)."""
    out = []
    for block in re.split(r"\n\s*\n", page.text):
        if re.search(r"\S {2,}\S", block.strip()):        # a table row, handled by table_rows()
            continue
        para = re.sub(r"\s+", " ", block).strip()
        if para:
            out.append(para)
    return out


def table_rows(page):
    """Rows of the page's tables as lists of cells (columns are 2+ spaces apart)."""
    return [re.split(r"\s{2,}", line.strip()) for line in page.text.splitlines()
            if re.search(r"\S {2,}\S", line.strip())]


def sentences(para):
    return re.split(r"(?<=[.;])\s+(?=[A-Z])", para)


# ---------- records ----------

class Fields:
    """Collects records for one document; the first value found for an id wins."""

    def __init__(self, doc):
        self.doc, self.records = doc, {}

    def add(self, name, value, unit, page, source_text, plan=None, tier=None):
        fid = ":".join([self.doc, name] + [x for x in (plan, tier) if x])
        if value is None or fid in self.records:
            return
        rec = {"id": fid, "name": name, "value": value, "unit": unit}
        if plan:
            rec["plan"] = plan
        if tier:
            rec["coverage_tier"] = tier
        rec.update(doc=self.doc, page=page, source_text=source_text.strip(), status="unconfirmed")
        self.records[fid] = rec


# ---------- what kind of document ----------

KIND_CUES = {
    "offer_letter": r"offer of employment|pleased to offer|annual base salary|accept this offer",
    "pay_stub": r"earnings statement|pay stub|net pay|year to date|pay period",
    "benefits_guide": r"benefits guide|deductible|out-of-pocket|premium|open enrollment|401\(k\)",
}


def kind_of(pages):
    """'offer_letter', 'pay_stub' or 'benefits_guide', by which cues appear most."""
    text = " ".join(p.text for p in pages).lower()
    scores = {k: len(re.findall(cue, text)) for k, cue in KIND_CUES.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] else None


# ---------- offer letter ----------

def offer_letter(pages, out):
    for page in pages:
        for para in paragraphs(page):
            for s in sentences(para):
                m = re.search(rf"\bsalary\b[^$.]{{0,60}}{MONEY}", s, re.I) or \
                    re.search(rf"{MONEY}\s+(?:per year|a year|annually)", s, re.I)
                if m:
                    out.add("offer.annual_salary", to_money(m.group(1)), "usd_per_year", page.page, s)
                if re.search(r"\bpaid\b|\bpay(?:check|roll)?s?\b", s, re.I):
                    out.add("offer.pay_frequency", pay_frequency(s), "enum", page.page, s)
                m = re.search(rf"(?:first day(?: of employment)?|start date|start(?:ing)? on|begin(?:ning)? on)"
                              rf"[^.]{{0,40}}?({DATE})", s, re.I)
                if m:
                    out.add("offer.start_date", to_date(m.group(1)), "date", page.page, s)


def pay_frequency(text):
    t = text.lower()
    if re.search(r"bi-?weekly|every (?:other|two) weeks?|every other (?:monday|tuesday|wednesday|thursday|friday)", t):
        return "biweekly"
    if re.search(r"semi-?monthly|twice (?:a|per) month", t):
        return "semimonthly"
    if re.search(r"\bweekly\b|every week", t):
        return "weekly"
    if re.search(r"\bmonthly\b|once a month", t):
        return "monthly"
    return None


# ---------- pay stub ----------

def pay_stub(pages, out):
    for page in pages:
        rows = table_rows(page)
        # A "gross" row wins over a salary row, so both are tried in that order.
        for label in (r"gross (?:pay|earnings|wages)", r"regular (?:salary|pay|earnings)|^salary"):
            for cells in rows:
                if re.search(label, cells[0], re.I):
                    amounts = [c for c in cells[1:] if re.fullmatch(MONEY, c)]
                    if amounts:     # the first amount is this period, the next year-to-date
                        out.add("paystub.gross_pay", to_money(amounts[0]), "usd_per_paycheck", page.page,
                                " ".join(cells[:2]))
        for para in paragraphs(page):
            m = re.search(rf"(?:pay|check) date:?\s*({DATE})", para, re.I)
            if m:
                out.add("paystub.pay_date", to_date(m.group(1)), "date", page.page, m.group(0))


# ---------- benefits guide ----------

PLAN_NAME = re.compile(r"\b(?:PPO|HMO|EPO|POS|HDHP|High[- ]Deductible)\b", re.I)


def medical_table(pages, out):
    """Find the cost table (a header row naming 2+ plans), read premiums, deductibles,
    out-of-pocket maximums and coinsurance per plan; return the plan names."""
    plans = []
    for page in pages:
        rows = table_rows(page)
        for i, header in enumerate(rows):
            names = header[1:]
            if len(names) < 2 or not all(PLAN_NAME.search(n) for n in names):
                continue
            plans += [n for n in names if n not in plans]
            per_check = bool(PER_CHECK.search(header[0])) or any(
                PER_CHECK.search(p) for p in paragraphs(page))
            for cells in rows[i + 1:]:
                if len(cells) != len(header):
                    break
                label, values = cells[0], cells[1:]
                low = label.lower()
                # Coinsurance first: its label often says "after deductible".
                if "coinsurance" in low:
                    for plan, v in zip(names, values):
                        m = re.fullmatch(r"(\d+(?:\.\d+)?)%", v)
                        if m:
                            out.add("health.coinsurance_percent", num(m.group(1)), "percent", page.page, v, plan=plan)
                    continue
                elif "deductible" in low:
                    name, unit = "health.deductible", "usd_per_year"
                elif "out-of-pocket" in low or "out of pocket" in low:
                    name, unit = "health.out_of_pocket_max", "usd_per_year"
                elif per_check and tier_of(label):
                    name, unit = "health.premium", "usd_per_paycheck"
                else:
                    continue
                tier = tier_of(label.split(",")[-1])
                for plan, v in zip(names, values):
                    if re.fullmatch(MONEY, v) and tier:
                        out.add(name, to_money(v), unit, page.page, v, plan=plan, tier=tier)
    # A plan's type is cited where the guide first names the plan.
    for plan in plans:
        page = next((p for p in pages if plan in re.sub(r"\s+", " ", p.text)), None)
        if page:
            out.add("health.plan_type", plan_type_of(plan), "enum", page.page, plan, plan=plan)
    return plans


def hsa_money(pages, plans, out):
    hsa_plans = [p for p in plans if plan_type_of(p) == "hdhp"]
    if len(hsa_plans) != 1:
        return          # which plan the money belongs to would be a guess
    for page in pages:
        for para in paragraphs(page):
            if not (re.search(r"\bHSA\b|health savings", para, re.I) and re.search(r"contribut|deposit|adds?", para, re.I)):
                continue
            # The coverage phrase ends before the next amount: "... for individual coverage and $1,500 ..."
            for m in re.finditer(rf"{MONEY}\s*(?:per year|a year|annually)?\s+for\s+([^.;$]+?)(?=\s+(?:and|or)\b|[,.;$]|$)",
                                 para, re.I):
                out.add("health.employer_hsa_contribution", to_money(m.group(1)), "usd_per_year", page.page,
                        m.group(0), plan=hsa_plans[0], tier=tier_of(m.group(2)))


def dental_vision(pages, out):
    for page in pages:
        for para in paragraphs(page):
            m = re.match(r"(Dental|Vision)\b", para)
            if not (m and PER_CHECK.search(para)):
                continue
            for amt in re.finditer(rf"{MONEY}\s+(employee[- ]only|individual|single|employee \+ \w+|family)", para, re.I):
                out.add("health.premium", to_money(amt.group(1)), "usd_per_paycheck", page.page, amt.group(0),
                        plan=m.group(1), tier=tier_of(amt.group(2)))


def benefits_credit(pages, out):
    credit = re.compile(r"benefits? credit|flex (?:dollars|credits)|benefits? (?:fund|dollars|allowance)", re.I)
    for page in pages:
        for para in paragraphs(page):
            if not credit.search(para):
                continue
            for s in sentences(para):
                named = credit.search(s)
                if named:
                    m = re.search(rf"{MONEY}\s*(?:per year|a year|annually|each year)", s, re.I)
                    if m:
                        out.add("benefits.employer_credit", to_money(m.group(1)), "usd_per_year", page.page, s)
                    elif NEGATION.search(s[:named.end()][-40:]):
                        out.add("benefits.employer_credit", 0, "usd_per_year", page.page, s)
                # A later sentence may say where leftover credit goes without naming the credit again.
                if re.search(r"unused|left ?over|remaining", s, re.I):
                    if re.search(r"401\(k\)", s):
                        where = "401k"
                    elif re.search(r"\bcash\b|paid (?:out|to you)|taxable pay|in your paycheck", s, re.I):
                        where = "cash"
                    elif re.search(r"forfeit|\blost\b|\blose\b", s, re.I):
                        where = "forfeit"
                    else:
                        where = None
                    out.add("benefits.credit_leftover_to", where, "enum", page.page, s)


def retirement(pages, out):
    for page in pages:
        for para in paragraphs(page):
            for s in sentences(para):
                if re.search(r"\bmatch", s, re.I):
                    out.add("retirement.match_tiers", match_tiers(s), "match_tiers", page.page, s)
                if re.search(r"profit[- ]sharing|non-?matching|non-?elective", s, re.I):
                    if NEGATION.search(s):
                        out.add("retirement.employer_nonmatch", 0, "usd_per_year", page.page, s)
                    else:
                        m = re.search(rf"{MONEY}\s*(?:per year|a year|annually|each year)", s, re.I)
                        if m:
                            out.add("retirement.employer_nonmatch", to_money(m.group(1)), "usd_per_year", page.page, s)


def match_tiers(s):
    """Read a match formula into cumulative tiers; None if the sentence states none."""
    pct = r"(\d+(?:\.\d+)?)%"
    m = re.search(rf"(\d+) cents (?:for|on) (?:every|each) dollar.*?(?:first|up to) {pct}", s, re.I)
    if m:
        return [{"match_percent": int(m.group(1)), "up_to_percent_of_pay": num(m.group(2))}]
    m = re.search(rf"dollar[- ]for[- ]dollar.*?(?:first|up to) {pct}", s, re.I)
    if m:
        return [{"match_percent": 100, "up_to_percent_of_pay": num(m.group(1))}]
    tiers, top = [], 0
    for m in re.finditer(rf"{pct}\s+(?:match\s+)?(?:of|on)\s+(?:the\s+)?(first|next)\s+{pct}", s, re.I):
        top = num(m.group(3)) if m.group(2).lower() == "first" else top + num(m.group(3))
        tiers.append({"match_percent": num(m.group(1)), "up_to_percent_of_pay": top})
    return tiers or None


def num(text):
    value = float(text)
    return int(value) if value.is_integer() else value


def espp(pages, out):
    for page in pages:
        if not re.search(r"\bESPP\b|stock purchase", page.text, re.I):
            continue
        for para in paragraphs(page):
            for s in sentences(para):
                if re.search(r"401\(k\)", s):
                    continue
                m = re.search(r"(\d+(?:\.\d+)?)%\s+discount|discount of (\d+(?:\.\d+)?)%", s, re.I)
                if m:
                    out.add("espp.discount_percent", num(m.group(1) or m.group(2)), "percent", page.page, s)
                if re.search(r"look-?back", s, re.I):
                    out.add("espp.lookback", not re.search(r"\b(?:no|without|does not)\b[^.]{0,20}look-?back", s, re.I),
                            "boolean", page.page, s)
                m = re.search(r"(\w+)[- ]month offering periods?|offering periods? (?:of|last(?:s|ing)?) (\w+) months", s, re.I)
                if m:
                    out.add("espp.offering_period_months", to_number(m.group(1) or m.group(2)), "months", page.page, s)
                if re.search(r"no holding period", s, re.I):
                    out.add("espp.holding_period_months", 0, "months", page.page, s)
                m = re.search(r"(?:cannot|can't|may not|must not) be sold (?:for|until) (\w+) (days?|months?|years?)|"
                              r"(?:hold(?:ing)? (?:period )?(?:of|for)|(?:held|kept) for(?: at least)?) "
                              r"(\w+) (days?|months?|years?)", s, re.I)
                if m:
                    n, unit = to_number(m.group(1) or m.group(3)), (m.group(2) or m.group(4)).lower()
                    if n is not None:
                        months = round(n / 30) if unit.startswith("day") else n * 12 if unit.startswith("year") else n
                        out.add("espp.holding_period_months", months, "months", page.page, s)
                m = re.search(r"\d+% to (\d+)% of (?:your )?(?:eligible )?(?:pay|compensation|salary)|"
                              r"up to (\d+)% of (?:your )?(?:eligible )?(?:pay|compensation|salary)", s, re.I)
                if m:
                    out.add("espp.max_contribution_percent", num(m.group(1) or m.group(2)), "percent", page.page, s)
                if re.search(r"no (?:service )?waiting period", s, re.I):
                    out.add("espp.months_until_eligible", 0, "months", page.page, s)
                m = re.search(r"after (\w+) months? of (?:service|employment)", s, re.I)
                if m and re.search(r"join|eligible|enroll", s, re.I):
                    out.add("espp.months_until_eligible", to_number(m.group(1)), "months", page.page, s)


def enrollment(pages, out):
    for page in pages:
        for para in paragraphs(page):
            for s in sentences(para):
                m = re.search(rf"(?:deadline|enroll by|elections? (?:are )?due)\D{{0,20}}?({DATE})", s, re.I)
                if m:
                    out.add("enrollment.deadline", to_date(m.group(1)), "date", page.page, s)


def benefits_guide(pages, out):
    plans = medical_table(pages, out)
    hsa_money(pages, plans, out)
    dental_vision(pages, out)
    benefits_credit(pages, out)
    retirement(pages, out)
    espp(pages, out)
    enrollment(pages, out)


EXTRACTORS = {"offer_letter": offer_letter, "pay_stub": pay_stub, "benefits_guide": benefits_guide}


def extract_fields(doc, pages, kind=None):
    """Return field records (the docs/fields.schema.json shape) for one document's redacted pages.

    kind is 'offer_letter', 'pay_stub' or 'benefits_guide'; worked out from the text when not given.
    """
    kind = kind or kind_of(pages)
    out = Fields(doc)
    if kind:
        EXTRACTORS[kind](pages, out)
    return list(out.records.values())


def main():
    sys.path.insert(0, str(Path(__file__).parent))
    from parse import ParseError, parse_pdf
    from redact import redact_pages
    if len(sys.argv) != 2:
        sys.exit("usage: python docs/extract.py <file.pdf>")
    try:
        pages, _ = redact_pages(parse_pdf(sys.argv[1]))
    except ParseError as e:
        sys.exit(f"error: {e}")
    fields = extract_fields(Path(sys.argv[1]).name, pages)
    print(json.dumps({"schema_version": SCHEMA_VERSION, "fields": fields}, indent=2))


if __name__ == "__main__":
    main()

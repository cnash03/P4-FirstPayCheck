"""Render the synthetic sample PDFs from their specs, then check them.

Each samples/answers/<name>.json is both the source of samples/<name>.pdf and
its answer file: the "fields" list is what extraction must find, on the page
given, and "pii" is what redaction must remove.

    python samples/make_samples.py
"""
import json
import re
import sys
from pathlib import Path

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

HERE = Path(__file__).parent
ANSWERS = HERE / "answers"
STYLES = getSampleStyleSheet()


def blocks_to_flowables(blocks):
    """A block is {"h": text}, {"p": text} or {"table": rows}; the first table row is the header."""
    out = []
    for block in blocks:
        if "h" in block:
            out.append(Paragraph(block["h"], STYLES["Heading2"]))
        elif "p" in block:
            out.append(Paragraph(block["p"], STYLES["BodyText"]))
        elif "table" in block:
            table = Table(block["table"], hAlign="LEFT")
            table.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
            ]))
            out.append(table)
        else:
            raise ValueError(f"unknown block: {block}")
        out.append(Spacer(1, 6))
    return out


def render(spec, pdf_path):
    story = []
    for i, page in enumerate(spec["pages"]):
        if i:
            story.append(PageBreak())
        story.extend(blocks_to_flowables(page))

    def footer(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.drawString(inch, 0.5 * inch, f"{spec['title']} | Page {doc.page} | SYNTHETIC TEST DOCUMENT")

    doc = SimpleDocTemplate(str(pdf_path), pagesize=letter, title=spec["title"],
                            topMargin=inch, bottomMargin=inch)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def normalize(text):
    return re.sub(r"\s+", " ", text).strip()


def check(spec, pdf_path):
    """Return a list of problems: wrong page count, an answer not on its page, or PII missing."""
    pages = [normalize(p.extract_text()) for p in PdfReader(pdf_path).pages]
    problems = []
    if len(pages) != len(spec["pages"]):
        problems.append(f"{len(pages)} pages rendered, spec has {len(spec['pages'])} (a page overflowed)")
    for f in spec["fields"]:
        page = f["page"]
        if page > len(pages) or normalize(f["source_text"]) not in pages[page - 1]:
            problems.append(f"{f['id']}: {f['source_text']!r} not found on page {page}")
    everything = " ".join(pages)
    for item in spec["pii"]:
        if normalize(item) not in everything:
            problems.append(f"PII {item!r} not in the PDF, so redaction has nothing to test")
    return problems


def main():
    failed = False
    for spec_path in sorted(ANSWERS.glob("*.json")):
        spec = json.loads(spec_path.read_text())
        pdf_path = HERE / spec["doc"]
        render(spec, pdf_path)
        problems = check(spec, pdf_path)
        status = "FAIL" if problems else "ok"
        print(f"{status:4} {pdf_path.name}: {len(spec['pages'])} pages, "
              f"{len(spec['fields'])} fields, {len(spec['pii'])} PII strings")
        for p in problems:
            print("     ", p)
        failed |= bool(problems)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

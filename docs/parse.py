"""Turn a PDF into its text, one entry per page.

Uses pypdf's layout mode, which keeps a table row on one line
("Employee only   $62.00   $38.00   $18.00") instead of one cell per line,
so extraction can tell which column a number belongs to.

    python docs/parse.py samples/benefits_guide.pdf          # every page
    python docs/parse.py samples/benefits_guide.pdf --page 4 # one page
"""
import argparse
import re
import sys
from pathlib import Path
from typing import NamedTuple

from pypdf import PdfReader
from pypdf.errors import PdfReadError


class Page(NamedTuple):
    page: int   # 1-based, the number a citation shows
    text: str


class ParseError(Exception):
    """The file is missing, is not a PDF, or is password-protected."""


def clean(text):
    """Drop trailing spaces and collapse runs of blank lines; keep column spacing."""
    lines = [line.rstrip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip("\n")


def parse_pdf(path):
    """Return [Page(1, text), Page(2, text), ...] for the PDF at path.

    A page with no text layer (a scan) comes back with text "" and a warning,
    so page numbers stay aligned with the document.
    """
    path = Path(path)
    if not path.is_file():
        raise ParseError(f"{path}: no such file")
    try:
        reader = PdfReader(path)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ParseError(f"{path}: the PDF is password-protected")
        pages = [Page(i, clean(p.extract_text(extraction_mode="layout")))
                 for i, p in enumerate(reader.pages, start=1)]
    except PdfReadError as e:
        raise ParseError(f"{path}: not a readable PDF ({e})") from e

    for p in pages:
        if not p.text:
            print(f"warning: {path.name} page {p.page} has no text (scanned?)", file=sys.stderr)
    return pages


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pdf")
    ap.add_argument("--page", type=int, help="print only this page (1-based)")
    args = ap.parse_args()
    try:
        pages = parse_pdf(args.pdf)
    except ParseError as e:
        sys.exit(f"error: {e}")
    for p in pages:
        if args.page in (None, p.page):
            print(f"===== page {p.page} =====\n{p.text}\n")


if __name__ == "__main__":
    main()

"""Build the store from PDFs: parse, redact and save every page.

    python docs/ingest.py samples/                  # every PDF in a folder
    python docs/ingest.py samples/pay_stub.pdf      # one file
    python docs/ingest.py samples/ --force          # re-ingest unchanged files too

Deleting data/firstpaycheck.sqlite and rerunning rebuilds it. Output shows
only file names, page counts and redaction counts, never document text.
"""
import argparse
import sys
from pathlib import Path

from parse import ParseError
from store import DB_PATH, ingest_file


def pdfs_in(paths):
    """Expand folders to the PDFs directly inside them, in name order."""
    found = []
    for p in map(Path, paths):
        if p.is_dir():
            found += sorted(f for f in p.iterdir() if f.suffix.lower() == ".pdf")
        else:
            found.append(p)
    return found


def pages(n):
    return f"{n} page" if n == 1 else f"{n} pages"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+", help="PDF files or folders of PDFs")
    ap.add_argument("--db", default=DB_PATH, help=f"SQLite file (default: {DB_PATH.relative_to(DB_PATH.parents[1])})")
    ap.add_argument("--force", action="store_true", help="re-ingest files that have not changed")
    args = ap.parse_args()

    files = pdfs_in(args.paths)
    if not files:
        sys.exit("error: no PDF files found")

    failed = 0
    for f in files:
        try:
            s = ingest_file(f, args.db, force=args.force)
        except ParseError as e:
            print(f"FAIL {f.name}: {e}")
            failed += 1
            continue
        if s["skipped"]:
            print(f"skip {s['doc']}: unchanged ({pages(s['pages'])})")
        else:
            removed = ", ".join(f"{n} {label}" for label, n in s["redactions"].items() if n) or "nothing"
            print(f"ok   {s['doc']}: {pages(s['pages'])}, redacted {removed}")
    print(f"{len(files) - failed} of {len(files)} files in {args.db}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()

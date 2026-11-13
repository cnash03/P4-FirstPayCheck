"""Block commits that contain personal data: real documents, names, addresses, IDs, salaries.

    python safety/check_private.py          # staged files (what the pre-commit hook runs)
    python safety/check_private.py --all    # every tracked file (what CI runs)
    python safety/check_private.py FILE...  # specific files

Install the hook once per clone:   git config core.hooksPath .githooks

Synthetic test data is allowed only in the paths listed in safety/allowlist.txt. For a
one-off false positive, put `privacy: allow` on that line. The output never prints the
matched text, because CI logs on this public repo are public too.

Standard library only, so the hook runs with any python3.
"""
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / "safety" / "allowlist.txt"
LINE_OVERRIDE = "privacy: allow"

DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".rtf", ".pages", ".xls", ".xlsx", ".numbers",
                       ".png", ".jpg", ".jpeg", ".heic", ".gif", ".tif", ".tiff", ".bmp", ".webp"}
ROLE_MAILBOXES = {"benefits", "hr", "payroll", "people", "help", "support", "info", "noreply", "no-reply"}
EXAMPLE_DOMAINS = re.compile(r"(^|\.)(example\.(com|org|net)|test|invalid|localhost)$", re.I)

NAME = r"[A-Z][a-z]+(?:[ \t]+[A-Z]\.?)?[ \t]+[A-Z][a-z]+(?:-[A-Z][a-z]+)?"
_DATE = r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|[A-Z][a-z]+\.? \d{1,2},? \d{4})"

# (kind, pattern). Each pattern matches only the personal part, not ordinary prose.
PATTERNS = [
    ("Social Security number", re.compile(r"(?<![\d-])\d{3}-\d{2}-\d{4}(?![\d-])")),
    ("Social Security number", re.compile(r"\b(?:SSN|Social Security (?:Number|No\.?))[ \t]*[:#]?[ \t]*\d{9}\b", re.I)),
    ("employee ID", re.compile(r"\b(?:Employee|Emp\.?)[ \t]*(?:ID|No\.?|Number|#)[ \t]*[:#]?[ \t]*(?=[A-Z-]*\d)[A-Z0-9][A-Z0-9-]{3,}", re.I)),
    ("bank account number", re.compile(r"\b(?:Account|Acct\.?|Routing|ABA)[ \t]*(?:number|no\.?|#)?[ \t]*[:#]?[ \t]*\d{6,17}\b", re.I)),
    ("date of birth", re.compile(rf"\b(?:Date of birth|Birth ?date|DOB)[ \t]*[:#]?[ \t]*{_DATE}", re.I)),
    ("phone number", re.compile(r"(?<![\d+.])(?:\+?1[ .-]?)?(?:\(\d{3}\) ?|\d{3}[ .-])\d{3}[ .-]\d{4}(?![\d.])")),
    ("street address", re.compile(
        r"\b\d{1,6}(?: [A-Z][\w.']*)+ (?:Way|St|Street|Ave|Avenue|Rd|Road|Ln|Lane|Ct|Court|Dr|Drive|Blvd|"
        r"Boulevard|Pl|Place|Cir|Circle|Pkwy|Parkway|Ter|Terrace|Trl|Trail)\b")),
    ("person's name", re.compile(rf"\bDear[ \t]+(?:(?:Mr|Ms|Mrs|Dr)\.?[ \t]+)?{NAME}")),
    ("person's name", re.compile(rf"\b(?:Employee(?: [Nn]ame)?|Name|Payee|Pay to the order of)[ \t]*:[ \t]*{NAME}")),
    ("salary", re.compile(r"\b(?:[Ss]alary|[Bb]ase pay|[Aa]nnual pay)\b[^\n]{0,60}?\$[ \t]?\d{2,3}(?:,\d{3})+")),
    ("salary", re.compile(r"\$[ \t]?\d{2,3},\d{3}(?:\.\d{2})?[ \t]*(?:/[ \t]*(?:yr|year)\b|per year|a year|annually)", re.I)),
]
EMAIL = re.compile(r"\b([\w.+-]+)@([\w-]+(?:\.[\w-]+)+)")


def load_allowlist():
    globs = []
    for line in ALLOWLIST.read_text().splitlines():
        glob = line.split(" #")[0].strip()
        if glob and not glob.startswith("#"):
            globs.append(glob)
    return globs


def allowed(path, globs):
    return any(fnmatch.fnmatchcase(path, g) for g in globs)


def path_problems(path):
    """Rules on the file itself: real-document folders and file types."""
    p = Path(path)
    if p.parts and p.parts[0] == "data":
        return ["data/ holds real documents and must never be committed"]
    if p.suffix.lower() in DOCUMENT_EXTENSIONS:
        if p.parts and p.parts[0] == "samples" and len(p.parts) == 2:
            spec = ROOT / "samples" / "answers" / f"{p.stem}.json"
            try:
                if json.loads(spec.read_text()).get("synthetic") is True:
                    return []
            except (OSError, ValueError):
                pass
            return [f"sample document has no samples/answers/{p.stem}.json marked \"synthetic\": true"]
        return ["document or image file: real documents never go in the repo; synthetic ones go in samples/"]
    return []


def text_problems(text):
    """(line number, kind) for each line that looks like personal data."""
    hits = []
    for n, line in enumerate(text.splitlines(), start=1):
        if LINE_OVERRIDE in line:
            continue
        for kind, pattern in PATTERNS:
            if pattern.search(line):
                hits.append((n, kind))
        for local, domain in EMAIL.findall(line):
            parts = set(re.split(r"[._+-]", local.lower()))
            if not (parts & ROLE_MAILBOXES or EXAMPLE_DOMAINS.search(domain)):
                hits.append((n, "personal email address"))
    return sorted(set(hits))


def check(path, content, globs):
    """All problems for one file, as printable strings (never containing the matched text)."""
    if allowed(path, globs):
        return []
    problems = [f"{path}: {msg}" for msg in path_problems(path)]
    if problems or b"\0" in content[:8000]:
        return problems
    text = content.decode("utf-8", errors="replace")
    return [f"{path}:{n}: looks like a {kind}" for n, kind in text_problems(text)]


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True).stdout


def staged_files():
    names = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").decode().split("\0")
    return [(n, git("show", f":{n}")) for n in names if n]


def tracked_files():
    names = git("ls-files", "-z").decode().split("\0")
    return [(n, (ROOT / n).read_bytes()) for n in names if n and (ROOT / n).is_file()]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["--all"]:
        files = tracked_files()
    elif argv:
        files = [(str(Path(a).resolve().relative_to(ROOT)) if Path(a).resolve().is_relative_to(ROOT) else a,
                  Path(a).read_bytes()) for a in argv]
    else:
        files = staged_files()

    globs = load_allowlist()
    problems = [p for name, content in files for p in check(name, content, globs)]
    if not problems:
        return 0
    print("Possible personal data found; nothing was committed:\n", file=sys.stderr)
    for p in problems:
        print(f"  {p}", file=sys.stderr)
    print("\nReal documents and real people's details never go in this repo (it is public).\n"
          "If this is synthetic test data: move it under a path in safety/allowlist.txt, or add\n"
          f"'{LINE_OVERRIDE}' to that line. Don't use --no-verify: CI runs the same check.",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

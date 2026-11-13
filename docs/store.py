"""The SQLite store: each document's redacted pages, its extracted fields, and
the full-text search index over the pages.

Everything lives in one file, data/firstpaycheck.sqlite (git-ignored). Text is
redacted before it is written, so nothing in the file holds the PII that
docs/redact.py removes.

    from store import ingest_file, get_page, confirm_field
    ingest_file("samples/benefits_guide.pdf")
    get_page("benefits_guide.pdf", 4)
"""
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from parse import ParseError, parse_pdf
from redact import redact_pages

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "firstpaycheck.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc         TEXT PRIMARY KEY,   -- file name, as in field ids: benefits_guide.pdf
    sha256      TEXT NOT NULL,      -- of the original file, to skip an unchanged re-upload
    n_pages     INTEGER NOT NULL,
    redactions  TEXT NOT NULL,      -- JSON counts per label, e.g. {"NAME": 2}; no PII
    ingested_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pages (
    doc  TEXT NOT NULL REFERENCES documents(doc) ON DELETE CASCADE,
    page INTEGER NOT NULL,              -- 1-based, as cited
    text TEXT NOT NULL,                 -- redacted
    PRIMARY KEY (doc, page)
);
CREATE TABLE IF NOT EXISTS fields (
    id            TEXT PRIMARY KEY,     -- <doc>:<name>[:<plan>][:<coverage_tier>]
    doc           TEXT NOT NULL REFERENCES documents(doc) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    value         TEXT NOT NULL,        -- JSON, since a value may be a number, text, true/false or a list
    unit          TEXT NOT NULL,
    plan          TEXT,
    coverage_tier TEXT,
    page          INTEGER NOT NULL,
    source_text   TEXT,
    status        TEXT NOT NULL DEFAULT 'unconfirmed' CHECK (status IN ('unconfirmed', 'confirmed')),
    confirmed_at  TEXT
);
-- Search index over the redacted pages. porter: "deductibles" also finds "deductible".
CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
    text, doc UNINDEXED, page UNINDEXED, tokenize = 'porter unicode61'
);
"""

FIELD_KEYS = ["id", "name", "value", "unit", "plan", "coverage_tier", "doc", "page", "source_text", "status"]


def connect(db_path=None):
    """Open the store, creating the file and tables if needed."""
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    return con


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ingest_file(path, db_path=None, force=False):
    """Parse, redact and store one PDF; return a summary with no PII in it.

    A file with the same name replaces the earlier one, along with its fields.
    The same file again is skipped unless force=True.
    """
    path = Path(path)
    if not path.is_file():
        raise ParseError(f"{path}: no such file")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    with closing(connect(db_path)) as con, con:
        old = con.execute("SELECT sha256 FROM documents WHERE doc = ?", (path.name,)).fetchone()
        if old and old["sha256"] == sha and not force:
            n = con.execute("SELECT n_pages FROM documents WHERE doc = ?", (path.name,)).fetchone()[0]
            return {"doc": path.name, "pages": n, "redactions": {}, "skipped": True}

        # Redact before anything is written.
        pages, counts = redact_pages(parse_pdf(path))

        con.execute("DELETE FROM documents WHERE doc = ?", (path.name,))   # pages and fields cascade
        con.execute("DELETE FROM pages_fts WHERE doc = ?", (path.name,))
        con.execute("INSERT INTO documents VALUES (?, ?, ?, ?, ?)",
                    (path.name, sha, len(pages), json.dumps(dict(counts)), _now()))
        con.executemany("INSERT INTO pages VALUES (?, ?, ?)", [(path.name, p.page, p.text) for p in pages])
        con.executemany("INSERT INTO pages_fts (text, doc, page) VALUES (?, ?, ?)",
                        [(p.text, path.name, p.page) for p in pages])
    return {"doc": path.name, "pages": len(pages), "redactions": dict(counts), "skipped": False}


def get_page(doc, page, db_path=None):
    """Return the redacted text of one page, or None if there is no such page."""
    with closing(connect(db_path)) as con:
        row = con.execute("SELECT text FROM pages WHERE doc = ? AND page = ?", (doc, page)).fetchone()
    return row["text"] if row else None


def list_documents(db_path=None):
    with closing(connect(db_path)) as con:
        rows = con.execute("SELECT doc, n_pages, redactions, ingested_at FROM documents ORDER BY doc").fetchall()
    return [dict(r, redactions=json.loads(r["redactions"])) for r in rows]


def save_fields(fields, db_path=None):
    """Store extracted field records (the docs/fields.schema.json shape).

    A field the user already confirmed keeps its value and status when
    extraction runs again; any other field is replaced.
    """
    with closing(connect(db_path)) as con, con:
        for f in fields:
            row = con.execute("SELECT status FROM fields WHERE id = ?", (f["id"],)).fetchone()
            if row and row["status"] == "confirmed":
                continue
            con.execute(
                "INSERT OR REPLACE INTO fields (id, doc, name, value, unit, plan, coverage_tier, page, source_text, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (f["id"], f["doc"], f["name"], json.dumps(f["value"]), f["unit"], f.get("plan"),
                 f.get("coverage_tier"), f["page"], f.get("source_text"), f.get("status", "unconfirmed")))


def _field(row):
    f = {k: row[k] for k in FIELD_KEYS}
    f["value"] = json.loads(f["value"])
    return {k: v for k, v in f.items() if v is not None}


def get_fields(doc=None, status=None, db_path=None):
    """Return field records in the docs/fields.schema.json shape, optionally for one doc or status."""
    sql, args = "SELECT * FROM fields WHERE 1 = 1", []
    if doc:
        sql, args = sql + " AND doc = ?", args + [doc]
    if status:
        sql, args = sql + " AND status = ?", args + [status]
    with closing(connect(db_path)) as con:
        return [_field(r) for r in con.execute(sql + " ORDER BY doc, page, id", args)]


_MISSING = object()


def confirm_field(field_id, value=_MISSING, db_path=None):
    """Mark a field confirmed, optionally with the value the user corrected it to.

    Returns the updated record; raises KeyError for an unknown id.
    """
    with closing(connect(db_path)) as con, con:
        if value is _MISSING:
            cur = con.execute("UPDATE fields SET status = 'confirmed', confirmed_at = ? WHERE id = ?",
                              (_now(), field_id))
        else:
            cur = con.execute("UPDATE fields SET status = 'confirmed', confirmed_at = ?, value = ? WHERE id = ?",
                              (_now(), json.dumps(value), field_id))
        if cur.rowcount == 0:
            raise KeyError(field_id)
        return _field(con.execute("SELECT * FROM fields WHERE id = ?", (field_id,)).fetchone())

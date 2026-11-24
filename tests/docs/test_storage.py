"""Storage: one command, python docs/ingest.py samples/, builds one SQLite file holding each
document's redacted text by page, its extracted fields with their status, and the search
index; deleting the file and running the command again rebuilds the same contents.

The command runs with --db pointed at a temporary file, so the real data/ store is never touched.
"""
import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from store import DB_PATH, confirm_field, get_fields, ingest_file

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "samples"
PDFS = sorted(SAMPLES.glob("*.pdf"))


def ingest(db, *extra):
    """Run the one command; return its exit code and output."""
    run = subprocess.run([sys.executable, str(ROOT / "docs" / "ingest.py"), str(SAMPLES), "--db", str(db), *extra],
                         capture_output=True, text=True, cwd=ROOT)
    return run.returncode, run.stdout + run.stderr


def dump(db):
    """The store's contents, without the ingest timestamps."""
    with closing(sqlite3.connect(db)) as con:
        return {
            "documents": con.execute("SELECT doc, sha256, n_pages, redactions FROM documents ORDER BY doc").fetchall(),
            "pages": con.execute("SELECT doc, page, text FROM pages ORDER BY doc, page").fetchall(),
            "fields": con.execute("SELECT id, value, page, status FROM fields ORDER BY id").fetchall(),
            "index": con.execute("SELECT doc, page, text FROM pages_fts ORDER BY doc, page").fetchall(),
        }


def answers(pdf):
    return json.loads((SAMPLES / "answers" / f"{pdf.stem}.json").read_text())


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    folder = tmp_path_factory.mktemp("data")
    db = folder / "firstpaycheck.sqlite"
    code, out = ingest(db)
    assert code == 0, out
    return folder, db, dump(db)


def test_one_command_builds_one_file(built):
    folder, db, _ = built
    assert [p.name for p in folder.iterdir()] == [db.name]


def test_every_sample_is_stored(built):
    _, _, store = built
    assert [d[0] for d in store["documents"]] == [p.name for p in PDFS]


def test_redacted_text_is_stored_by_page(built):
    _, _, store = built
    for doc, _, n_pages, _ in store["documents"]:
        assert [p for d, p, _ in store["pages"] if d == doc] == list(range(1, n_pages + 1))
    assert all(text.strip() for _, _, text in store["pages"])


def test_fields_are_stored_unconfirmed(built):
    _, _, store = built
    expected = sum(len(answers(p)["fields"]) for p in PDFS)
    assert len(store["fields"]) == expected
    assert {status for *_, status in store["fields"]} == {"unconfirmed"}


def test_search_index_holds_every_page(built):
    _, _, store = built
    assert store["index"] == store["pages"]


def test_delete_and_rerun_rebuilds_the_same_store(built):
    _, db, store = built
    db.unlink()
    code, out = ingest(db)
    assert code == 0, out
    assert dump(db) == store


def test_rerun_skips_unchanged_files(built):
    _, db, store = built
    code, out = ingest(db)
    assert code == 0, out
    assert out.count("skip ") == len(PDFS)
    assert dump(db) == store


def test_confirmed_field_survives_reingest(tmp_path):
    db = tmp_path / "firstpaycheck.sqlite"
    offer = SAMPLES / "offer_letter.pdf"
    ingest_file(offer, db_path=db)
    field = get_fields(doc=offer.name, db_path=db)[0]
    confirm_field(field["id"], db_path=db)
    ingest_file(offer, db_path=db, force=True)
    again = {f["id"]: f for f in get_fields(doc=offer.name, db_path=db)}
    assert again[field["id"]]["status"] == "confirmed"


def test_default_store_is_in_ignored_data_folder():
    assert DB_PATH.parent == ROOT / "data"
    run = subprocess.run(["git", "check-ignore", "-q", str(DB_PATH.relative_to(ROOT))], cwd=ROOT)
    assert run.returncode == 0, "data/firstpaycheck.sqlite is not git-ignored"

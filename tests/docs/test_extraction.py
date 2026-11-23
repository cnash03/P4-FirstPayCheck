"""Extraction: ingesting the synthetic samples stores every field in their answer files,
with the same value, unit and page, and each field's page holds its source text.

The samples are ingested into a temporary store, the same path python docs/ingest.py takes,
so the test checks what the engine and app will read, not only extract.py on its own.
"""
import json
import re
from pathlib import Path

import pytest

from cite import check_citations, cite
from store import get_fields, get_page, ingest_file

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
DOCS = ["offer_letter", "benefits_guide", "pay_stub"]
COMPARED = ["value", "unit", "plan", "coverage_tier", "doc", "page"]


def norm(text):
    return re.sub(r"\s+", " ", text)


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("store") / "test.sqlite"
    for name in DOCS:
        ingest_file(SAMPLES / f"{name}.pdf", db_path=path)
    return path


@pytest.fixture(params=DOCS)
def sample(request, db):
    spec = json.loads((SAMPLES / "answers" / f"{request.param}.json").read_text())
    expected = {f["id"]: f for f in spec["fields"]}
    stored = {f["id"]: f for f in get_fields(doc=f"{request.param}.pdf", db_path=db)}
    return expected, stored


def test_every_answer_field_is_extracted(sample):
    expected, stored = sample
    assert sorted(set(expected) - set(stored)) == []


def test_nothing_extracted_beyond_the_answers(sample):
    expected, stored = sample
    assert sorted(set(stored) - set(expected)) == []


def test_values_match_the_answer_file(sample):
    expected, stored = sample
    wrong = {i: {k: (stored[i].get(k), f.get(k)) for k in COMPARED if stored[i].get(k) != f.get(k)}
             for i, f in expected.items() if i in stored}
    assert {i: d for i, d in wrong.items() if d} == {}


def test_every_field_starts_unconfirmed(sample):
    _, stored = sample
    assert [i for i, f in stored.items() if f["status"] != "unconfirmed"] == []


def test_every_field_cites_a_stored_page(sample, db):
    _, stored = sample
    problems = [p for f in stored.values() for p in check_citations(cite(f["doc"], f["page"]), db_path=db)]
    assert problems == []


def test_cited_page_holds_the_source_text(sample, db):
    """The page a field links to is the page the user will see; its value must be on it."""
    expected, _ = sample
    lost = [i for i, f in expected.items()
            if norm(f["source_text"]) not in norm(get_page(f["doc"], f["page"], db) or "")]
    assert lost == []

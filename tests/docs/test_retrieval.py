"""Retrieval: for each eval case's question, search_documents returns every page the
case cites among its top 3 hits, each labeled with its document, page and citation.

Only cases whose documents are all synthetic samples run here; a case on a document
kept out of the repo (the Tyler summary) cannot run in CI.
"""
import json
from pathlib import Path

import pytest

from cite import cite
from search import search
from store import ingest_file

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "samples"
CASES = [json.loads(p.read_text()) for p in sorted((ROOT / "eval" / "cases").glob("*.json"))]
RUNNABLE = [c for c in CASES if c["expected"].get("citations")
            and all((SAMPLES / d).is_file() for d in c["docs"])]

# Cases whose answer needs a page the question's own words rank below the top 3: the agent
# finds it with a second search. strict, so the test fails once search finds it and the mark can go.
SECOND_SEARCH = {
    "ex1-take-home": "needs a second search: the question ranks the premiums on benefits_guide.pdf p4 below the top 3",
    "ex3-match-then-roth": "needs a second search: the question ranks the salary on offer_letter.pdf p1 below the top 3",
}
TOP_3 = [pytest.param(c, id=c["id"], marks=pytest.mark.xfail(reason=SECOND_SEARCH[c["id"]], strict=True))
         if c["id"] in SECOND_SEARCH else pytest.param(c, id=c["id"]) for c in RUNNABLE]


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("store") / "test.sqlite"
    for pdf in sorted(SAMPLES.glob("*.pdf")):
        ingest_file(pdf, db_path=path)
    return path


def test_some_cases_run():
    assert len(RUNNABLE) >= 5


@pytest.mark.parametrize("case", TOP_3)
def test_cited_pages_in_top_3(case, db):
    hits = [(h["doc"], h["page"]) for h in search(case["question"], k=3, db_path=db)]
    missing = [cite(c["doc"], c["page"]) for c in case["expected"]["citations"]
               if (c["doc"], c["page"]) not in hits]
    assert missing == [], f"top 3 was {[cite(*h) for h in hits]}"


@pytest.mark.parametrize("case", RUNNABLE, ids=[c["id"] for c in RUNNABLE])
def test_hits_are_labeled(case, db):
    for h in search(case["question"], k=3, db_path=db):
        assert h["cite"] == cite(h["doc"], h["page"]) and h["page"] >= 1

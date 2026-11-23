"""Search the redacted pages: the agent's search_documents tool.

Ranks pages with SQLite FTS5's BM25 over the index docs/store.py builds, and
labels every hit with its document and page, so an answer can cite it.

    python docs/search.py "Should I pick the HDHP or the PPO?"
"""
import re
import sys
from contextlib import closing

from cite import cite
from store import connect

# Words that say nothing about which page answers a question.
STOPWORDS = set("""
a about after all also am an and any are as at be because been before being but by can could did do
does doing for from get got had has have how i if in into is it its just me more my no not now of on
or our out over should so some than that the their them then there these they this those to too up
us very was we were what when where which while who why will with would you your yours
actually really also thing things want need know think
""".split())

# Everyday words a new hire uses, and the words a benefits document uses for them.
SYNONYMS = {
    "high-deductible": ["hdhp"],
    "high deductible": ["hdhp"],
    "company stock": ["espp", "stock purchase"],
    "buy stock": ["espp", "stock purchase"],
    "every two weeks": ["biweekly"],
    "every other week": ["biweekly"],
    "hits my account": ["salary", "paid", "paycheck"],
    "take-home": ["salary", "paid", "paycheck"],
    "take home": ["salary", "paid", "paycheck"],
    "invest": ["401(k)", "match"],
    "retirement": ["401(k)"],
    "roth": ["401(k)"],
    "doctor": ["medical", "deductible", "premium"],
    "health plan": ["medical", "premium", "deductible"],
    "sign up": ["enroll", "enrollment"],
    "deadline": ["enroll", "enrollment"],
    "gross": ["salary", "earnings"],  # pay stubs label gross pay "Regular salary" or "Earnings"
}

# Words searched as another word instead. "employer" stems to the same root as
# "employment", which every offer letter repeats; guides say "the company".
REPLACE = {"employer": "company", "employers": "company"}


def to_fts_query(question):
    """Turn a question into an FTS5 query: its useful words and their synonyms, joined with OR.

    Each term is quoted, so text like "401(k)" or "AND" cannot break FTS5's query syntax.
    """
    q = question.lower()
    terms = []
    for phrase, extra in SYNONYMS.items():
        if phrase in q:
            terms += extra
    terms += [REPLACE.get(w, w) for w in re.findall(r"[a-z0-9]+(?:\.\d+)?", q)
              if w not in STOPWORDS and (len(w) > 1 or w.isdigit())]
    seen, quoted = set(), []
    for t in terms:
        t = t.replace('"', "")
        if t and t not in seen:
            seen.add(t)
            quoted.append(f'"{t}"')
    return " OR ".join(quoted)


def search(query, k=3, doc=None, db_path=None):
    """Return up to k pages for a question, best first: [{doc, page, cite, snippet, score}].

    cite is the page's citation, [benefits_guide.pdf p4], for the answer to copy.
    score is BM25 with the sign flipped, so higher is better. doc limits the search to one document.
    """
    fts = to_fts_query(query)
    if not fts:
        return []
    sql = ("SELECT doc, page, snippet(pages_fts, 0, '[', ']', ' ... ', 16) AS snippet, -bm25(pages_fts) AS score "
           "FROM pages_fts WHERE pages_fts MATCH ?")
    args = [fts]
    if doc:
        sql, args = sql + " AND doc = ?", args + [doc]
    with closing(connect(db_path)) as con:
        rows = con.execute(sql + " ORDER BY bm25(pages_fts) LIMIT ?", args + [k]).fetchall()
    return [{"doc": r["doc"], "page": r["page"], "cite": cite(r["doc"], r["page"]), "snippet": re.sub(r"\s+", " ", r["snippet"]).strip(),
             "score": round(r["score"], 3)} for r in rows]


# The tool as the agent sees it (Anthropic tool-use format).
SEARCH_TOOL = {
    "name": "search_documents",
    "description": "Search the user's uploaded documents (offer letter, benefits guide, pay stub). "
                   "Returns the best-matching pages, each labeled with its document and page number, "
                   "with a snippet and its citation. Copy the citation, e.g. [benefits_guide.pdf p4], "
                   "after any value you use from that page.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to look for, in plain words."},
            "k": {"type": "integer", "description": "How many pages to return (default 3).", "minimum": 1, "maximum": 10},
            "doc": {"type": "string", "description": "Optional: only this document, e.g. benefits_guide.pdf."},
        },
        "required": ["query"],
    },
}


def search_documents(query, k=3, doc=None, db_path=None):
    """The tool call: the same as search(), named for the agent."""
    return search(query, k=k, doc=doc, db_path=db_path)


def main():
    if len(sys.argv) < 2:
        sys.exit('usage: python docs/search.py "<question>" [k]')
    k = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    for i, hit in enumerate(search(sys.argv[1], k=k), start=1):
        print(f"{i}. {hit['cite']}  (score {hit['score']})\n   {hit['snippet']}")


if __name__ == "__main__":
    main()

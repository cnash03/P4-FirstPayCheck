"""Citations: the one way an answer names the page a value came from.

A citation is written [<doc> p<page>], e.g. [benefits_guide.pdf p4]. Search hits carry
it ready-made in "cite", a field record's is cite(f["doc"], f["page"]), the agent copies
it into its answer, the chat panel turns it into a link to the redacted page, and the
eval compares parse_citations(answer) with a case's expected citations.

    python docs/cite.py "The HDHP premium is $468 a year [benefits_guide.pdf p4]."
"""
import re
import sys

from store import get_page

# The doc is a stored file name (it may contain spaces); the page is 1-based, as stored.
CITATION = re.compile(r"\[([^\[\]]+?\.pdf) p(\d+)\]")


def cite(doc, page):
    """The citation for one page: [benefits_guide.pdf p4]."""
    return f"[{doc} p{page}]"


def parse_citations(answer):
    """Return the pages an answer cites, in order, each once: [{doc, page}]."""
    seen, out = set(), []
    for m in CITATION.finditer(answer):
        key = (m.group(1), int(m.group(2)))
        if key not in seen:
            seen.add(key)
            out.append({"doc": key[0], "page": key[1]})
    return out


def check_citations(answer, db_path=None):
    """Return one problem per cited page that is not in the store; [] when every citation resolves."""
    return [f"{cite(c['doc'], c['page'])} is not a page in the store"
            for c in parse_citations(answer) if get_page(c["doc"], c["page"], db_path) is None]


# The tool as the agent sees it (Anthropic tool-use format), next to search_documents.
GET_PAGE_TOOL = {
    "name": "get_page",
    "description": "Read the full redacted text of one page of the user's documents, e.g. a page "
                   "search_documents returned, before quoting a value from it. Cite it as [<doc> p<page>].",
    "input_schema": {
        "type": "object",
        "properties": {
            "doc": {"type": "string", "description": "The document, as search returns it, e.g. benefits_guide.pdf."},
            "page": {"type": "integer", "description": "The page number, starting at 1.", "minimum": 1},
        },
        "required": ["doc", "page"],
    },
}


def get_page_tool(doc, page, db_path=None):
    """The tool call: {doc, page, cite, text}, or {error} for a page that is not stored."""
    text = get_page(doc, page, db_path)
    if text is None:
        return {"error": f"no page {page} in {doc}; search_documents lists the pages that exist"}
    return {"doc": doc, "page": page, "cite": cite(doc, page), "text": text}


def main():
    if len(sys.argv) != 2:
        sys.exit('usage: python docs/cite.py "<answer>"')
    for c in parse_citations(sys.argv[1]):
        print(cite(c["doc"], c["page"]))
    problems = check_citations(sys.argv[1])
    for p in problems:
        print("MISSING", p)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()

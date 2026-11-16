"""Controlled FTS syntax and parameter-bound SQL; never execute raw user MATCH."""

import re
import unicodedata

from dblp_local_search.search.models import Search, Term

COLUMNS = {"title": "title", "authors": "authors_text", "venue": "venue"}

#转换单一的查询 over review
def atom(term: Term) -> str:
    words = re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", term.text), re.UNICODE)
    if not words:
        raise ValueError("Text must contain letters or digits")
    pieces = (
        ['"' + " ".join(words) + '"']
        if term.phrase
        else [f'"{word}"' for word in words]
    )
    expression = "(" + " AND ".join(pieces) + ")"
    if term.field != "all":
        expression = f"{COLUMNS[term.field]} : {expression}"
    return expression

#over review 转换Search为具体的sql条件
def predicate(request: Search) -> tuple[str, list[object]]:
    clauses: list[str] = [] 
    params: list[object] = []
    positives = [atom(term) for term in request.query.all_of]
    if request.query.any_of:
        positives.append(
            "(" + " OR ".join(atom(term) for term in request.query.any_of) + ")"
        )
    if positives:
        expression = " AND ".join(positives)
        for term in request.query.none_of:
            expression = f"({expression}) NOT ({atom(term)})"
        clauses.append("p.id IN (SELECT rowid FROM paper_fts WHERE paper_fts MATCH ?)")
        params.append(expression)
    else:
        for term in request.query.none_of:
            clauses.append(
                "p.id NOT IN (SELECT rowid FROM paper_fts WHERE paper_fts MATCH ?)"
            )
            params.append(atom(term))
    if request.year_from:
        clauses.append("p.year >= ?")
        params.append(request.year_from)
    if request.year_to:
        clauses.append("p.year <= ?")
        params.append(request.year_to)
    if request.venues:
        clauses.append("p.venue IN (" + ",".join("?" for _ in request.venues) + ")")
        params.extend(request.venues)
    if request.author_id:
        clauses.append("p.id IN (SELECT paper_id FROM paper_authors WHERE author_id=?)")
        params.append(request.author_id)
    return " AND ".join(clauses) or "1", params

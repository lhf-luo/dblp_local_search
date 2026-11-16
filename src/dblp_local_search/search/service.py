"""Read-only DBLP queries; deterministic row-ID keyset pagination."""

import json
import sqlite3
from typing import Any

from dblp_local_search.config import Settings
from dblp_local_search.search.cursor import decode, encode, fingerprint
from dblp_local_search.search.models import Search, Term
from dblp_local_search.search.query import atom, predicate
from dblp_local_search.storage.database import database


def paper_dict(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    value["authors"] = json.loads(value.pop("authors_json"))
    value["external_urls"] = json.loads(value.pop("urls"))
    value.pop("id", None)
    return value


def search(settings: Settings, request: Search) -> dict[str, Any]:
    signature = fingerprint(request.model_dump())
    last = decode(request.cursor, signature)
    condition, params = predicate(request)
    with database(settings.data_dir, settings.query_timeout) as connection:
        total = (
            connection.execute(
                f"SELECT count(*) FROM papers p WHERE {condition}", params
            ).fetchone()[0]
            if request.include_total
            else None
        )
        rows = connection.execute(
            f"SELECT p.* FROM papers p WHERE ({condition}) AND p.id>? ORDER BY p.id LIMIT ?",
            [*params, last, request.page_size + 1],
        ).fetchall()
        more = len(rows) > request.page_size
        rows = rows[: request.page_size]
        return {
            "items": [paper_dict(row) for row in rows],
            "total": total,
            "next_cursor": encode(rows[-1]["id"], signature) if more else None,
            "warnings": [],
        }


def lookup(
    settings: Settings, key: str | None = None, doi: str | None = None
) -> dict[str, Any]:
    with database(settings.data_dir, settings.query_timeout) as connection:
        column, value = ("dblp_key", key) if key else ("doi", doi)
        rows = connection.execute(
            f"SELECT * FROM papers WHERE {column}=? ORDER BY id LIMIT 100", (value,)
        ).fetchall()
        return {"items": [paper_dict(row) for row in rows]}


def authors(
    settings: Settings, name: str, page_size: int, cursor: str | None
) -> dict[str, Any]:
    signature = fingerprint({"author_search": name, "page_size": page_size})
    last = decode(cursor, signature)
    expression = atom(Term(text=name, field="all"))
    with database(settings.data_dir, settings.query_timeout) as connection:
        condition = "id IN (SELECT rowid FROM author_fts WHERE author_fts MATCH ?)"
        total = connection.execute(
            f"SELECT count(*) FROM authors WHERE {condition}", (expression,)
        ).fetchone()[0]
        rows = connection.execute(
            f"SELECT * FROM authors WHERE {condition} AND id>? ORDER BY id LIMIT ?",
            (expression, last, page_size + 1),
        ).fetchall()
        more, rows = len(rows) > page_size, rows[:page_size]
        items = [
            {
                "author_id": row["id"],
                "name": row["name"],
                "pid": row["pid"],
                "identity_verified": row["pid"] is not None,
            }
            for row in rows
        ]
        return {
            "items": items,
            "total": total,
            "next_cursor": encode(rows[-1]["id"], signature) if more else None,
        }


def dataset(settings: Settings) -> dict[str, Any]:
    with database(settings.data_dir, settings.query_timeout) as connection:
        metadata = {
            row["key"]: json.loads(row["value"])
            for row in connection.execute("SELECT * FROM metadata")
        }
    try:
        metadata["update"] = json.loads(
            (settings.data_dir / "update-status.json").read_text()
        )
    except (OSError, ValueError):
        metadata["update"] = None
    return metadata

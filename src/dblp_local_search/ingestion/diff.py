"""Incremental diff of the new dump against the copied active database."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dblp_local_search.ingestion.build import (
    insert_record,
    record_hash,
    update_record,
    validate,
    write_metadata,
)
from dblp_local_search.ingestion.parser import records


# 增量更新数据库表的内容。 over review
def apply_incremental(
    connection: sqlite3.Connection, xml: Path, dtd: Path
) -> dict[str, Any]:
    """Upsert changed records, remove unseen keys, then validate.

    The input is the trusted official dump. The database is a private staging
    copy, so partial commits are safe and discarded if the update fails.
    """
    connection.execute(
        "CREATE TEMP TABLE seen_keys(dblp_key TEXT PRIMARY KEY) WITHOUT ROWID"
    )
    counts = {"added": 0, "updated": 0, "unchanged": 0, "deleted": 0}
    processed = 0
    for record in records(xml, dtd):
        digest = record_hash(record)
        row = connection.execute(
            "SELECT id, content_hash FROM papers WHERE dblp_key=?", (record.key,)
        ).fetchone()
        if row is None:
            insert_record(connection, record, digest)
            counts["added"] += 1
        elif row["content_hash"] != digest:  # hash不同，dblp_key不同，说明需要执行更新
            update_record(connection, row["id"], record, digest)
            counts["updated"] += 1
        else:
            counts["unchanged"] += 1
        connection.execute("INSERT OR IGNORE INTO seen_keys VALUES(?)", (record.key,))
        processed += 1
        if processed % 5000 == 0:
            connection.commit()
            print(f"Compared {processed} publications", flush=True)
    if processed == 0:
        raise ValueError("Dump contains no publications")
    connection.commit()
    # 额外的处理，用于删除新版本中不存在的键
    connection.execute(
        "CREATE TEMP TABLE removed_ids AS "
        "SELECT id FROM papers WHERE dblp_key NOT IN (SELECT dblp_key FROM seen_keys)"
    )
    counts["deleted"] = connection.execute(
        "SELECT count(*) FROM removed_ids"
    ).fetchone()[0]
    connection.execute(
        "DELETE FROM paper_fts WHERE rowid IN (SELECT id FROM removed_ids)"
    )
    connection.execute(
        "DELETE FROM paper_authors WHERE paper_id IN (SELECT id FROM removed_ids)"
    )
    connection.execute("DELETE FROM papers WHERE id IN (SELECT id FROM removed_ids)")
    if counts["deleted"] or counts["updated"]:
        connection.execute(
            "DELETE FROM authors WHERE id NOT IN (SELECT DISTINCT author_id FROM paper_authors)"
        )
    paper_count = connection.execute("SELECT count(*) FROM papers").fetchone()[0]
    author_count = connection.execute("SELECT count(*) FROM authors").fetchone()[0]
    write_metadata(
        connection,
        {
            "paper_count": paper_count,
            "author_count": author_count,
            "built_at": datetime.now(UTC).isoformat(),
        },
    )
    connection.commit()
    validate(connection, paper_count)
    return {**counts, "paper_count": paper_count, "author_count": author_count}

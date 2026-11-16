"""Shared row writes and full initialization of the DBLP database."""

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from dblp_local_search.ingestion.parser import Record, records
from dblp_local_search.storage.schema import INDEXES, create_schema


# 一条记录对应的hash值，防止重复插入
def record_hash(record: Record) -> str:
    """Canonical hash of fields used in the database; detects real changes."""
    payload = {
        "key": record.key,
        "title": record.title,
        "year": record.year,
        "venue": record.venue,
        "doi": record.doi,
        "urls": list(record.urls),
        "authors": [list(author) for author in record.authors],
    }
    encoded = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


# 作者表更新
def author_id(connection: sqlite3.Connection, name: str, pid: str | None) -> int:
    # Name-only entries are provisional labels, not verified person identities.
    identity = (
        f"pid:{pid}" if pid else "name:" + hashlib.sha256(name.encode()).hexdigest()
    )
    connection.execute(
        "INSERT OR IGNORE INTO authors(identity,name,pid) VALUES(?,?,?)",
        (identity, name, pid),
    )
    row = connection.execute(
        "SELECT id FROM authors WHERE identity=?", (identity,)
    ).fetchone()
    return cast(int, row[0])


# over review fts更新
def _write_paper_values(
    connection: sqlite3.Connection, paper_id: int, record: Record
) -> None:
    # 检索表需要用到
    connection.execute("DELETE FROM paper_fts WHERE rowid=?", (paper_id,))  # 删除论文
    connection.execute(
        "INSERT INTO paper_fts(rowid,title,authors_text,venue) VALUES(?,?,?,?)",
        (
            paper_id,
            record.title,
            " ".join(name for name, _ in record.authors),
            record.venue or "",
        ),
    )
    # 作者关联表，用于论文的第几个作者
    connection.execute("DELETE FROM paper_authors WHERE paper_id=?", (paper_id,))
    # 论文关联的作者
    for position, (name, pid) in enumerate(record.authors):
        identifier = author_id(connection, name, pid)
        connection.execute(
            "INSERT INTO paper_authors VALUES(?,?,?)", (paper_id, identifier, position)
        )


# 插入一条记录 over review
def insert_record(
    connection: sqlite3.Connection, record: Record, content_hash: str | None = None
) -> int:
    cursor = connection.execute(
        "INSERT INTO papers(dblp_key,title,year,venue,doi,record_url,urls,authors_json,content_hash) VALUES(?,?,?,?,?,?,?,?,?)",
        (
            record.key,
            record.title,
            record.year,
            record.venue,
            record.doi,
            f"https://dblp.org/rec/{record.key}",
            json.dumps(record.urls),
            json.dumps([name for name, _ in record.authors], ensure_ascii=False),
            content_hash or record_hash(record),
        ),
    )
    paper_id = cast(int, cursor.lastrowid)  # 返回的行号，唯一id？
    _write_paper_values(connection, paper_id, record)
    return paper_id


# 更新一条记录 over review
def update_record(
    connection: sqlite3.Connection,
    paper_id: int,
    record: Record,
    content_hash: str,
) -> None:
    connection.execute(
        "UPDATE papers SET title=?,year=?,venue=?,doi=?,record_url=?,urls=?,authors_json=?,content_hash=? WHERE id=?",
        (
            record.title,
            record.year,
            record.venue,
            record.doi,
            f"https://dblp.org/rec/{record.key}",
            json.dumps(record.urls),
            json.dumps([name for name, _ in record.authors], ensure_ascii=False),
            content_hash,
            paper_id,
        ),
    )
    _write_paper_values(connection, paper_id, record)


# 写元数据的表 over review
def write_metadata(connection: sqlite3.Connection, values: dict[str, Any]) -> None:
    connection.executemany(
        "INSERT OR REPLACE INTO metadata VALUES(?,?)",
        [(key, json.dumps(value)) for key, value in values.items()],
    )


# 核心代码，建立数据库 over review
def build(xml: Path, dtd: Path, target: Path) -> dict[str, Any]:
    if target.exists():
        raise ValueError("Build target must be a new file")
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target)
    count = 0
    try:
        create_schema(connection)  # 创建表
        # 每5000 提交一次
        for record in records(xml, dtd):
            insert_record(connection, record)  # 插入一条记录
            count += 1
            if count % 5000 == 0:
                connection.commit()
                print(f"Imported {count} publications", flush=True)
        if count == 0:
            raise ValueError("Dump contains no publications")
        connection.commit()
        connection.executescript(INDEXES)  # 建立索引
        connection.execute(
            "INSERT INTO author_fts(rowid,name) SELECT id,name FROM authors"
        )  # 作者表更新
        # 不清楚，提升查询的性能
        connection.execute("INSERT INTO paper_fts(paper_fts) VALUES('optimize')")
        connection.execute("INSERT INTO author_fts(author_fts) VALUES('optimize')")
        metadata: dict[str, Any] = {
            "paper_count": count,
            "author_count": connection.execute(
                "SELECT count(*) FROM authors"
            ).fetchone()[0],
            "built_at": datetime.now(UTC).isoformat(),
        }
        write_metadata(connection, metadata)
        connection.commit()  # 提交事务
        validate(connection, count)
        return metadata  # 返回元数据
    finally:
        connection.close()


# 最后检测一般数据表 over review
def validate(connection: sqlite3.Connection, expected: int) -> None:
    if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise ValueError("SQLite integrity check failed")
    if connection.execute("SELECT count(*) FROM paper_fts").fetchone()[0] != expected:
        raise ValueError("Publication/FTS row counts differ")
    connection.execute("INSERT INTO paper_fts(paper_fts) VALUES('integrity-check')")
    connection.execute("INSERT INTO author_fts(author_fts) VALUES('integrity-check')")
    connection.commit()

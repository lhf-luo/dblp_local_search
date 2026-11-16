"""Read-only active database connections and atomic file publication."""

import json
import os
import sqlite3
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from time import monotonic
from typing import Any


class NotReady(Exception):
    pass


class QueryTimedOut(Exception):
    pass


# 原子写入json文件
def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)  # 目录存在页不报错
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


# 返回元数据信息
def read_metadata(connection: sqlite3.Connection) -> dict[str, Any]:
    return {
        row[0]: json.loads(row[1])
        for row in connection.execute("SELECT key,value FROM metadata")
    }


# 数据库连接
@contextmanager
def database(root: Path, timeout: float) -> Iterator[sqlite3.Connection]:
    path = root / "dblp.sqlite"
    if not path.is_file():
        raise NotReady("No published dataset; initialize it first")
    connection = sqlite3.connect(
        path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True
    )
    connection.row_factory = sqlite3.Row
    deadline = monotonic() + timeout
    connection.set_progress_handler(lambda: int(monotonic() > deadline), 1000)
    try:
        yield connection
    except sqlite3.OperationalError as error:
        if "interrupted" in str(error).lower():
            raise QueryTimedOut(
                "Query time budget exceeded; narrow your query"
            ) from error
        raise
    finally:
        connection.close()


# 返回元数据信息 over review
def active_metadata(root: Path) -> dict[str, Any]:
    with database(root, 15) as connection:
        return read_metadata(connection)

#替换文件 over review
def publish(candidate: Path, root: Path) -> None:
    """Same-filesystem atomic replacement; Linux open readers retain the old inode.

    On Windows replacement may fail if a reader holds the file; the old file stays.
    No new queries are routed to the old database after successful replacement.
    """
    with candidate.open("r+b") as stream:
        os.fsync(stream.fileno())
    os.replace(candidate, root / "dblp.sqlite")
    if os.name == "posix":
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

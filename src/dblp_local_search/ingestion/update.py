"""Full initialization or incremental update, then atomic database replacement."""

import shutil
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout

from dblp_local_search.config import Settings
from dblp_local_search.ingestion.build import build, write_metadata
from dblp_local_search.ingestion.diff import apply_incremental
from dblp_local_search.ingestion.download import DTD_URL, XML_URL, fetch
from dblp_local_search.ingestion.validate import validate_size
from dblp_local_search.storage.database import (
    NotReady,
    active_metadata,
    atomic_json,
    publish,
)


def now() -> str:
    return datetime.now(UTC).isoformat()


# 过渡的中间函数 over review
def update(
    settings: Settings,
    *,
    force: bool = False,
    full: bool = False,
    xml: Path | None = None,
    dtd: Path | None = None,
) -> dict[str, Any]:
    """Lock, obtain source, diff/rebuild a staging database, and publish it."""
    root = settings.data_dir
    root.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(root / "update.lock", timeout=0):
            return locked_update(settings, force, full, xml, dtd)
    except Timeout:
        print("Update already running; skipped", flush=True)
        return {"state": "busy"}


# 整体的更新入口 over review
def locked_update(
    settings: Settings,
    force: bool,
    full: bool,
    xml: Path | None,
    dtd: Path | None,
) -> dict[str, Any]:
    root = settings.data_dir
    stage = root / "staging"
    for source in (xml, dtd):
        if source is not None and Path(source).resolve().is_relative_to(
            stage.resolve()
        ):
            raise ValueError("Local XML/DTD must be outside the staging directory")
    if stage.exists():
        shutil.rmtree(stage)  # 删除目录
    stage.mkdir(parents=True)
    status: dict[str, Any] = {"state": "running", "started_at": now()}
    atomic_json(root / "update-status.json", status)
    try:
        source = prepare_source(root, stage, force, xml, dtd)
        if source is None:
            status.update(state="unchanged", finished_at=now())
        else:
            source_xml, source_dtd, upstream = source
            candidate = stage / "dblp.sqlite"
            if full or not (root / "dblp.sqlite").is_file():  # 全量更新
                metadata = build(source_xml, source_dtd, candidate)  # 建立库
                write_upstream(candidate, upstream)
                status.update(mode="full", **metadata)  # 更新状态
            else:
                copy_database(root / "dblp.sqlite", candidate)
                stats = apply_incremental_to(  # 增量更新
                    candidate, source_xml, source_dtd, upstream
                )
                if not (stats["added"] or stats["updated"] or stats["deleted"]):
                    status.update(
                        state="unchanged",
                        finished_at=now(),
                        mode="incremental",
                        stats=stats,
                    )
                    atomic_json(root / "update-status.json", status)
                    return status
                status.update(mode="incremental", **stats)
            if not full:
                validate_size(root, status["paper_count"], settings.min_record_ratio)
            publish(candidate, root)
            status.update(state="succeeded", finished_at=now())
        atomic_json(root / "update-status.json", status)
        return status
    except Exception as error:
        status.update(
            state="failed", finished_at=now(), error=f"{type(error).__name__}: {error}"
        )
        atomic_json(root / "update-status.json", status)
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)


# 数据更新 over review
def apply_incremental_to(
    candidate: Path, xml: Path, dtd: Path, upstream: dict[str, Any]
) -> dict[str, Any]:
    connection = sqlite3.connect(candidate)
    connection.row_factory = sqlite3.Row
    with closing(connection) as connection, connection:
        stats = apply_incremental(connection, xml, dtd)
        write_metadata(connection, {"upstream": upstream})
        connection.commit()
        return stats


# over review
def write_upstream(candidate: Path, upstream: dict[str, Any]) -> None:
    with closing(sqlite3.connect(candidate)) as connection, connection:
        write_metadata(connection, {"upstream": upstream})
        connection.commit()


# 备份数据库 over review
def copy_database(source: Path, target: Path) -> None:
    """Consistent SQLite backup; does not copy a live file byte-for-byte."""
    if target.exists():
        raise ValueError("Copy target must be a new file")
    source_connection = sqlite3.connect(
        source.resolve().as_uri() + "?mode=ro", uri=True
    )
    target_connection = sqlite3.connect(target)
    try:
        source_connection.backup(target_connection)
    finally:
        source_connection.close()
        target_connection.close()


# 数据下载 over reivew
def prepare_source(
    root: Path,
    stage: Path,
    force: bool,
    xml: Path | None,
    dtd: Path | None,
) -> tuple[Path, Path, dict[str, Any]] | None:
    """stage: temporary work dir; force: skip HTTP cache; xml/dtd: local inputs."""
    if (xml is None) != (dtd is None):
        raise ValueError("--xml and --dtd must be provided together")
    if xml is not None:
        return xml, dtd, {"kind": "local-files"}
    try:
        previous = active_metadata(root).get("upstream", {})
    except NotReady:
        previous = {}
    target = stage / "dblp.xml.gz"
    xml_meta = fetch(XML_URL, target, previous.get("xml"), force)
    if xml_meta is None:
        return None
    dtd_target = stage / "dblp.dtd"
    dtd_meta = fetch(DTD_URL, dtd_target, force=True)
    return target, dtd_target, {"xml": xml_meta, "dtd": dtd_meta}

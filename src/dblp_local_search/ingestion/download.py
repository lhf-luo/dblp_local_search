"""Download only the official DBLP dump and DTD, streaming to temporary files."""

import hashlib
import logging
import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import httpx

XML_URL = "https://dblp.org/xml/dblp.xml.gz"
DTD_URL = "https://dblp.org/xml/dblp.dtd"

logger = logging.getLogger(__name__)

# 进度日志间隔（秒）
_PROGRESS_INTERVAL = 5.0


def _fmt_bytes(n: float) -> str:
    """把字节数格式化成人类可读的字符串。"""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


# 下载文件
def fetch(
    url: str,
    target: Path,
    previous: Mapping[str, Any] | None = None,
    force: bool = False,
) -> dict[str, Any] | None:
    headers: dict[str, str] = {
        "User-Agent": "dblp-local-search/0.1 (offline metadata indexing)"
    }
    if previous and not force:
        if previous.get("etag"):
            headers["If-None-Match"] = cast(str, previous["etag"])
        if previous.get("last_modified"):
            headers["If-Modified-Since"] = cast(str, previous["last_modified"])
    digest = hashlib.sha256()
    size = 0
    with httpx.stream(
        "GET",
        url,
        headers=headers,
        timeout=httpx.Timeout(120, connect=30),
        follow_redirects=True,
    ) as response:
        if response.status_code == 304:
            logger.info("未更改 (304): %s", url)
            return None  # 未更改
        response.raise_for_status()

        # 总大小可能缺失（chunked / 代理改写），拿不到就只报已下载量
        total_header = response.headers.get("content-length")
        total: int | None = int(total_header) if total_header else None

        start = time.monotonic()
        last_log = start
        last_size = 0

        logger.info(
            "开始下载: %s -> %s (总大小: %s)",
            url,
            target,
            _fmt_bytes(total) if total else "未知",
        )

        with target.open("wb") as stream:
            for chunk in response.iter_bytes(1024 * 1024):
                stream.write(chunk)
                digest.update(chunk)
                size += len(chunk)

                now = time.monotonic()
                if now - last_log >= _PROGRESS_INTERVAL:
                    elapsed = now - start
                    avg = size / elapsed if elapsed > 0 else 0.0
                    inst = (size - last_size) / (now - last_log) if now > last_log else 0.0

                    if total:
                        pct = size / total * 100
                        eta = (total - size) / avg if avg > 0 else 0.0
                        logger.info(
                            "下载进度: %.1f%% (%s/%s), 瞬时 %.2f MB/s, 平均 %.2f MB/s, ETA %.0fs",
                            pct,
                            _fmt_bytes(size),
                            _fmt_bytes(total),
                            inst / 1048576,
                            avg / 1048576,
                            eta,
                        )
                    else:
                        logger.info(
                            "下载进度: %s, 瞬时 %.2f MB/s, 平均 %.2f MB/s",
                            _fmt_bytes(size),
                            inst / 1048576,
                            avg / 1048576,
                        )
                    last_log = now
                    last_size = size

            stream.flush()
            os.fsync(stream.fileno())

        elapsed = time.monotonic() - start
        avg = size / elapsed if elapsed > 0 else 0.0
        logger.info(
            "下载完成: %s, 耗时 %.1fs, 平均 %.2f MB/s",
            _fmt_bytes(size),
            elapsed,
            avg / 1048576,
        )

        if size == 0:
            raise ValueError("Empty upstream file")
        if target.suffix == ".gz":
            with target.open("rb") as stream:
                if stream.read(2) != b"\x1f\x8b":
                    raise ValueError(
                        "Dump is not gzip; upstream may have returned a challenge page"
                    )
        return {
            "etag": response.headers.get("etag"),
            "last_modified": response.headers.get("last-modified"),
            "sha256": digest.hexdigest(),
            "bytes": size,
        }
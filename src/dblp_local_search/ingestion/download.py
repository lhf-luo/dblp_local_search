"""Download only the official DBLP dump and DTD, streaming to temporary files."""

import hashlib
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import httpx

XML_URL = "https://dblp.org/xml/dblp.xml.gz"
DTD_URL = "https://dblp.org/xml/dblp.dtd"


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
            return None  # 未更改
        response.raise_for_status()
        with target.open("wb") as stream:
            for chunk in response.iter_bytes(1024 * 1024):
                stream.write(chunk)
                digest.update(chunk)
                size += len(chunk)
            stream.flush()
            os.fsync(stream.fileno())
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

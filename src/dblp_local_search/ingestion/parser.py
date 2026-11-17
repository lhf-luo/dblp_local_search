"""Streaming DBLP XML, resolving only the explicitly supplied local DTD."""

import gzip
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

from lxml import etree

RECORD_TAGS = {
    "article",
    "inproceedings",
    "proceedings",
    "book",
    "incollection",
    "phdthesis",
    "mastersthesis",
}


# 解析xml的辅助函数
class LocalDtdResolver(etree.Resolver):
    def __init__(self, dtd: Path, xml: Path) -> None:
        self.dtd: Path = dtd.resolve()
        self.reference: Path = (xml.resolve().parent / "dblp.dtd").resolve()

    def resolve(self, url: str, public_id: str | None, context: Any) -> Any:
        # No HTTP, file:// or arbitrary local path resolution. DBLP declares dblp.dtd.
        parsed = urlsplit(url)
        local_path = (
            Path(url2pathname(unquote(parsed.path)))
            if parsed.scheme == "file" and not parsed.netloc
            else None
        )
        if (
            url == "dblp.dtd"
            or url == str(self.dtd)
            or (
                local_path is not None
                and local_path.resolve() in (self.dtd, self.reference)
            )
        ):
            return self.resolve_filename(str(self.dtd), context)
        raise ValueError("XML references an unapproved external resource")


# 一条记录
@dataclass(frozen=True)
class Record:
    key: str
    title: str
    year: int | None
    venue: str | None
    doi: str | None
    urls: tuple[str, ...]
    authors: tuple[tuple[str, str | None], ...]


# 辅助函数
def node_text(node: etree._Element | None) -> str:
    return " ".join("".join(node.itertext()).split()) if node is not None else ""


# 解析一条记录
def parse_record(node: etree._Element) -> Record:
    title, key = node_text(node.find("title")), node.get("key")
    if not title or not key:
        raise ValueError("DBLP publication missing key/title")
    year = node_text(node.find("year"))
    urls = tuple(
        dict.fromkeys(node_text(link) for link in node.findall("ee") if node_text(link))
    )
    doi = node_text(node.find("doi")) or next(
        (url for url in urls if re.match(r"https?://(?:dx\.)?doi\.org/", url, re.I)), ""
    )
    doi = (
        re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.I).casefold() or None
    )
    authors = node.findall("author") or node.findall("editor")
    return Record(
        key,
        title,
        int(year) if year.isdigit() else None,
        node_text(node.find("booktitle")) or node_text(node.find("journal")) or None,
        doi,
        urls,
        tuple((node_text(author), author.get("pid")) for author in authors),
    )


# 过滤条件
def predicate(record: Record) -> bool:
    """
    读取环境变量，或者写死？
    """
    if record.year is not None and record.year < 2000:
        return False

    return True


# 流式读取xml文件 over review
def records(xml: Path, dtd: Path) -> Iterator[Record]:
    """Never materialize the document tree; drop each top-level node after use.

    Input is the trusted official dump, not user-uploaded XML. Entity expansion
    keeps libxml2 safety limits (huge_tree=False); unexpected entities fail closed.
    """
    opener = gzip.open if xml.suffix == ".gz" else open
    with opener(xml, "rb") as stream:
        header = stream.read(65536)
        if b"<!ENTITY" in header or re.search(rb"<!DOCTYPE[^>]*\[", header):
            raise ValueError("XML contains an unapproved internal entity declaration")
        stream.seek(0)
        parser = etree.iterparse(
            stream,
            events=("end",),
            load_dtd=True,
            resolve_entities=True,
            no_network=True,
            huge_tree=False,
            collect_ids=False,
        )
        parser.resolvers.add(LocalDtdResolver(dtd, xml))
        for _, node in parser:
            parent = node.getparent()
            if parent is None or parent.tag != "dblp":
                continue
            if node.tag in RECORD_TAGS:
                record = parse_record(node)
                if predicate(record):
                    yield record
            node.clear()
            while node.getprevious() is not None:
                del parent[0]
        if parser.root.tag != "dblp":
            raise ValueError("Not a DBLP XML document")

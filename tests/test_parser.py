import gzip
from pathlib import Path

import pytest

from dblp_local_search.ingestion.parser import records
from dblp_local_search.ingestion.update import update
from dblp_local_search.search.models import Search
from dblp_local_search.search.service import lookup, search
from dblp_local_search.storage.database import active_metadata

FIXTURES = Path(__file__).parent / "fixtures"


def test_gzip_and_entity_resolution(settings, tmp_path):
    source = tmp_path / "dblp.xml.gz"
    with gzip.open(source, "wb") as stream:
        stream.write((FIXTURES / "dblp.xml").read_bytes())
    # DTD is explicitly selected, not whatever file is adjacent to the input.
    result = update(settings, xml=source, dtd=FIXTURES / "dblp.dtd")
    assert result["paper_count"] == 3


def test_reject_unapproved_remote_dtd(tmp_path):
    xml = tmp_path / "bad.xml"
    xml.write_text('<!DOCTYPE dblp SYSTEM "https://example.org/other.dtd"><dblp/>')
    with pytest.raises(ValueError, match="unapproved"):
        tuple(records(xml, FIXTURES / "dblp.dtd"))


def test_update_replaces_only_active_database(populated):
    first = search(populated, Search(year_from=2020))
    update(populated, xml=FIXTURES / "dblp.xml", dtd=FIXTURES / "dblp.dtd")
    second = search(populated, Search(year_from=2020))
    assert first == second
    assert list(populated.data_dir.rglob("*.sqlite")) == [
        populated.data_dir / "dblp.sqlite"
    ]
    assert not (populated.data_dir / "snapshots").exists()
    assert not (populated.data_dir / "current.json").exists()
    assert not (populated.data_dir / "staging").exists()


def test_large_record_drop_refuses_publication(populated, tmp_path):
    original = search(populated, Search(year_from=2020))
    xml = tmp_path / "small.xml"
    xml.write_text(
        '<dblp><article key="one"><title>Single</title><year>2024</year></article></dblp>'
    )
    with pytest.raises(ValueError, match="lost too many"):
        update(populated, xml=xml, dtd=FIXTURES / "dblp.dtd")
    assert search(populated, Search(year_from=2020)) == original


def variant_xml(tmp_path: Path) -> Path:
    xml = (FIXTURES / "dblp.xml").read_text(encoding="utf-8")
    xml = xml.replace("for Security</title>", "for Security v2</title>", 1)
    start = xml.index('<article key="journals/Two23">')
    end = xml.index("</article>", start) + len("</article>")
    xml = xml[:start] + xml[end:]
    xml = xml.replace(
        "</dblp>",
        '<inproceedings key="conf/icse/Four26"><author pid="s/Alice">Alice Smith</author>'
        "<title>Incremental Systems</title><year>2026</year><booktitle>ICSE</booktitle>"
        "</inproceedings></dblp>",
    )
    target = tmp_path / "dblp-v2.xml"
    target.write_text(xml, encoding="utf-8")
    return target


def test_incremental_add_update_delete(populated, tmp_path, monkeypatch):
    from dblp_local_search.ingestion import update as update_module
    from dblp_local_search.ingestion.update import update

    monkeypatch.setattr(
        update_module,
        "build",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("must not rebuild")
        ),
    )
    result = update(populated, xml=variant_xml(tmp_path), dtd=FIXTURES / "dblp.dtd")
    assert result["mode"] == "incremental"
    assert result["added"] == 1 and result["updated"] == 1 and result["deleted"] == 1
    assert result["paper_count"] == 3
    assert (
        search(populated, Search(year_from=2026))["items"][0]["title"]
        == "Incremental Systems"
    )
    assert (
        search(populated, Search(year_from=2024))["items"][0]["title"]
        == "Graph Learning for Security v2"
    )
    assert lookup(populated, key="journals/Two23")["items"] == []
    assert active_metadata(populated.data_dir)["paper_count"] == 3
    assert not (populated.data_dir / "staging").exists()


def test_unchanged_incremental_does_not_publish(populated):
    before = (populated.data_dir / "dblp.sqlite").read_bytes()
    result = update(populated, xml=FIXTURES / "dblp.xml", dtd=FIXTURES / "dblp.dtd")
    assert result["state"] == "unchanged" and result["mode"] == "incremental"
    assert result["stats"] == {
        "added": 0,
        "updated": 0,
        "unchanged": 3,
        "deleted": 0,
        "paper_count": 3,
        "author_count": 3,
    }
    assert (populated.data_dir / "dblp.sqlite").read_bytes() == before


def test_full_rebuild_ignores_old_database(populated, tmp_path):
    result = update(
        populated, full=True, xml=variant_xml(tmp_path), dtd=FIXTURES / "dblp.dtd"
    )
    assert result["mode"] == "full" and result["paper_count"] == 3
    assert (
        lookup(populated, key="conf/icse/One24")["items"][0]["title"]
        == "Graph Learning for Security v2"
    )

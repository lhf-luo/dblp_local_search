import json
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from filelock import FileLock
from lxml import etree

from dblp_local_search.app import create_app
from dblp_local_search.ingestion.parser import records
from dblp_local_search.ingestion.update import update
from dblp_local_search.scheduler import cron_trigger

FIXTURES = Path(__file__).parent / "fixtures"


def test_not_ready(settings):
    client = TestClient(create_app(settings))
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 503
    assert client.post("/v1/papers/search", json={"year_from": 2020}).status_code == 401


def test_failed_build_keeps_current(populated, tmp_path):
    old = (populated.data_dir / "dblp.sqlite").read_bytes()
    broken = tmp_path / "bad.xml"
    broken.write_text("<dblp><article>", encoding="utf-8")
    with pytest.raises((ValueError, etree.XMLSyntaxError)):
        update(populated, xml=broken, dtd=FIXTURES / "dblp.dtd")
    assert (populated.data_dir / "dblp.sqlite").read_bytes() == old
    assert (
        json.loads((populated.data_dir / "update-status.json").read_text())["state"]
        == "failed"
    )


def test_cursor_is_not_rejected_after_database_update(client, populated):
    body = {"query": {"all_of": [{"text": "graph"}]}, "page_size": 1}
    first = client.post("/v1/papers/search", json=body).json()
    update(populated, xml=FIXTURES / "dblp.xml", dtd=FIXTURES / "dblp.dtd")
    following = client.post(
        "/v1/papers/search", json={**body, "cursor": first["next_cursor"]}
    )
    assert following.status_code == 200
    assert "dataset_version" not in following.json()
    assert following.json()["items"][0]["dblp_key"] != first["items"][0]["dblp_key"]
    assert "version" not in client.get("/v1/dataset").json()


def test_lock_prevents_concurrent_update(settings):
    settings.data_dir.mkdir()
    with FileLock(settings.data_dir / "update.lock"):
        assert update(settings)["state"] == "busy"


def test_external_xml_entity_is_blocked(tmp_path):
    xml = tmp_path / "evil.xml"
    xml.write_text(
        '<!DOCTYPE dblp [<!ENTITY steal SYSTEM "file:///etc/passwd">]><dblp><article key="x"><title>&steal;</title></article></dblp>'
    )
    with pytest.raises(ValueError, match="unapproved"):
        tuple(records(xml, FIXTURES / "dblp.dtd"))


def test_sunday_3am_is_sunday_not_monday():
    trigger = cron_trigger("0 3 * * 0", "Asia/Shanghai")
    start = datetime.fromisoformat("2026-11-14T04:00:00+08:00")
    following = trigger.get_next_fire_time(None, start)
    assert following.weekday() == 6 and following.hour == 3
    assert following.isoformat() == "2026-11-15T03:00:00+08:00"

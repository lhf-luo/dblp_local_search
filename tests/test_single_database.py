import os

import pytest
from conftest import FIXTURES

from dblp_local_search.ingestion.update import update
from dblp_local_search.storage.database import active_metadata, database


def test_publish_failure_preserves_old_database(populated, monkeypatch):
    old = active_metadata(populated.data_dir)

    def fail(*args):
        raise PermissionError("Cannot replace active database")

    monkeypatch.setattr("dblp_local_search.ingestion.update.publish", fail)
    with pytest.raises(PermissionError):
        update(
            populated, full=True, xml=FIXTURES / "dblp.xml", dtd=FIXTURES / "dblp.dtd"
        )
    assert active_metadata(populated.data_dir) == old
    assert not (populated.data_dir / "staging").exists()


def test_upstream_metadata_in_same_file(populated):
    assert active_metadata(populated.data_dir)["upstream"] == {"kind": "local-files"}
    assert not (populated.data_dir / "metadata.json").exists()


def test_author_papers_need_only_author_id(client, populated):
    author_page = client.get("/v1/authors/search", params={"name": "Alice"}).json()
    author = author_page["items"][0]
    update(populated, xml=FIXTURES / "dblp.xml", dtd=FIXTURES / "dblp.dtd")
    response = client.get(f"/v1/authors/{author['author_id']}/papers")
    assert response.status_code == 200
    assert response.json()["total"] == 2


@pytest.mark.skipif(os.name != "posix", reason="Linux inode replacement semantics")
def test_open_reader_finishes_on_old_inode(populated):
    with database(populated.data_dir, 30) as reader:
        old_timestamp = reader.execute(
            "SELECT value FROM metadata WHERE key='built_at'"
        ).fetchone()[0]
        update(populated, xml=FIXTURES / "dblp.xml", dtd=FIXTURES / "dblp.dtd")
        assert (
            reader.execute(
                "SELECT value FROM metadata WHERE key='built_at'"
            ).fetchone()[0]
            == old_timestamp
        )
        assert reader.execute("SELECT count(*) FROM papers").fetchone()[0] == 3

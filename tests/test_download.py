from unittest.mock import Mock

import httpx
import pytest

from dblp_local_search.ingestion import update as updater
from dblp_local_search.ingestion.download import fetch


def test_not_modified_skips_build(populated, monkeypatch):
    original = (populated.data_dir / "dblp.sqlite").read_bytes()
    download = Mock(return_value=None)
    monkeypatch.setattr(updater, "fetch", download)
    result = updater.update(populated)
    assert result["state"] == "unchanged"
    assert (populated.data_dir / "dblp.sqlite").read_bytes() == original
    assert download.call_count == 1


def test_fetch_rejects_html_instead_of_gzip(tmp_path, monkeypatch):
    response = httpx.Response(
        200,
        content=b"<html>challenge</html>",
        request=httpx.Request("GET", "https://dblp.org/xml/dblp.xml.gz"),
    )

    class Context:
        def __enter__(self):
            return response

        def __exit__(self, *args):
            response.close()

    monkeypatch.setattr(httpx, "stream", lambda *a, **kw: Context())
    with pytest.raises(ValueError, match="not gzip"):
        fetch("https://dblp.org/xml/dblp.xml.gz", tmp_path / "dblp.xml.gz")


def test_body_limit(client):
    response = client.post(
        "/v1/papers/search",
        content=b"x" * 70000,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413

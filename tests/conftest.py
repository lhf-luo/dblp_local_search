from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dblp_local_search.app import create_app
from dblp_local_search.config import Settings
from dblp_local_search.ingestion.update import update

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path / "data", api_token="test-token")


@pytest.fixture
def populated(settings):
    update(settings, xml=FIXTURES / "dblp.xml", dtd=FIXTURES / "dblp.dtd")
    return settings


@pytest.fixture
def client(populated):
    return TestClient(
        create_app(populated), headers={"Authorization": "Bearer test-token"}
    )

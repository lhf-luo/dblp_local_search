import pytest
from conftest import FIXTURES
from filelock import FileLock

from dblp_local_search.ingestion.update import update


def test_stale_stage_cleaned_before_build(populated, monkeypatch):
    from dblp_local_search.ingestion import update as module

    stage = populated.data_dir / "staging"
    stage.mkdir()
    (stage / "stale.sqlite").write_text("incomplete")
    original = module.build

    def check_build(xml, dtd, target):
        assert target == stage / "dblp.sqlite"
        assert not (stage / "stale.sqlite").exists()
        return original(xml, dtd, target)

    monkeypatch.setattr(module, "build", check_build)
    update(populated, full=True, xml=FIXTURES / "dblp.xml", dtd=FIXTURES / "dblp.dtd")
    assert not stage.exists()


def test_busy_update_does_not_touch_stage(settings):
    stage = settings.data_dir / "staging"
    stage.mkdir(parents=True)
    source = stage / "in-progress"
    source.write_text("keep")
    with FileLock(settings.data_dir / "update.lock"):
        assert update(settings)["state"] == "busy"
    assert source.read_text() == "keep"


def test_local_input_inside_stage_is_not_deleted(settings):
    stage = settings.data_dir / "staging"
    stage.mkdir(parents=True)
    xml = stage / "input.xml"
    xml.write_text("keep")
    with pytest.raises(ValueError, match="outside"):
        update(settings, xml=xml, dtd=FIXTURES / "dblp.dtd")
    assert xml.read_text() == "keep"

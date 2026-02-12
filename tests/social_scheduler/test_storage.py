from pathlib import Path

import pytest

from social_scheduler.core.paths import ensure_directories
from social_scheduler.core.service import SocialSchedulerService
from social_scheduler.core.storage_jsonl import JsonlStore


def test_jsonl_store_append_find_upsert(tmp_path: Path):
    store = JsonlStore(tmp_path / "items.jsonl")
    store.append({"id": "1", "value": "a"})

    row = store.find_one("id", "1")
    assert row is not None
    assert row["value"] == "a"

    store.upsert("id", "1", {"id": "1", "value": "b"})
    row = store.find_one("id", "1")
    assert row is not None
    assert row["value"] == "b"


def test_jsonl_store_compact_reclaims_blank_lines(tmp_path: Path):
    path = tmp_path / "items.jsonl"
    path.write_text('{"id":"1","value":"a"}\n\n\n', encoding="utf-8")
    store = JsonlStore(path)

    reclaimed = store.compact()
    assert reclaimed >= 0
    assert path.read_text(encoding="utf-8").count("\n") == 1


def test_service_compact_data_unknown_store_raises():
    ensure_directories()
    service = SocialSchedulerService()
    with pytest.raises(ValueError):
        service.compact_data("does_not_exist")

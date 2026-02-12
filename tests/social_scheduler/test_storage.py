from pathlib import Path

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

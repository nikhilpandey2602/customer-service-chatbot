import os
import shutil
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from clock import FakeClock
from doc_store import KnowledgeStore, RollbackError


@pytest.fixture
def clock():
    return FakeClock(datetime(2026, 11, 14, 2, 0))


@pytest.fixture
def source(tmp_path):
    folder = tmp_path / "incoming"
    folder.mkdir()
    return folder


@pytest.fixture
def store(tmp_path, clock):
    return KnowledgeStore(str(tmp_path / "kb"), clock=clock)


def write(folder, name, content):
    (folder / name).write_text(content, encoding="utf-8")


def test_first_scan_finds_new_documents_and_candidate_is_not_active(store, source):
    write(source, "refund.txt", "Refunds within 14 days.")
    write(source, "support.txt", "Support 9 to 6.")
    result = store.create_candidate(str(source))
    assert result["version"] == 1
    assert result["report"]["new"] == ["refund.txt", "support.txt"]
    assert store.active_version() is None  # not live until activated
    store.activate(1)
    assert store.read_documents()["refund.txt"] == "Refunds within 14 days."


def test_unchanged_documents_create_no_new_version(store, source):
    write(source, "a.txt", "Alpha")
    store.activate(store.create_candidate(str(source))["version"])
    result = store.create_candidate(str(source))
    assert result["version"] is None
    assert result["report"]["unchanged"] == ["a.txt"]
    assert store.versions() == [1]


def test_only_modified_and_new_documents_are_processed(store, source):
    write(source, "a.txt", "Alpha")
    write(source, "b.txt", "Beta")
    store.activate(store.create_candidate(str(source))["version"])
    write(source, "b.txt", "Beta changed")
    write(source, "c.txt", "Gamma")
    result = store.create_candidate(str(source))
    assert result["report"]["unchanged"] == ["a.txt"]
    assert result["report"]["modified"] == ["b.txt"]
    assert result["report"]["new"] == ["c.txt"]
    store.activate(result["version"])
    docs = store.read_documents()
    assert docs == {"a.txt": "Alpha", "b.txt": "Beta changed", "c.txt": "Gamma"}
    assert store.read_documents(1)["b.txt"] == "Beta"  # old version untouched


def test_duplicates_inside_one_batch_are_skipped(store, source):
    write(source, "a.txt", "Same text")
    write(source, "b.txt", "Same text")
    result = store.create_candidate(str(source))
    assert result["report"]["new"] == ["a.txt"]
    assert result["report"]["duplicates"] == [{"file": "b.txt", "duplicate_of": "a.txt"}]
    store.activate(result["version"])
    assert list(store.read_documents()) == ["a.txt"]


def test_copy_of_existing_content_under_new_name_is_a_duplicate(store, source):
    write(source, "a.txt", "Original")
    store.activate(store.create_candidate(str(source))["version"])
    write(source, "copy_of_a.txt", "Original")
    result = store.create_candidate(str(source))
    assert result["version"] is None
    assert result["report"]["duplicates"] == [{"file": "copy_of_a.txt", "duplicate_of": "a.txt"}]


def test_invalid_files_are_quarantined_and_valid_ones_still_processed(store, source):
    write(source, "good.txt", "Good document")
    write(source, "empty.txt", "")
    write(source, "blank.md", "   \n  ")
    write(source, "virus.exe", "MZ...")
    (source / "binary.txt").write_bytes(b"\xff\xfe\x00bad")
    result = store.create_candidate(str(source))
    reasons = {q["file"]: q["reason"] for q in result["report"]["quarantined"]}
    assert reasons == {
        "binary.txt": "not valid UTF-8 text",
        "blank.md": "file contains only whitespace",
        "empty.txt": "empty file",
        "virus.exe": "unsupported file type",
    }
    assert result["report"]["new"] == ["good.txt"]
    store.activate(result["version"])
    assert list(store.read_documents()) == ["good.txt"]
    kept = os.listdir(store.quarantine_dir)
    assert any(name.endswith("virus.exe") for name in kept) and "log.json" in kept


def test_oversized_file_is_quarantined(tmp_path, clock, source):
    small = KnowledgeStore(str(tmp_path / "kb2"), clock=clock, max_bytes=10)
    write(source, "big.txt", "x" * 50)
    result = small.create_candidate(str(source))
    assert result["version"] is None
    assert result["report"]["quarantined"][0]["reason"] == "file too large"


def test_same_bad_file_is_not_quarantined_twice(store, source):
    write(source, "empty.txt", "")
    store.scan(str(source))
    store.scan(str(source))
    copies = [n for n in os.listdir(store.quarantine_dir) if n != "log.json"]
    assert len(copies) == 1


def test_rollback_returns_to_previous_version(store, source):
    write(source, "a.txt", "Version one")
    store.activate(store.create_candidate(str(source))["version"])
    write(source, "a.txt", "Version two")
    store.activate(store.create_candidate(str(source))["version"])
    assert store.read_documents()["a.txt"] == "Version two"
    assert store.rollback() == 1
    assert store.active_version() == 1
    assert store.read_documents()["a.txt"] == "Version one"
    assert store.versions() == [1, 2]  # nothing deleted


def test_rollback_without_history_raises(store, source):
    with pytest.raises(RollbackError):
        store.rollback()
    write(source, "a.txt", "Only version")
    store.activate(store.create_candidate(str(source))["version"])
    with pytest.raises(RollbackError):
        store.rollback()


def test_failed_update_leaves_no_partial_version_and_keeps_active(store, source, monkeypatch):
    write(source, "a.txt", "Alpha")
    store.activate(store.create_candidate(str(source))["version"])
    write(source, "b.txt", "Beta")

    real_copy = shutil.copy2

    def failing_copy(src, dst, *args, **kwargs):
        if os.path.basename(src) == "b.txt":
            raise OSError("disk full")
        return real_copy(src, dst, *args, **kwargs)

    monkeypatch.setattr("doc_store.shutil.copy2", failing_copy)
    with pytest.raises(OSError):
        store.create_candidate(str(source))
    assert store.versions() == [1]
    assert store.active_version() == 1
    assert not [n for n in os.listdir(store.versions_dir) if n.startswith(".tmp")]


def test_state_survives_restart_and_manifest_uses_the_clock(tmp_path, clock, source):
    root = str(tmp_path / "kb3")
    first = KnowledgeStore(root, clock=clock)
    write(source, "a.txt", "Alpha")
    version = first.create_candidate(str(source))["version"]
    first.activate(version)
    second = KnowledgeStore(root, clock=clock)
    assert second.active_version() == 1
    assert second.manifest(1)["created_at"] == "2026-11-14T02:00:00"


def test_activating_unknown_version_is_rejected(store):
    with pytest.raises(ValueError):
        store.activate(99)
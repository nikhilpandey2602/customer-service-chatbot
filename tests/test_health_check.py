import copy
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from clock import FakeClock
from config import load_config
from doc_store import KnowledgeStore
from health_check import HealthChecker, active_documents_readable, active_quality_ok
from quality_gate import KeywordEvaluator
from update_pipeline import UpdatePipeline


class FakeGate:
    def review(self, store, version):
        return {"approved": True, "reasons": []}


# ---------- the checker itself ----------
def test_all_checks_passing_is_healthy():
    result = HealthChecker({"a": lambda: True, "b": lambda: True}).run()
    assert result == {"healthy": True, "failures": []}


def test_a_failing_or_crashing_check_is_unhealthy():
    def crash():
        raise ConnectionError("service down")

    result = HealthChecker({"ok": lambda: True, "bad": lambda: False, "crash": crash}).run()
    assert result["healthy"] is False
    assert result["failures"] == ["bad: check failed", "crash: service down"]


def test_documents_readable_check(tmp_path):
    clock = FakeClock(datetime(2026, 11, 22, 2, 0))
    store = KnowledgeStore(str(tmp_path / "kb"), clock=clock)
    source = tmp_path / "in"
    source.mkdir()
    (source / "a.txt").write_text("Alpha", encoding="utf-8")
    store.activate(store.create_candidate(str(source))["version"])
    assert HealthChecker({"docs": active_documents_readable(store)}).run()["healthy"] is True

    os.remove(os.path.join(store.versions_dir, "v0001", "a.txt"))  # simulate a damaged live version
    assert HealthChecker({"docs": active_documents_readable(store)}).run()["healthy"] is False


def test_quality_check_notices_a_degraded_live_version(tmp_path):
    questions = [{"question": "How many days for a refund?", "expected_keywords": ["14 days"], "source": "refund.txt"}]
    clock = FakeClock(datetime(2026, 11, 22, 2, 0))
    store = KnowledgeStore(str(tmp_path / "kb"), clock=clock)
    source = tmp_path / "in"
    source.mkdir()
    (source / "refund.txt").write_text("Refunds are available within 30 days.", encoding="utf-8")
    store.activate(store.create_candidate(str(source))["version"])
    check = active_quality_ok(store, KeywordEvaluator(questions))
    assert HealthChecker({"quality": check}).run()["healthy"] is False


# ---------- the pipeline with health checks ----------
@pytest.fixture
def env(tmp_path):
    source = tmp_path / "incoming"
    source.mkdir()
    (source / "a.txt").write_text("Version one", encoding="utf-8")
    clock = FakeClock(datetime(2026, 11, 21, 2, 0))
    store = KnowledgeStore(str(tmp_path / "kb"), clock=clock)
    health = {"ok": True}

    def check():
        if isinstance(health["ok"], Exception):
            raise health["ok"]
        return health["ok"]

    cfg = copy.deepcopy(load_config(None))
    pipeline = UpdatePipeline(store, FakeGate(), str(source), cfg, clock,
                              health_checker=HealthChecker({"site": check}))
    return {"source": source, "clock": clock, "store": store, "health": health, "pipeline": pipeline}


def go_live_with_two_versions(env):
    """Version 1 goes live healthy and confirmed, then version 2 goes live and is being watched."""
    pipeline, clock, source = env["pipeline"], env["clock"], env["source"]
    pipeline.tick()  # 02:00 -> v1 live
    clock.set(datetime(2026, 11, 21, 2, 10))
    pipeline.tick()  # watch window over -> confirmed
    assert pipeline.state()["last_activation"]["health"] == "confirmed"

    (source / "a.txt").write_text("Version two", encoding="utf-8")
    clock.set(datetime(2026, 11, 22, 2, 0))
    assert pipeline.tick()[0]["status"] == "activated"  # v2 live, being watched
    assert env["store"].active_version() == 2


def test_healthy_update_is_confirmed_after_the_window(env):
    go_live_with_two_versions(env)
    env["clock"].set(datetime(2026, 11, 22, 2, 5))
    assert env["pipeline"].tick() == [{"status": "health_confirmed", "version": 2}]
    assert env["store"].active_version() == 2


def test_failure_within_five_minutes_rolls_back_automatically(env):
    go_live_with_two_versions(env)
    env["health"]["ok"] = False
    env["clock"].set(datetime(2026, 11, 22, 2, 2))
    result = env["pipeline"].tick()[0]
    assert result == {"status": "rolled_back", "version": 1, "failed_version": 2}
    assert env["store"].active_version() == 1
    assert env["store"].read_documents()["a.txt"] == "Version one"
    state = env["pipeline"].state()
    assert state["last_activation"]["health"] == "rolled_back"
    names = [e["event"] for e in state["events"]]
    assert "health_check_failed" in names and "auto_rollback" in names


def test_failure_exactly_at_five_minutes_still_rolls_back(env):
    go_live_with_two_versions(env)
    env["health"]["ok"] = False
    env["clock"].set(datetime(2026, 11, 22, 2, 5))
    assert env["pipeline"].tick()[0]["status"] == "rolled_back"


def test_failure_after_the_window_raises_an_alert_but_does_not_roll_back(env):
    go_live_with_two_versions(env)
    env["health"]["ok"] = False
    env["clock"].set(datetime(2026, 11, 22, 2, 6))
    assert env["pipeline"].tick()[0]["status"] == "unhealthy_after_window"
    assert env["store"].active_version() == 2


def test_a_crashing_health_check_counts_as_a_failure(env):
    go_live_with_two_versions(env)
    env["health"]["ok"] = ConnectionError("service outage")
    env["clock"].set(datetime(2026, 11, 22, 2, 1))
    assert env["pipeline"].tick()[0]["status"] == "rolled_back"


def test_rolled_back_content_is_not_activated_again(env):
    go_live_with_two_versions(env)
    env["health"]["ok"] = False
    env["clock"].set(datetime(2026, 11, 22, 2, 2))
    env["pipeline"].tick()  # rolled back to v1

    env["health"]["ok"] = True
    env["clock"].set(datetime(2026, 11, 23, 2, 0))  # next day: same bad documents are still in the folder
    assert env["pipeline"].tick()[0]["status"] == "blocked_after_rollback"
    assert env["store"].active_version() == 1


def test_fixed_content_after_a_rollback_is_accepted(env):
    go_live_with_two_versions(env)
    env["health"]["ok"] = False
    env["clock"].set(datetime(2026, 11, 22, 2, 2))
    env["pipeline"].tick()

    env["health"]["ok"] = True
    (env["source"] / "a.txt").write_text("Version three, fixed", encoding="utf-8")
    env["clock"].set(datetime(2026, 11, 23, 2, 0))
    assert env["pipeline"].tick()[0]["status"] == "activated"
    assert env["store"].read_documents()["a.txt"] == "Version three, fixed"


def test_first_ever_version_cannot_be_rolled_back(env):
    env["health"]["ok"] = False
    result = env["pipeline"].tick()
    assert [r["status"] for r in result] == ["activated", "rollback_failed"]
    assert env["store"].active_version() == 1  # nothing earlier to return to


def test_without_a_health_checker_nothing_is_watched(tmp_path):
    source = tmp_path / "in"
    source.mkdir()
    (source / "a.txt").write_text("Alpha", encoding="utf-8")
    clock = FakeClock(datetime(2026, 11, 21, 2, 0))
    store = KnowledgeStore(str(tmp_path / "kb"), clock=clock)
    pipeline = UpdatePipeline(store, FakeGate(), str(source), copy.deepcopy(load_config(None)), clock)
    pipeline.tick()
    assert pipeline.state()["last_activation"]["health"] == "not_monitored"
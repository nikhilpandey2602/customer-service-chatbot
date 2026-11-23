import copy
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from clock import FakeClock
from config import load_config
from doc_store import KnowledgeStore
from update_pipeline import UpdatePipeline


class FakeGate:
    def __init__(self, approved=True):
        self.approved = approved
        self.calls = 0

    def review(self, store, version):
        self.calls += 1
        return {"approved": self.approved, "reasons": [] if self.approved else ["accuracy dropped"]}


@pytest.fixture
def setup(tmp_path):
    source = tmp_path / "incoming"
    source.mkdir()
    (source / "a.txt").write_text("Alpha document", encoding="utf-8")
    clock = FakeClock(datetime(2026, 11, 21, 1, 59))
    store = KnowledgeStore(str(tmp_path / "kb"), clock=clock)
    return {"source": source, "clock": clock, "store": store}


def make_pipeline(setup, gate=None, schedule="02:00", window=("01:00", "04:00")):
    cfg = copy.deepcopy(load_config(None))
    cfg["update"]["schedule_time"] = schedule
    cfg["maintenance_window"] = {"start": window[0], "end": window[1]}
    return UpdatePipeline(setup["store"], gate or FakeGate(), str(setup["source"]), cfg, setup["clock"])


def make_flaky(store, monkeypatch, fail):
    real = store.create_candidate

    def flaky(source_dir):
        if fail["on"]:
            raise OSError("service outage")
        return real(source_dir)

    monkeypatch.setattr(store, "create_candidate", flaky)


def event_names(pipeline):
    return [e["event"] for e in pipeline.state()["events"]]


def test_nothing_happens_before_the_scheduled_time_then_it_runs_once_a_day(setup):
    pipeline = make_pipeline(setup)
    assert pipeline.tick() == []  # 01:59
    setup["clock"].set(datetime(2026, 11, 21, 2, 0))
    assert pipeline.tick()[0]["status"] == "activated"
    setup["clock"].set(datetime(2026, 11, 21, 2, 30))
    assert pipeline.tick() == []  # already ran today
    setup["clock"].set(datetime(2026, 11, 22, 2, 0))
    assert pipeline.tick()[0]["status"] == "no_changes"  # next day, nothing new


def test_approved_update_goes_live_inside_the_window(setup):
    pipeline = make_pipeline(setup)
    setup["clock"].set(datetime(2026, 11, 21, 2, 0))
    pipeline.tick()
    assert setup["store"].active_version() == 1
    assert pipeline.state()["last_activation"]["previous"] is None


def test_approved_update_waits_for_the_maintenance_window(setup):
    pipeline = make_pipeline(setup, schedule="12:00")
    setup["clock"].set(datetime(2026, 11, 21, 12, 0))
    assert pipeline.tick()[0]["status"] == "waiting_for_window"
    assert setup["store"].active_version() is None
    assert pipeline.state()["pending_version"] == 1

    setup["clock"].set(datetime(2026, 11, 21, 23, 0))
    assert pipeline.tick() == []  # still outside the window
    assert setup["store"].active_version() is None

    setup["clock"].set(datetime(2026, 11, 22, 1, 0))
    assert pipeline.tick()[0]["status"] == "activated"
    assert setup["store"].active_version() == 1
    assert pipeline.state()["pending_version"] is None


def test_window_that_crosses_midnight(setup):
    pipeline = make_pipeline(setup, schedule="12:00", window=("23:00", "02:00"))
    setup["clock"].set(datetime(2026, 11, 21, 12, 0))
    pipeline.tick()
    setup["clock"].set(datetime(2026, 11, 21, 22, 59))
    assert pipeline.tick() == []
    setup["clock"].set(datetime(2026, 11, 21, 23, 30))
    assert pipeline.tick()[0]["status"] == "activated"


def test_rejected_update_is_never_activated_and_not_retried(setup):
    gate = FakeGate(approved=False)
    pipeline = make_pipeline(setup, gate=gate)
    setup["clock"].set(datetime(2026, 11, 21, 2, 0))
    result = pipeline.tick()[0]
    assert result["status"] == "rejected" and result["reasons"] == ["accuracy dropped"]
    assert setup["store"].active_version() is None
    assert pipeline.state()["pending_version"] is None
    assert pipeline.state()["next_retry_at"] is None
    assert "update_rejected" in event_names(pipeline)


def test_failed_update_retries_after_15_30_and_60_minutes_then_gives_up(setup, monkeypatch):
    fail = {"on": True}
    make_flaky(setup["store"], monkeypatch, fail)
    pipeline = make_pipeline(setup)
    clock = setup["clock"]

    clock.set(datetime(2026, 11, 21, 2, 0))
    assert pipeline.tick()[0]["status"] == "failed_retry_scheduled"
    assert pipeline.state()["next_retry_at"] == "2026-11-21T02:15:00"

    clock.set(datetime(2026, 11, 21, 2, 14))
    assert pipeline.tick() == []  # not due yet
    clock.set(datetime(2026, 11, 21, 2, 15))
    assert pipeline.tick()[0]["status"] == "failed_retry_scheduled"
    assert pipeline.state()["next_retry_at"] == "2026-11-21T02:45:00"

    clock.set(datetime(2026, 11, 21, 2, 45))
    assert pipeline.tick()[0]["status"] == "failed_retry_scheduled"
    assert pipeline.state()["next_retry_at"] == "2026-11-21T03:45:00"

    clock.set(datetime(2026, 11, 21, 3, 45))
    assert pipeline.tick()[0]["status"] == "failed_giving_up"
    assert pipeline.state()["next_retry_at"] is None
    assert event_names(pipeline).count("update_failed") == 4
    assert "gave_up" in event_names(pipeline)

    clock.set(datetime(2026, 11, 21, 4, 30))
    assert pipeline.tick() == []  # no more attempts today

    fail["on"] = False  # the outage is over
    clock.set(datetime(2026, 11, 22, 2, 0))
    assert pipeline.tick()[0]["status"] == "activated"  # next day it tries again
    assert setup["store"].active_version() == 1


def test_a_successful_retry_resets_the_counters(setup, monkeypatch):
    fail = {"on": True}
    make_flaky(setup["store"], monkeypatch, fail)
    pipeline = make_pipeline(setup)
    clock = setup["clock"]
    clock.set(datetime(2026, 11, 21, 2, 0))
    pipeline.tick()
    fail["on"] = False
    clock.set(datetime(2026, 11, 21, 2, 15))
    assert pipeline.tick()[0]["status"] == "activated"
    state = pipeline.state()
    assert state["attempts"] == 0 and state["next_retry_at"] is None


def test_retry_success_outside_the_window_still_waits(setup, monkeypatch):
    fail = {"on": True}
    make_flaky(setup["store"], monkeypatch, fail)
    pipeline = make_pipeline(setup, window=("01:00", "03:00"))
    clock = setup["clock"]
    clock.set(datetime(2026, 11, 21, 2, 0))
    pipeline.tick()
    fail["on"] = False
    clock.set(datetime(2026, 11, 21, 3, 30))  # retry is overdue and the window has closed
    assert pipeline.tick()[0]["status"] == "waiting_for_window"
    assert setup["store"].active_version() is None


def test_state_survives_a_restart(setup, monkeypatch):
    fail = {"on": True}
    make_flaky(setup["store"], monkeypatch, fail)
    first = make_pipeline(setup)
    setup["clock"].set(datetime(2026, 11, 21, 2, 0))
    first.tick()

    restarted = make_pipeline(setup)  # a new object, as after a crash
    assert restarted.state()["next_retry_at"] == "2026-11-21T02:15:00"
    fail["on"] = False
    setup["clock"].set(datetime(2026, 11, 21, 2, 15))
    assert restarted.tick()[0]["status"] == "activated"


def test_events_are_recorded_for_monitoring(setup):
    pipeline = make_pipeline(setup)
    setup["clock"].set(datetime(2026, 11, 21, 2, 0))
    pipeline.tick()
    assert event_names(pipeline) == ["update_approved", "activated"]
import os
from datetime import datetime, timedelta

from clock import in_time_window
from config import parse_hhmm
from doc_store import _read_json, _write_json

DEFAULT_STATE = {
    "last_run_date": None,
    "attempts": 0,
    "next_retry_at": None,
    "pending_version": None,
    "last_activation": None,
    "events": [],
}


class UpdatePipeline:
    """Runs knowledge-base updates on a schedule.

    - one scheduled run per day, at the configured time
    - a failed run is retried after each delay in retry_delays_minutes, then given up
    - an approved version goes live only inside the maintenance window
    Call tick() regularly (for example every minute). All time comes from the clock.
    """

    def __init__(self, store, gate, source_dir, config, clock, logger=None):
        self.store = store
        self.gate = gate
        self.source_dir = source_dir
        self.clock = clock
        self.logger = logger
        self.schedule_time = parse_hhmm(config["update"]["schedule_time"])
        self.retry_delays = list(config["update"]["retry_delays_minutes"])
        self.window_start = parse_hhmm(config["maintenance_window"]["start"])
        self.window_end = parse_hhmm(config["maintenance_window"]["end"])
        self.state_path = os.path.join(store.root, "pipeline_state.json")

    # ---------- state ----------
    def state(self):
        saved = _read_json(self.state_path, {})
        state = {**DEFAULT_STATE, **saved}
        state["events"] = list(state["events"])
        return state

    def _save(self, state):
        _write_json(self.state_path, state)

    def _event(self, state, name, detail=""):
        state["events"].append({"time": self.clock.now().isoformat(), "event": name, "detail": detail})
        state["events"] = state["events"][-200:]
        if self.logger:
            self.logger.info(f"{name}: {detail}")

    def _in_window(self):
        return in_time_window(self.clock.now().time(), self.window_start, self.window_end)

    # ---------- actions ----------
    def _activate(self, state, version, event):
        previous = self.store.active_version()
        self.store.activate(version)
        state["pending_version"] = None
        state["last_activation"] = {
            "version": version,
            "previous": previous,
            "at": self.clock.now().isoformat(),
        }
        self._event(state, event, f"version {version} is now live")

    def _handle_failure(self, state, error):
        attempts = state["attempts"]
        self._event(state, "update_failed", str(error))
        if attempts < len(self.retry_delays):
            delay = self.retry_delays[attempts]
            state["attempts"] = attempts + 1
            state["next_retry_at"] = (self.clock.now() + timedelta(minutes=delay)).isoformat()
            self._event(state, "retry_scheduled", f"in {delay} minutes")
            status = "failed_retry_scheduled"
        else:
            state["attempts"] = 0
            state["next_retry_at"] = None
            self._event(state, "gave_up", "all retries used; next scheduled run will try again")
            status = "failed_giving_up"
        self._save(state)
        return {"status": status}

    def run_update(self, trigger="manual"):
        state = self.state()
        if trigger == "scheduled":
            state["last_run_date"] = self.clock.now().date().isoformat()
        try:
            created = self.store.create_candidate(self.source_dir)
            version = created["version"]
            decision = self.gate.review(self.store, version) if version is not None else None
        except Exception as error:
            return self._handle_failure(state, error)

        state["attempts"] = 0
        state["next_retry_at"] = None
        if version is None:
            self._event(state, "no_changes", "no new or modified documents")
            self._save(state)
            return {"status": "no_changes"}
        if not decision["approved"]:
            self._event(state, "update_rejected", "; ".join(decision["reasons"]))
            self._save(state)
            return {"status": "rejected", "reasons": decision["reasons"], "version": version}

        state["pending_version"] = version
        self._event(state, "update_approved", f"version {version} passed the quality gate")
        if self._in_window():
            self._activate(state, version, "activated")
            status = "activated"
        else:
            self._event(state, "waiting_for_window", f"version {version} will go live in the maintenance window")
            status = "waiting_for_window"
        self._save(state)
        return {"status": status, "version": version}

    def tick(self):
        """Do whatever is due right now. Returns a list of results (empty if nothing was due)."""
        results = []
        now = self.clock.now()
        state = self.state()

        if state["pending_version"] is not None and self._in_window():
            self._activate(state, state["pending_version"], "activated_after_wait")
            self._save(state)
            results.append({"status": "activated", "version": state["last_activation"]["version"]})
            state = self.state()

        retry_at = state["next_retry_at"]
        if retry_at:
            if now >= datetime.fromisoformat(retry_at):
                results.append(self.run_update("retry"))
        elif state["last_run_date"] != now.date().isoformat() and now.time() >= self.schedule_time:
            results.append(self.run_update("scheduled"))
        return results
import hashlib
import json
import os
import shutil

from clock import SystemClock

DEFAULT_EXTENSIONS = (".txt", ".md", ".csv")
DEFAULT_MAX_BYTES = 5 * 1024 * 1024


class RollbackError(Exception):
    pass


def sha256_of(data):
    return hashlib.sha256(data).hexdigest()


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def _read_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class KnowledgeStore:
    """Versioned storage for knowledge-base documents.

    root/versions/v0001/   a full snapshot of the accepted documents plus manifest.json
    root/quarantine/       invalid files (copied here) plus log.json with the reasons
    root/state.json        which version is active, and the activation history
    """

    def __init__(self, root, clock=None, allowed_extensions=DEFAULT_EXTENSIONS,
                 max_bytes=DEFAULT_MAX_BYTES, logger=None):
        self.root = root
        self.clock = clock or SystemClock()
        self.allowed_extensions = tuple(e.lower() for e in allowed_extensions)
        self.max_bytes = max_bytes
        self.logger = logger
        self.versions_dir = os.path.join(root, "versions")
        self.quarantine_dir = os.path.join(root, "quarantine")
        self.state_path = os.path.join(root, "state.json")
        for folder in (self.versions_dir, self.quarantine_dir):
            os.makedirs(folder, exist_ok=True)

    # ---------- helpers ----------
    def _log(self, message):
        if self.logger:
            self.logger.info(message)

    def _version_dir(self, number):
        return os.path.join(self.versions_dir, f"v{number:04d}")

    def _state(self):
        return _read_json(self.state_path, {"active": None, "history": []})

    def versions(self):
        numbers = []
        for name in os.listdir(self.versions_dir):
            if name.startswith("v") and name[1:].isdigit():
                numbers.append(int(name[1:]))
        return sorted(numbers)

    def active_version(self):
        return self._state()["active"]

    def manifest(self, version):
        return _read_json(os.path.join(self._version_dir(version), "manifest.json"), None)

    def read_documents(self, version=None):
        version = self.active_version() if version is None else version
        if version is None:
            return {}
        folder = self._version_dir(version)
        docs = {}
        for name in self.manifest(version)["files"]:
            with open(os.path.join(folder, name), encoding="utf-8") as f:
                docs[name] = f.read()
        return docs

    # ---------- validation ----------
    def _validate(self, name, data):
        """Return None if the file is valid, otherwise the reason it is not."""
        if os.path.splitext(name)[1].lower() not in self.allowed_extensions:
            return "unsupported file type"
        if len(data) == 0:
            return "empty file"
        if len(data) > self.max_bytes:
            return "file too large"
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return "not valid UTF-8 text"
        if not text.strip():
            return "file contains only whitespace"
        return None

    def _quarantine(self, source_path, name, digest, reason):
        log_path = os.path.join(self.quarantine_dir, "log.json")
        log = _read_json(log_path, [])
        if any(e["file"] == name and e["sha256"] == digest and e["reason"] == reason for e in log):
            return  # already quarantined; do not pile up copies on every scan
        stamp = self.clock.now().strftime("%Y%m%dT%H%M%S")
        shutil.copy2(source_path, os.path.join(self.quarantine_dir, f"{stamp}_{name}"))
        log.append({"file": name, "sha256": digest, "reason": reason, "time": self.clock.now().isoformat()})
        _write_json(log_path, log)
        self._log(f"Quarantined {name}: {reason}")

    # ---------- scan ----------
    def scan(self, source_dir):
        """Compare the source folder with the active version. Nothing is changed except quarantine."""
        active = self.active_version()
        known = self.manifest(active)["files"] if active else {}
        seen = {info["sha256"]: name for name, info in known.items()}

        report = {"new": [], "modified": [], "unchanged": [], "duplicates": [], "quarantined": []}
        for name in sorted(os.listdir(source_dir)):
            path = os.path.join(source_dir, name)
            if not os.path.isfile(path):
                continue
            with open(path, "rb") as f:
                data = f.read()
            digest = sha256_of(data)

            reason = self._validate(name, data)
            if reason:
                self._quarantine(path, name, digest, reason)
                report["quarantined"].append({"file": name, "reason": reason})
                continue

            if name in known and known[name]["sha256"] == digest:
                report["unchanged"].append(name)
            elif digest in seen:
                report["duplicates"].append({"file": name, "duplicate_of": seen[digest]})
            else:
                if name in known:
                    seen.pop(known[name]["sha256"], None)
                    report["modified"].append(name)
                else:
                    report["new"].append(name)
                seen[digest] = name
        return report

    # ---------- versions ----------
    def create_candidate(self, source_dir):
        """Build a new version from new and modified documents. It is NOT active yet."""
        report = self.scan(source_dir)
        changed = report["new"] + report["modified"]
        if not changed:
            return {"version": None, "report": report}

        active = self.active_version()
        existing = self.versions()
        number = (existing[-1] if existing else 0) + 1
        final_dir = self._version_dir(number)
        tmp_dir = os.path.join(self.versions_dir, f".tmp_v{number:04d}")
        try:
            os.makedirs(tmp_dir)
            files = {}
            if active:
                for name, info in self.manifest(active)["files"].items():
                    shutil.copy2(os.path.join(self._version_dir(active), name), os.path.join(tmp_dir, name))
                    files[name] = info
            for name in changed:
                shutil.copy2(os.path.join(source_dir, name), os.path.join(tmp_dir, name))
                with open(os.path.join(tmp_dir, name), "rb") as f:
                    data = f.read()
                files[name] = {"sha256": sha256_of(data), "bytes": len(data)}
            _write_json(os.path.join(tmp_dir, "manifest.json"), {
                "version": number,
                "parent": active,
                "created_at": self.clock.now().isoformat(),
                "files": files,
            })
            os.rename(tmp_dir, final_dir)  # the version only appears once it is complete
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise
        self._log(f"Created candidate version {number} with {len(changed)} changed documents")
        return {"version": number, "report": report}

    def activate(self, version):
        if version not in self.versions():
            raise ValueError(f"Version {version} does not exist")
        state = self._state()
        if state["active"] == version:
            return
        state["active"] = version
        state["history"].append(version)
        _write_json(self.state_path, state)
        self._log(f"Activated version {version}")

    def rollback(self):
        """Return to the version that was active before the current one."""
        state = self._state()
        if len(state["history"]) < 2:
            raise RollbackError("There is no earlier version to roll back to")
        state["history"].pop()
        state["active"] = state["history"][-1]
        _write_json(self.state_path, state)
        self._log(f"Rolled back to version {state['active']}")
        return state["active"]
class HealthChecker:
    """Runs named health checks. A check passes when it returns True and fails when it
    returns False or raises an error (an error is never treated as healthy)."""

    def __init__(self, checks):
        self.checks = dict(checks)

    def run(self):
        failures = []
        for name, check in self.checks.items():
            try:
                ok = bool(check())
            except Exception as error:
                failures.append(f"{name}: {error}")
                continue
            if not ok:
                failures.append(f"{name}: check failed")
        return {"healthy": not failures, "failures": failures}


def active_documents_readable(store):
    """Check: the live version exists and all of its documents can be read."""

    def check():
        return bool(store.read_documents())

    return check


def active_quality_ok(store, evaluator, min_accuracy=0.80, min_grounding=0.90):
    """Check: the live version still scores above the minimums on the quality questions."""

    def check():
        scores = evaluator(store.read_documents())
        return scores["accuracy"] >= min_accuracy and scores["grounding"] >= min_grounding

    return check
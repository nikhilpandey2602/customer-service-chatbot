import csv
import os
from datetime import date

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLICY_PATH = os.path.join(PROJECT_DIR, "dataset", "policies.csv")

# Higher number = more restricted. A user can see documents at or below their level.
ACCESS_LEVELS = {"public": 0, "internal": 1}


def _parse_date(value):
    value = (value or "").strip()
    return date.fromisoformat(value) if value else None


def load_policies(path=POLICY_PATH):
    policies = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            row["version"] = int(row["version"])
            row["effective_date"] = _parse_date(row["effective_date"])
            row["expiry_date"] = _parse_date(row["expiry_date"])
            policies.append(row)
    return policies


def is_active_on(doc, on_date):
    """True if the policy was in force on on_date (future and expired are False)."""
    if doc["effective_date"] and on_date < doc["effective_date"]:
        return False
    if doc["expiry_date"] and on_date > doc["expiry_date"]:
        return False
    return True


def is_allowed(doc, user_level):
    """A document with an unknown access level is treated as the most restricted."""
    doc_level = ACCESS_LEVELS.get(doc["access_level"], 99)
    return doc_level <= ACCESS_LEVELS.get(user_level, 0)


def select_policies(policies, on_date, user_level="public", region=None, product=None):
    """Pick the policies that apply. Rules only, no AI involved.

    on_date is a parameter (not today's date inside the function) so that
    current questions, historical questions and simulated dates can be tested.
    """
    pool = [
        d
        for d in policies
        if is_allowed(d, user_level)
        and is_active_on(d, on_date)
        and (product is None or d["product"] == product)
    ]

    by_title = {}
    for d in pool:
        by_title.setdefault(d["title"], []).append(d)

    selected, needs_region = [], []
    for title, docs in by_title.items():
        if region:
            exact = [d for d in docs if d["region"] == region]
            general = [d for d in docs if d["region"] == "ALL"]
            docs = exact or general
            if not docs:
                continue
        else:
            regions = {d["region"] for d in docs}
            specific = regions - {"ALL"}
            if len(specific) > 1 and "ALL" not in regions:
                needs_region.append({"title": title, "regions": sorted(specific)})
                continue
        best = max(docs, key=lambda d: (d["version"], d["effective_date"]))
        selected.append(best)

    return {"selected": selected, "needs_region": needs_region}
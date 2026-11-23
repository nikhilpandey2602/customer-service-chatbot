import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from clock import FakeClock
from config import load_config
from doc_store import KnowledgeStore
from quality_gate import KeywordEvaluator, QualityGate

QUESTIONS = [
    {"question": "How many days for a refund?", "expected_keywords": ["14 days"], "source": "refund.txt"},
    {"question": "When is support open?", "expected_keywords": ["9 AM", "6 PM"], "source": "support.txt"},
    {"question": "How long until certificates are issued?", "expected_keywords": ["10 working days"], "source": "certificate.txt"},
    {"question": "When are instructors paid?", "expected_keywords": ["5th"], "source": "payout.txt"},
    {"question": "How to contact the support desk helpline?", "expected_keywords": ["helpline"], "source": "contact.txt"},
]

GOOD = {
    "refund.txt": "Refund policy: refunds are available within 14 days of purchase.",
    "support.txt": "Support hours: support is open 9 AM to 6 PM on weekdays.",
    "certificate.txt": "Certificates are issued within 10 working days after course completion.",
    "payout.txt": "Instructor payout: instructors are paid on the 5th of every month.",
    "contact.txt": "Contact: reach the support desk or call the helpline.",
}


@pytest.fixture
def evaluator():
    return KeywordEvaluator(QUESTIONS)


@pytest.fixture
def gate(evaluator):
    return QualityGate(evaluator, min_accuracy=0.7, min_grounding=0.7)


def test_good_documents_score_perfectly(evaluator):
    assert evaluator(GOOD) == {"accuracy": 1.0, "grounding": 1.0}


def test_a_changed_fact_lowers_accuracy_but_not_grounding(evaluator):
    bad = dict(GOOD, **{"refund.txt": "Refund policy: refunds are available within 30 days of purchase."})
    scores = evaluator(bad)
    assert scores["accuracy"] == pytest.approx(0.8)
    assert scores["grounding"] == 1.0


def test_a_missing_source_document_lowers_grounding(evaluator):
    missing = {k: v for k, v in GOOD.items() if k != "payout.txt"}
    scores = evaluator(missing)
    assert scores["grounding"] == pytest.approx(0.8)
    assert scores["accuracy"] == pytest.approx(0.8)


def test_gate_approves_an_equal_candidate(gate):
    result = gate.check(GOOD, baseline_docs=dict(GOOD))
    assert result["approved"] is True and result["reasons"] == []


def test_gate_rejects_a_drop_in_accuracy_even_above_the_minimum(gate):
    worse = dict(GOOD, **{"refund.txt": "Refund policy: refunds are available within 30 days of purchase."})
    result = gate.check(worse, baseline_docs=GOOD)  # 0.80 accuracy is above the 0.70 minimum
    assert result["approved"] is False
    assert any("accuracy dropped from 1.00 to 0.80" in r for r in result["reasons"])


def test_gate_rejects_a_drop_in_grounding(gate):
    worse = {k: v for k, v in GOOD.items() if k != "payout.txt"}
    result = gate.check(worse, baseline_docs=GOOD)
    assert result["approved"] is False
    assert any("grounding dropped" in r for r in result["reasons"])


def test_first_version_must_still_meet_the_minimums(evaluator):
    strict = QualityGate(evaluator, min_accuracy=0.9, min_grounding=0.9)
    bad = dict(GOOD, **{"refund.txt": "Refund policy: refunds are available within 30 days of purchase."})
    result = strict.check(bad)  # no active version yet
    assert result["approved"] is False
    assert any("below the minimum" in r for r in result["reasons"])


def test_gate_approves_an_improvement(gate):
    baseline = dict(GOOD, **{"refund.txt": "Refund policy: refunds are available within 30 days of purchase."})
    result = gate.check(GOOD, baseline_docs=baseline)
    assert result["approved"] is True


def test_a_failing_evaluation_rejects_the_update():
    def broken(docs):
        raise RuntimeError("model is down")

    result = QualityGate(broken).check(GOOD, baseline_docs=GOOD)
    assert result["approved"] is False
    assert result["reasons"] == ["evaluation failed: model is down"]


def test_evaluator_needs_valid_questions():
    with pytest.raises(ValueError):
        KeywordEvaluator([])
    with pytest.raises(ValueError):
        KeywordEvaluator([{"question": "Q?", "expected_keywords": [], "source": "a.txt"}])


def test_gate_uses_thresholds_from_the_config(evaluator):
    gate = QualityGate.from_config(load_config(), evaluator)
    assert gate.min_accuracy == 0.80 and gate.min_grounding == 0.90


def test_review_compares_a_stored_candidate_with_the_active_version(tmp_path, evaluator):
    store = KnowledgeStore(str(tmp_path / "kb"), clock=FakeClock(datetime(2026, 11, 21, 2, 0)))
    source = tmp_path / "incoming"
    source.mkdir()
    for name, text in GOOD.items():
        (source / name).write_text(text, encoding="utf-8")
    store.activate(store.create_candidate(str(source))["version"])

    (source / "refund.txt").write_text("Refund policy: refunds are available within 30 days.", encoding="utf-8")
    candidate = store.create_candidate(str(source))["version"]

    gate = QualityGate(evaluator, min_accuracy=0.7, min_grounding=0.7)
    result = gate.review(store, candidate)
    assert result["approved"] is False
    assert store.active_version() == 1  # reviewing never changes what is live
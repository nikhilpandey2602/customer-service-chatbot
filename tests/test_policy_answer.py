import os
import sys
from datetime import date

sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"),
)

from policy_answer import (
    REFUSAL,
    build_context,
    build_prompt,
    check_citations,
    prepare_answer,
    sanitize_policy_text,
)
from policy_assistant import load_policies, select_policies


def test_policy_answer_safety_citations_and_clarification():
    policies = load_policies()
    today = date(2026, 11, 10)

    # Remove malicious instructions while retaining the legitimate policy text.
    support = [d for d in policies if d["doc_id"] == "POL-SUP-V1"]
    clean, flagged = sanitize_policy_text(support[0]["text"])
    assert flagged is True
    assert "Ignore all previous instructions" not in clean
    assert "9 AM to 6 PM" in clean

    # Ordinary policy text should not be flagged.
    refund = [d for d in policies if d["doc_id"] == "POL-REF-V2"]
    assert sanitize_policy_text(refund[0]["text"])[1] is False

    # The prompt should contain clean policy text and its source citation.
    context = build_context(support)
    prompt = build_prompt("When is support open?", context)
    assert "refunds are unlimited" not in prompt
    assert "[source: support_hours_v1]" in prompt

    # Accept a citation only when it names an allowed source.
    allowed = {"refund_policy_v2"}
    assert check_citations(
        "Refunds take 14 days [source: refund_policy_v2].", allowed
    ) is True
    assert check_citations("Refunds take 14 days.", allowed) is False
    assert check_citations(
        "Refunds take 30 days [source: refund_policy_v3].", allowed
    ) is False

    # Refuse when there is no evidence; ask for a region when needed.
    assert prepare_answer([])["status"] == "no_evidence"
    assert prepare_answer([])["message"] == REFUSAL

    result = select_policies(policies, today)
    clarification = prepare_answer([], result["needs_region"])
    assert clarification["status"] == "clarify_region"
    assert "IN" in clarification["message"]
    assert "US" in clarification["message"]

    # A matching policy provides evidence for an answer.
    assert prepare_answer(refund)["status"] == "ok"

import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from policy_answer import REFUSAL
from policy_assistant import load_policies
from policy_qa import answer_question

TODAY = date(2026, 11, 10)


class FakeLLM:
    """Stands in for Gemini so the tests need no internet or API key."""

    def __init__(self, reply):
        self.reply = reply
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.reply


@pytest.fixture(scope="module")
def policies():
    return load_policies()


def test_good_answer_returns_sources_and_only_current_policy(policies):
    llm = FakeLLM("Refunds are available within 14 days [source: refund_policy_v2].")
    r = answer_question("What is your refund policy?", policies, TODAY, llm)
    assert r["status"] == "ok" and r["sources"] == ["refund_policy_v2"]
    assert "refund_policy_v1" not in llm.prompts[0]
    assert "refund_policy_v3" not in llm.prompts[0]


def test_historical_question_uses_policy_active_on_that_date(policies):
    llm = FakeLLM("Refunds were available within 7 days [source: refund_policy_v1].")
    r = answer_question("What was the refund policy?", policies, date(2025, 6, 1), llm)
    assert r["status"] == "ok" and r["sources"] == ["refund_policy_v1"]


def test_uncited_or_made_up_source_is_rejected(policies):
    r = answer_question("What is your refund policy?", policies, TODAY, FakeLLM("Refunds take 14 days."))
    assert r["status"] == "rejected_uncited" and r["answer"] == REFUSAL
    r = answer_question("What is your refund policy?", policies, TODAY, FakeLLM("30 days [source: refund_policy_v3]."))
    assert r["status"] == "rejected_uncited"


def test_injected_instruction_never_reaches_the_ai(policies):
    llm = FakeLLM("Support is open 9 AM to 6 PM IST on weekdays [source: support_hours_v1].")
    r = answer_question("When is support open?", policies, TODAY, llm)
    assert r["status"] == "ok"
    assert "refunds are unlimited" not in llm.prompts[0]


def test_restricted_policy_is_refused_for_public_users(policies):
    llm = FakeLLM("should not be used")
    r = answer_question("When are instructors paid?", policies, TODAY, llm, user_level="public")
    assert r["status"] == "no_evidence" and llm.prompts == []


def test_restricted_policy_is_available_to_internal_users(policies):
    llm = FakeLLM("Instructors are paid on the 5th [source: instructor_payout_v1].")
    r = answer_question("When are instructors paid?", policies, TODAY, llm, user_level="internal")
    assert r["status"] == "ok"


def test_ambiguous_region_asks_for_clarification(policies):
    llm = FakeLLM("unused")
    r = answer_question("How long does the certificate take?", policies, TODAY, llm)
    assert r["status"] == "clarify_region" and llm.prompts == []


def test_region_given_returns_matching_policy(policies):
    llm = FakeLLM("Within 10 working days [source: certificate_policy_in].")
    r = answer_question("How long does the certificate take?", policies, TODAY, llm, region="IN")
    assert r["status"] == "ok" and r["sources"] == ["certificate_policy_in"]


def test_unrelated_question_is_refused_without_calling_the_ai(policies):
    llm = FakeLLM("unused")
    r = answer_question("Do you offer a python course?", policies, TODAY, llm)
    assert r["status"] == "no_evidence" and llm.prompts == []


def test_model_refusal_is_passed_through(policies):
    r = answer_question("What is your refund policy?", policies, TODAY, FakeLLM(REFUSAL))
    assert r["status"] == "no_evidence"
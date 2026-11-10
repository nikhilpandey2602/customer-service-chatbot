import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from policy_answer import REFUSAL, build_context, build_prompt, check_citations, prepare_answer, sanitize_policy_text
from policy_assistant import load_policies, select_policies

policies = load_policies()
today = date(2026, 11, 10)

# Prompt injection: the hidden order is removed, the real policy text stays.
support = [d for d in policies if d["doc_id"] == "POL-SUP-V1"]
clean, flagged = sanitize_policy_text(support[0]["text"])
assert flagged is True
assert "Ignore all previous instructions" not in clean
assert "9 AM to 6 PM" in clean

# A normal policy is not flagged.
refund = [d for d in policies if d["doc_id"] == "POL-REF-V2"]
assert sanitize_policy_text(refund[0]["text"])[1] is False

# The prompt sent to the AI never contains the injected sentence, and carries source tags.
context = build_context(support)
prompt = build_prompt("When is support open?", context)
assert "refunds are unlimited" not in prompt
assert "[source: support_hours_v1]" in prompt

# Citation checking: valid, missing, and made-up sources.
allowed = {"refund_policy_v2"}
assert check_citations("Refunds take 14 days [source: refund_policy_v2].", allowed) is True
assert check_citations("Refunds take 14 days.", allowed) is False
assert check_citations("Refunds take 30 days [source: refund_policy_v3].", allowed) is False

# Refusal when nothing applies, and region question when ambiguous.
assert prepare_answer([])["status"] == "no_evidence"
assert prepare_answer([])["message"] == REFUSAL
result = select_policies(policies, today)
cert_only = prepare_answer([], result["needs_region"])
assert cert_only["status"] == "clarify_region"
assert "IN" in cert_only["message"] and "US" in cert_only["message"]

# Normal case: enough evidence to answer.
assert prepare_answer(refund)["status"] == "ok"

print("ALL TESTS PASSED")
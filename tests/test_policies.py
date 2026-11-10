import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from policy_assistant import load_policies, select_policies

policies = load_policies()


def refund_version(on_date, level="public"):
    result = select_policies(policies, on_date, user_level=level)
    refunds = [d for d in result["selected"] if d["title"] == "Refund Policy"]
    return refunds[0]["version"] if refunds else None


# Current question: expired v1 and future v3 are ignored, v2 applies.
assert refund_version(date(2026, 11, 10)) == 2

# Historical question: the policy active on the customer's date.
assert refund_version(date(2025, 6, 1)) == 1

# After the future policy starts, v3 applies.
assert refund_version(date(2027, 4, 1)) == 3

# Access control: public users never get the internal policy, internal users do.
public = select_policies(policies, date(2026, 11, 10), user_level="public")
internal = select_policies(policies, date(2026, 11, 10), user_level="internal")
assert "Instructor Payout Policy" not in [d["title"] for d in public["selected"]]
assert "Instructor Payout Policy" in [d["title"] for d in internal["selected"]]

# Region: no region given -> ask which one; region given -> the matching policy.
assert [x["title"] for x in public["needs_region"]] == ["Certificate Policy"]
india = select_policies(policies, date(2026, 11, 10), region="IN")
us = select_policies(policies, date(2026, 11, 10), region="US")
assert [d["doc_id"] for d in india["selected"] if d["title"] == "Certificate Policy"] == ["POL-CERT-IN"]
assert [d["doc_id"] for d in us["selected"] if d["title"] == "Certificate Policy"] == ["POL-CERT-US"]

print("ALL TESTS PASSED")
import re

from policy_answer import REFUSAL, build_prompt, check_citations, prepare_answer
from policy_assistant import select_policies

STOPWORDS = {
    "the", "a", "an", "is", "are", "do", "does", "did", "what", "when", "how", "can", "i",
    "my", "your", "you", "of", "for", "to", "in", "on", "and", "or", "it", "this", "that",
    "there", "any", "get", "have", "has", "me", "we", "our", "policy", "policies",
    "long", "many", "much", "take", "about", "tell", "please", "with", "be", "will",
}
SYNONYMS = {
    "refunded": "refund",
    "reimburse": "refund",
    "reimbursement": "refund",
    "reimbursed": "refund",
    "certification": "certificate",
    "certified": "certificate",
    "paid": "payout",
    "salary": "payout",
    "instructors": "instructor",
}
_CITATION_RE = re.compile(r"\[source:\s*([^\]]+)\]")


def _tokens(text):
    words = re.findall(r"[a-z]+", text.lower())
    result = set()
    for w in words:
        if w in STOPWORDS:
            continue
        if len(w) > 3 and w.endswith("s"):
            w = w[:-1]
        result.add(SYNONYMS.get(w, w))
    return result


def _relevant(question_tokens, title):
    return bool(question_tokens & _tokens(title))


def filter_relevant(question, selected, needs_region):
    """Keep only the policies whose title matches words in the question."""
    q = _tokens(question)
    return (
        [d for d in selected if _relevant(q, d["title"])],
        [x for x in needs_region if _relevant(q, x["title"])],
    )


def answer_question(question, policies, on_date, llm, user_level="public", region=None, product=None):
    """Full flow. The rules choose the documents; the AI (llm) only writes the wording."""
    result = select_policies(policies, on_date, user_level=user_level, region=region, product=product)
    selected, needs_region = filter_relevant(question, result["selected"], result["needs_region"])
    prepared = prepare_answer(selected, needs_region)
    if prepared["status"] != "ok":
        return {"status": prepared["status"], "answer": prepared["message"], "sources": []}

    raw = llm(build_prompt(question, prepared["context"])).strip()
    if raw == REFUSAL:
        return {"status": "no_evidence", "answer": REFUSAL, "sources": []}

    allowed = {c["source"] for c in prepared["context"]}
    if not check_citations(raw, allowed):
        # Uncited or made-up sources: never show the answer to the customer.
        return {"status": "rejected_uncited", "answer": REFUSAL, "sources": []}

    sources = sorted({c.strip() for c in _CITATION_RE.findall(raw)})
    return {"status": "ok", "answer": raw, "sources": sources}
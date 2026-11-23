import json
import re

EPSILON = 1e-9
_STOPWORDS = {
    "the", "a", "an", "is", "are", "what", "how", "do", "does", "of", "to", "for",
    "in", "on", "and", "or", "i", "my", "can", "when", "which", "will",
}


def _tokens(text):
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOPWORDS}


def load_questions(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class KeywordEvaluator:
    """Scores a set of documents against fixed test questions. No AI, so it is repeatable.

    Each question has: "question", "expected_keywords" (words the answer must contain)
    and "source" (the document the answer should come from).
      accuracy  = share of questions whose best-matching document contains all expected keywords
      grounding = share of questions whose best-matching document is the expected source
    """

    def __init__(self, questions):
        if not questions:
            raise ValueError("The quality test needs at least one question")
        for q in questions:
            if not q.get("question") or not q.get("expected_keywords") or not q.get("source"):
                raise ValueError("Every quality question needs question, expected_keywords and source")
        self.questions = questions

    @staticmethod
    def _best_doc(question, docs):
        wanted = _tokens(question)
        best_name, best_score = None, 0
        for name in sorted(docs):
            score = len(wanted & _tokens(docs[name]))
            if score > best_score:
                best_name, best_score = name, score
        return best_name

    def __call__(self, docs):
        correct = grounded = 0
        for q in self.questions:
            name = self._best_doc(q["question"], docs)
            if name is None:
                continue
            if name == q["source"]:
                grounded += 1
            text = docs[name].lower()
            if all(k.lower() in text for k in q["expected_keywords"]):
                correct += 1
        total = len(self.questions)
        return {"accuracy": correct / total, "grounding": grounded / total}


class QualityGate:
    """Decides whether a candidate version may be activated.

    Rejected if accuracy or grounding is below the minimum, or lower than the
    currently active version (an update must never make the answers worse).
    If the evaluation itself fails, the update is rejected too.
    """

    def __init__(self, evaluator, min_accuracy=0.80, min_grounding=0.90):
        self.evaluator = evaluator
        self.min_accuracy = min_accuracy
        self.min_grounding = min_grounding

    @classmethod
    def from_config(cls, cfg, evaluator):
        gate = cfg["quality_gate"]
        return cls(evaluator, gate["min_accuracy"], gate["min_grounding"])

    def check(self, candidate_docs, baseline_docs=None):
        try:
            candidate = self.evaluator(candidate_docs)
            baseline = self.evaluator(baseline_docs) if baseline_docs else None
        except Exception as error:
            return {"approved": False, "reasons": [f"evaluation failed: {error}"],
                    "candidate": None, "baseline": None}

        reasons = []
        minimums = {"accuracy": self.min_accuracy, "grounding": self.min_grounding}
        for metric, minimum in minimums.items():
            if candidate[metric] < minimum - EPSILON:
                reasons.append(f"{metric} {candidate[metric]:.2f} is below the minimum {minimum:.2f}")
            if baseline and candidate[metric] < baseline[metric] - EPSILON:
                reasons.append(f"{metric} dropped from {baseline[metric]:.2f} to {candidate[metric]:.2f}")
        return {"approved": not reasons, "reasons": reasons, "candidate": candidate, "baseline": baseline}

    def review(self, store, version):
        """Check a stored candidate version against the active one. Changes nothing."""
        baseline = store.read_documents() if store.active_version() is not None else None
        return self.check(store.read_documents(version), baseline)
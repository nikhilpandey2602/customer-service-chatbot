import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gemini_client import gemini_llm
from policy_assistant import load_policies
from policy_qa import answer_question

# Usage: python src\policy_cli.py "question" [YYYY-MM-DD] [region] [public|internal]
question = sys.argv[1]
on_date = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date.today()
region = sys.argv[3] if len(sys.argv) > 3 else None
level = sys.argv[4] if len(sys.argv) > 4 else "public"

result = answer_question(question, load_policies(), on_date, gemini_llm, user_level=level, region=region)
print("STATUS :", result["status"])
print("ANSWER :", result["answer"])
print("SOURCES:", ", ".join(result["sources"]) or "none")
import os

from dotenv import load_dotenv
from google import genai

load_dotenv()

MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")


def gemini_llm(prompt):
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
    return response.text
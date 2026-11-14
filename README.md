# Customer Service Chatbot

A customer service chatbot built on my NullClass training project (the FAQ dataset comes from the course). It answers customer questions from an FAQ dataset using retrieval (FAISS) and the Gemini API, and includes a policy assistant that answers from versioned policy documents with source citations.

## FAQ chatbot
- Loads FAQ question/answer pairs from `dataset/dataset.csv` (tab-separated).
- Builds a FAISS vector index using the `all-MiniLM-L6-v2` embedding model.
- Retrieves the closest FAQ entries and asks Gemini to answer using only those entries.
- Replies "I don't know." when the answer is not in the dataset.

## Policy assistant (internship task 4, prototype)
Uses `dataset/policies.csv`, a set of sample policy documents I wrote for testing, with version, product, region, access level, effective date and expiry date.
- Selects the latest policy that applies on the chosen date. Expired and future-dated policies are ignored for current questions, and a date can be given for historical questions.
- Respects access level (public or internal) and region. If a question depends on the region and none is given, it asks which one.
- Removes instruction-like sentences hidden inside documents before they reach the model.
- Every answer must include a source citation. Answers with no citation or an unknown source are rejected, and the assistant refuses when no policy applies.
- The rules are plain Python and the model only writes the wording, so behaviour is tested automatically (`tests/`, run with `pytest`).

Known limits: relevance matching is keyword-based on policy titles, and the access-level dropdown in the app is a demo control, not real authentication.

## Changes from the training version
- The original used Google PaLM, which has been discontinued. It now uses the Gemini API (`google-genai`).
- Fixed dependency conflicts in the embedding stack, the dataset path and the loader settings for the tab-separated file.

## Run it
Tested on Windows with Python 3.11.
1. Create a virtual environment.
2. `pip install -r requirements.txt`
3. Create a `.env` file in the project root containing `GOOGLE_API_KEY=your_key` (never commit this file).
4. `streamlit run src/main.py`
5. In the FAQ tab, click **Create Knowledgebase** once, then ask a question. Use the Policy Assistant tab for policy questions.
6. Run the tests with `python -m pytest tests -q`.

## Planned work (internship tasks)
Knowledge-base update pipeline, multimodal analysis, support-ticket workflow, multilingual sentiment and escalation, and multi-language sessions. These are not built yet.
# Customer Service Chatbot

A customer service chatbot built on my NullClass training project. It answers customer questions from an FAQ dataset using retrieval (FAISS) and the Gemini API.

## What it does now
- Loads FAQ question/answer pairs from `dataset/dataset.csv` (tab-separated).
- Builds a FAISS vector index using the `all-MiniLM-L6-v2` embedding model.
- Retrieves the closest FAQ entries for a customer question and asks Gemini to answer using only those entries.
- Replies "I don't know." when the answer is not in the dataset.
- Streamlit web interface with a "Create Knowledgebase" button.

## Changes from the training version
- The original used Google PaLM, which has been discontinued. It now uses the Gemini API (`google-genai`).
- Fixed dependency conflicts in the embedding stack.
- Fixed the dataset path and loader settings for the tab-separated file.

## Run it
1. Install Python 3.11 and create a virtual environment.
2. `pip install -r requirements.txt`
3. Create a `.env` file in the project root containing `GOOGLE_API_KEY=your_key` (never commit this file).
4. `streamlit run src/main.py`
5. Click **Create Knowledgebase** once, then ask a question.

## Planned work (internship tasks)
Knowledge-base update pipeline, multimodal analysis, support-ticket workflow, RAG with metadata and citations, multilingual sentiment and escalation, and multi-language sessions. These are not built yet.
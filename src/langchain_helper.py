import os

from dotenv import load_dotenv
from google import genai
from langchain.document_loaders.csv_loader import CSVLoader
from langchain.embeddings import HuggingFaceEmbeddings
from langchain.vectorstores import FAISS

load_dotenv()

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET_PATH = os.path.join(PROJECT_DIR, "dataset", "dataset.csv")
vectordb_file_path = os.path.join(PROJECT_DIR, "faiss_index")

MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2"
)

PROMPT_TEMPLATE = """Given the following context and a question, generate an answer based on this context only.
In the answer try to provide as much text as possible from the "response" section in the source document context without making much changes.
If the answer is not found in the context, kindly state "I don't know." Don't try to make up an answer.
Give one single answer. Do not mention the context or say "based on the context".

CONTEXT: {context}

QUESTION: {question}"""


def create_vector_db():
    loader = CSVLoader(
        file_path=DATASET_PATH,
        source_column="prompt",
        encoding="utf-8",
        csv_args={"delimiter": "\t"},
    )
    data = loader.load()
    vectordb = FAISS.from_documents(documents=data, embedding=embeddings)
    vectordb.save_local(vectordb_file_path)


class QAChain:
    def __init__(self, retriever):
        self.retriever = retriever
        self.client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

    def __call__(self, question):
        docs = self.retriever.get_relevant_documents(question)
        context = "\n\n".join(d.page_content for d in docs)
        prompt = PROMPT_TEMPLATE.format(context=context, question=question)
        response = self.client.models.generate_content(
            model=MODEL_NAME, contents=prompt
        )
        return {"result": response.text, "source_documents": docs}


def get_qa_chain():
    vectordb = FAISS.load_local(vectordb_file_path, embeddings)
    retriever = vectordb.as_retriever(search_kwargs={"k": 2})
    return QAChain(retriever)
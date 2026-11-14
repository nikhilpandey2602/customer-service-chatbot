import os
import sys
from datetime import date

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gemini_client import gemini_llm
from langchain_helper import create_vector_db, get_qa_chain
from policy_assistant import load_policies
from policy_qa import answer_question

st.title("CUSTOMER SERVICE CHATBOT 🤖")
faq_tab, policy_tab = st.tabs(["FAQ Chatbot", "Policy Assistant"])

with faq_tab:
    if st.button("Create Knowledgebase"):
        create_vector_db()
        st.success("Knowledgebase created.")

    question = st.text_input("Question: ", key="faq_question")
    if question:
        chain = get_qa_chain()
        response = chain(question)
        st.header("Answer")
        st.write(response["result"])

with policy_tab:
    st.caption(
        "Answers come only from policy documents that apply on the chosen date, "
        "region and access level. Every answer cites its source."
    )
    policy_question = st.text_input("Policy question:", key="policy_question")
    on_date = st.date_input("Answer as of this date:", value=date.today())
    region_choice = st.selectbox("Region", ["Not specified", "IN", "US"])
    level = st.selectbox("Access level (demo only)", ["public", "internal"])

    if policy_question:
        region = None if region_choice == "Not specified" else region_choice
        with st.spinner("Checking policies..."):
            result = answer_question(
                policy_question,
                load_policies(),
                on_date,
                gemini_llm,
                user_level=level,
                region=region,
            )
        st.header("Answer")
        if result["status"] == "ok":
            st.write(result["answer"])
            st.caption("Sources: " + ", ".join(result["sources"]))
        elif result["status"] == "clarify_region":
            st.info(result["answer"])
        else:
            st.warning(result["answer"])

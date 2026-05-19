import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq

load_dotenv()

# Primary model — for reasoning, planning, writing
llm = ChatGroq(
    model=os.getenv("GROQ_PRIMARY_MODEL", "llama-3.3-70b-versatile"),
    temperature=0,
    max_retries=3,
)

# Fast model — for evaluation, routing decisions, structured extraction
# Smaller context, cheaper, faster — perfect for judge-style tasks
llm_fast = ChatGroq(
    model=os.getenv("GROQ_FAST_MODEL", "llama-3.1-8b-instant"),
    temperature=0,
    max_retries=3,
)

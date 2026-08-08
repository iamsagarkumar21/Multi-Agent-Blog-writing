import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq

load_dotenv()

# Primary model — for reasoning, planning, writing
langfuse_handler = None
callbacks = []


if os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"):


    try:
        try:
            from langfuse.langchain import CallbackHandler
        except ImportError:
            from langfuse.callback import CallbackHandler
        # The CallbackHandler automatically picks up environment variables:
        # LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, and LANGFUSE_HOST (optional)
        langfuse_handler = CallbackHandler()
        callbacks.append(langfuse_handler)
    except Exception as e:
        print(f"⚠️ Warning: Failed to initialize Langfuse CallbackHandler: {e}")


llm = ChatGroq(
    model=os.getenv("GROQ_PRIMARY_MODEL", "llama-3.3-70b-versatile"),
    temperature=0,
    max_retries=3,
    callbacks=callbacks,
)

# Fast model — for evaluation, routing decisions, structured extraction
# Smaller context, cheaper, faster — perfect for judge-style tasks
llm_fast = ChatGroq(
    model=os.getenv("GROQ_FAST_MODEL", "llama-3.1-8b-instant"),
    temperature=0,
    max_retries=3,
    callbacks=callbacks,
)


def flush_langfuse():
    if langfuse_handler:
        try:
            from langfuse import get_client
            get_client().flush()
        except ImportError:
            pass


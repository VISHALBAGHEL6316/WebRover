import os
from typing import Any

from dotenv import load_dotenv
from langchain_core.runnables import RunnableLambda
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings

load_dotenv()


def extract_structured(res: Any) -> Any:
    if isinstance(res, list) and len(res) > 0:
        if isinstance(res[0], dict) and "args" in res[0]:
            return res[0]["args"]
        return res[0]
    return res


class WebRoverChatGemini(ChatGoogleGenerativeAI):
    def with_structured_output(self, schema: Any, **kwargs: Any):
        base_runnable = super().with_structured_output(schema, **kwargs)
        return base_runnable | RunnableLambda(extract_structured)


llm = WebRoverChatGemini(
    model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"),
    temperature=0,
    max_retries=3,
)
llm_fast = WebRoverChatGemini(
    model=os.getenv("GEMINI_FAST_MODEL", "gemini-3.5-flash-lite"),
    temperature=0,
    max_retries=3,
)
llm_reasoning = WebRoverChatGemini(
    model=os.getenv("GEMINI_REASONING_MODEL", "gemini-3-flash-preview"),
    temperature=0,
    max_retries=3,
)
embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")

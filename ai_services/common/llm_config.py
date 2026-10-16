"""
LLM configuration — returns Claude LLM via Signify Okta SSO.
No API key needed; ai-gateway-login manages the JWT automatically.
"""
import os
from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel

load_dotenv()


def get_llm(temperature: float = 0.0) -> BaseChatModel:
    model = os.getenv("LLM_MODEL", "claude-sonnet-4-5")

    from langchain_anthropic import ChatAnthropic
    return ChatAnthropic(model=model, temperature=temperature)

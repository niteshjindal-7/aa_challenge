"""
LLM configuration — returns Claude LLM via Signify Okta SSO gateway.

The gateway at llm-gateway.signifyhealth.com proxies to Anthropic's API.
Auth token is managed by ai-gateway-login (Okta JWT, auto-refreshed).
"""
import os
import subprocess
import logging
from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel

load_dotenv()

logger = logging.getLogger(__name__)

SIGNIFY_GATEWAY_URL = "https://llm-gateway.signifyhealth.com"


def _get_gateway_token() -> str:
    """Get the current Okta JWT from ai-gateway-login."""
    try:
        result = subprocess.run(
            [os.path.expanduser("~/.local/bin/ai-gateway-login"), "token", "--quiet"],
            capture_output=True, text=True, timeout=10,
        )
        token = result.stdout.strip()
        if not token:
            raise RuntimeError("ai-gateway-login returned empty token")
        return token
    except FileNotFoundError:
        raise RuntimeError(
            "ai-gateway-login not found. Install from Self Service / Workspace One."
        )


def get_llm(temperature: float = 0.0) -> BaseChatModel:
    model = os.getenv("LLM_MODEL", "claude-sonnet-4-5")
    token = _get_gateway_token()

    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(
        model=model,
        temperature=temperature,
        anthropic_api_key=token,
        base_url=SIGNIFY_GATEWAY_URL,
    )

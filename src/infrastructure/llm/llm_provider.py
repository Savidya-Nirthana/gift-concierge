"""
Chat llm provider -3-model architecture.

Three specialised LLMs for different tasks:
- Router:    gpt-4o-mini via OpenRouter (reliable JSON output)
- Extractor: llama-3.1-8b-instant via Groq (ultra-fast structured extraction)
- Chat:      gemini-2.0-flash via OpenRouter (high quality synthesis)
"""


from typing import Optional, Any, Dict
from langchain_openai import ChatOpenAI

from infrastructure.config import (
    ROUTER_MODEL,
    ROUTER_PROVIDER,
    EXTRACTOR_MODEL,
    EXTRACTOR_PROVIDER,
    GROQ_BASE_URL,
    CHAT_MODEL,
    CHAT_PROVIDER,
    OPENROUTER_BASE_URL,
    get_api_key,
)

def _build_llm(
    model: str,
    provider: str, 
    temperature: float = 0,
    streaming: bool = False,
    max_tokens: Optional[int] = None,
    **kwargs: Any,
) -> ChatOpenAI:
    """Build LLM instance based on provider"""
    
    llm_kwargs: Dict[str, Any] = dict(
        model=model,
        temperature=temperature,
        streaming=streaming,
        max_tokens=max_tokens,
        **kwargs,
    )

    if provider == "openrouter":
        llm_kwargs["openai_api_base"] = OPENROUTER_BASE_URL
        llm_kwargs["openai_api_key"] = get_api_key("openrouter")
    elif provider == "groq":
        llm_kwargs["openai_api_base"] = GROQ_BASE_URL
        llm_kwargs["openai_api_key"] = get_api_key("groq")

    elif provider == "openai":
        llm_kwargs["openai_api_key"] = get_api_key("openai")


    else:
        raise ValueError(f"Unsupported provider: {provider}")
    
    return ChatOpenAI(**llm_kwargs)


def get_router_llm(temperature: float = 0, **kwargs: Any) -> ChatOpenAI:
    """Get router LLM instance"""
    return _build_llm(
        ROUTER_MODEL,
        ROUTER_PROVIDER,
        temperature=temperature,
        **kwargs,
    )

def get_extractor_llm(temperature: float = 0, **kwargs: Any) -> ChatOpenAI:
    """Get extractor LLM instance"""
    return _build_llm(
        EXTRACTOR_MODEL,
        EXTRACTOR_PROVIDER,
        temperature=temperature,
        **kwargs,
    )

def get_chat_llm(temperature: float = 0, **kwargs: Any) -> ChatOpenAI:
    """Get chat LLM instance"""
    return _build_llm(
        CHAT_MODEL,
        CHAT_PROVIDER,
        temperature=temperature,
        **kwargs,
    )



def check_config_vars():
    """Print all 3-model architecture configurations to verify correctness."""
    print("=== LLM Provider Configuration ===")
    print(f"ROUTER_MODEL:        {ROUTER_MODEL}")
    print(f"ROUTER_PROVIDER:     {ROUTER_PROVIDER}")
    print(f"EXTRACTOR_MODEL:     {EXTRACTOR_MODEL}")
    print(f"EXTRACTOR_PROVIDER:  {EXTRACTOR_PROVIDER}")
    print(f"GROQ_BASE_URL:       {GROQ_BASE_URL}")
    print(f"CHAT_MODEL:          {CHAT_MODEL}")
    print(f"CHAT_PROVIDER:       {CHAT_PROVIDER}")
    print(f"OPENROUTER_BASE_URL: {OPENROUTER_BASE_URL}")
    print("==================================")




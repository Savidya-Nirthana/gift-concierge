"""
Embedding model provider.
"""

from typing import List, Dict, Any
from langchain_openai import OpenAIEmbeddings

from infrastructure.config import (
    EMBEDDING_MODEL,
    PROVIDER,
    OPENROUTER_BASE_URL,
    get_api_key
)


def get_default_embeddings(
    batch_size: int = 100,
    show_progress: bool = False,
    **kwargs: Any
) -> OpenAIEmbeddings:
    """Get default embedding instance"""
    llm_kwargs: dict[str, Any] = dict(
        model=EMBEDDING_MODEL,
        show_progress_bar=show_progress,
        **kwargs,
    )

    if PROVIDER == "openrouter":
        llm_kwargs["openai_api_base"] = OPENROUTER_BASE_URL
        llm_kwargs["openai_api_key"] = get_api_key("openrouter")

    return OpenAIEmbeddings(**llm_kwargs)




def check_config_vars():
    """Print embedding configuration"""
    print("=== Embedding Configuration ===")
    print(f"EMBEDDING_MODEL: {EMBEDDING_MODEL}")
    print(f"PROVIDER: {PROVIDER}")
    print(f"OPENROUTER_BASE_URL: {OPENROUTER_BASE_URL}")
    print("==================================")
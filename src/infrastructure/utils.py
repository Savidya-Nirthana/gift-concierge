"""
Helper functions for RAG service
"""

import re
from typing import List

def format_docs(docs: list) -> str:
    """
    Format list of documents into a single context string.

    Args:
        docs: List of Langchain Document objects

    Returns:
        Formatted context string with source URLs.
    """

    formatted = []
    for i, doc in enumerate(docs, 1):
        url = doc.metadata.get('url', 'N/A')
        title = doc.metadata.get('title', 'N/A')
        content = doc.page_content[:1000]
        formatted.append(
            f"[Source {i}: {url}]\n"
            f"Title: {title}\n"
            f"Content: {content}\n"
        )
    return "\n---\n".join(formatted)
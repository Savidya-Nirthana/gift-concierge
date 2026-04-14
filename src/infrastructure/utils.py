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


def calculate_confidence(docs: list, query: str) -> float:
    """
    Calculate confidence score based on document similarity.

    Args:
        docs: List of Langchain Document objects
        query: Query string

    Returns:
        Confidence score between 0 and 1.
    """
    if not docs:
        return 0.0
    
    query_words = set(query.lower().split())
   
    # keyword overlap score
    overlaps = []
    for doc in docs:
        doc_words = set(doc.page_content.lower().split())
        overlap = len(query_words & doc_words) / len(query_words) if query_words else 0
        overlaps.append(overlap)
    
    keyword_score = sum(overlaps) / len(overlaps)

    # content richness
    avg_length = sum([len(doc.page_content) for doc in docs]) / len(docs)
    length_score = min( avg_length / 500, 1.0)

    # strategy diversity score
    strategies = set([doc.metadata.get('strategy', 'unknown') for doc in docs])
    diversity_score = len(strategies) / 3.0

    # weight each score
    return 0.5 * keyword_score + 0.3 * length_score + 0.2 * diversity_score

   
"""
RAG Service

"""

import hashlib
from loguru import logger
from typing import List, Any, Optional, Dict
import time

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableParallel, Runnable
from langchain_core.documents import Document
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.retrievers import BaseRetriever

from infrastructure.config import TOP_K_RESULTS, SIMILARITY_THRESHOLD
from infrastructure.observability import observe, update_current_observation
from services.chat_service.rag_templates import RAG_TEMPLATE
from infrastructure.utils import format_docs
from infrastructure.db.qdrant_client import search_chunks


def enrich_chunk_with_product_context(chunk_text: str, title: str, url: str)-> str:
    """
    If chunk looks like an add-on table (no product name in it),
    prepend the product header extracted from title/url metadata
    """
    is_addon_chunk = (
        "| RS." in chunk_text and          # has price rows
        title.lower() not in chunk_text.lower()  # but no product name
    )

    if not is_addon_chunk:
        return chunk_text

    sku = url.rstrip("/").split("_")[-1] if url else "unknown"
    product_name = title.replace("# ", "").replace(" Online Price in Sri Lanka | At Kapruka", "").strip()
    
    header = f"""Product: {product_name}
    SKU: {sku}
    Source: {url}

    --- Add-ons / Options for this product ---
    """

    return header + chunk_text


def _is_addon_only_chunk(text: str) -> bool:
    """
    Detect chunks that are purely add-on/accessory table rows with no
    actual product description (name, weight, flavour, etc.).

    These shared add-on catalogs are identical across all cake products
    and pollute retrieval results by crowding out real product chunks.
    """
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    if not lines:
        return False

    table_rows = sum(
        1 for l in lines
        if l.startswith("|") and ("RS." in l or "Standard" in l)
    )
    total_lines = len(lines)

    # If >60% of non-empty lines are price-table rows → add-on only
    return (table_rows / total_lines) > 0.6


def _text_fingerprint(text: str) -> str:
    """
    Create a short fingerprint to detect near-duplicate chunks.

    Identical add-on tables across products will hash to the same value,
    allowing us to keep only one copy.
    """
    normalized = text.strip()[:300].lower()
    return hashlib.md5(normalized.encode()).hexdigest()





class QdrantRetriever(BaseRetriever):
    """
    Retriver backed by qdrant cloud.
    """

    embedder: Any = None
    top_k: int = TOP_K_RESULTS
    score_threshold: float = SIMILARITY_THRESHOLD

    class Config:
        arbitrary_types_allowed = True

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: Optional[CallbackManagerForRetrieverRun] = None,
    ) -> List[Document]:
        """
        Get documents relevant to the query.

        Applies three post-retrieval filters:
        1. Skip add-on-only chunks (shared accessory tables)
        2. Deduplicate near-identical chunk content
        3. Deduplicate by parent_id
        """
        query_vector = self.embedder.embed_query(query)

        # Fetch many more candidates than top_k because add-on chunks
        # (identical across products) will be filtered out, and we need
        # to dig past them to reach actual product description chunks.
        fetch_k = min(self.top_k * 10, 200)

        # Use a lower threshold internally so real product chunks
        # (which score lower than the shared add-on tables) can be reached.
        internal_threshold = self.score_threshold * 0.5

        hits = search_chunks(
            query_vector=query_vector,
            top_k=fetch_k,
            score_threshold=internal_threshold,
        )

        seen_parents: set = set()
        seen_fingerprints: set = set()
        addon_skipped = 0
        dedup_skipped = 0
        docs = []

        for hit in hits:
            # --- already collected enough ---
            if len(docs) >= self.top_k:
                break

            chunk_text = hit["chunk_text"]
            parent_text = hit.get("parent_text")
            parent_id = hit.get("parent_id")

            # --- 1. Skip add-on-only chunks ---
            if _is_addon_only_chunk(chunk_text):
                addon_skipped += 1
                continue

            # --- 2. Deduplicate near-identical content ---
            fp = _text_fingerprint(chunk_text)
            if fp in seen_fingerprints:
                dedup_skipped += 1
                continue
            seen_fingerprints.add(fp)

            # --- 3. Deduplicate by parent_id ---
            if parent_id and parent_id in seen_parents:
                continue
            if parent_id:
                seen_parents.add(parent_id)

            page_content = parent_text if parent_text else chunk_text
            page_content = enrich_chunk_with_product_context(
                chunk_text=page_content,
                title=hit.get("title", ""),
                url=hit.get("url", "")
            )
            docs.append(
                Document(
                    page_content=page_content,
                    metadata={
                        "url": hit.get("url", ""),
                        "title": hit.get("title", ""),
                        "strategy": hit.get("strategy", ""),
                        "chunk_index": hit.get("chunk_index", 0),
                        "score": hit.get("score", 0.0),
                        "child_text": chunk_text,
                    }
                )
            )

        if addon_skipped or dedup_skipped:
            logger.info(
                "Retrieval filter: {} add-on chunks skipped, {} duplicates skipped, {} docs kept",
                addon_skipped, dedup_skipped, len(docs),
            )

        return docs



    




def build_rag_chain(
    retriever: BaseRetriever,
    llm: Any,
    k: int = TOP_K_RESULTS,
    template: str = RAG_TEMPLATE,
) -> Runnable:
    if hasattr(retriever, "search_kwargs"):
        retriever.search_kwargs["k"] = k
    
    rag_prompt = ChatPromptTemplate.from_template(template)

    rag_chain = (
        RunnableParallel(
            {"context" : retriever | format_docs, "question" : RunnablePassthrough()}
        )
        | rag_prompt
        | llm
        | StrOutputParser()
    )

    return rag_chain


class RAGService:
    def __init__(
        self,
        embedder: Any,
        llm: Any,
        k: int = TOP_K_RESULTS,
        score_threshold: float = SIMILARITY_THRESHOLD
    ):
        self.embedder = embedder
        self.llm = llm
        self.k = k

        self.retriever = QdrantRetriever(
            embedder = embedder,
            top_k=k,
            score_threshold=score_threshold
        )

        self.chain = build_rag_chain(self.retriever, llm, k)
    
    @observe(name="rag_generate", as_type="generation")
    def generate(self, query:str) -> Dict[str, Any]:
        start = time.time()
        evidence = self.retriever.invoke(query)

        answer = self.chain.invoke(query)

        elapsed = time.time() - start

        evidence_url = list(set(doc.metadata.get("url", "") for doc in evidence))
        
        update_current_observation(input=query, output=answer)

        return {
            "answer" : answer,
            "evidence": evidence,
            "evidence_urls" : evidence_url,
            "generation_time" : elapsed,
            "num_docs" : len(evidence)
        }
    
    def stream(self, query: str):
        """
        Stream answer generation (for real-time UI).
        
        Args:
            query: User question
        
        Yields:
            String chunks as they're generated
        """
        for chunk in self.chain.stream(query):
            yield chunk

    def batch(self, queries: List[str]) -> List[Dict[str, Any]]:
        """
        Generate answers for multiple queries in batch.
        
        Args:
            queries: List of user questions
        
        Returns:
            List of result dicts (same format as generate())
        """
        return [self.generate(query) for query in queries]


__all__ = ["build_rag_chain", "RAGService", "QdrantRetriever"]

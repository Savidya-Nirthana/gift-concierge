"""
CRAG Service
"""

from loguru import logger
from typing import Any, Dict, List, Optional
import time

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.retrievers import BaseRetriever

from infrastructure.config import (
    CRAG_CONFIDENCE_THRESHOLD,
    CRAG_EXPANDED_K,
    TOP_K_RESULTS
)

from infrastructure.observability import observe, update_current_observation
from services.chat_service.rag_templates import RAG_TEMPLATE
from services.chat_service.rag_service import QdrantRetriever
from infrastructure.utils import format_docs, calculate_confidence

class CRAGService:
    """
    Corrective RAG service with automatic self-correction.
    """
    def __init__(
        self,
        retriever: BaseRetriever,
        llm: Any,
        initial_k: int = TOP_K_RESULTS,
        expanded_k: int = CRAG_EXPANDED_K
    ):
        self.retriever = retriever
        self.llm = llm
        self.initial_k = initial_k
        self.expanded_k = expanded_k 

        self.prompt = ChatPromptTemplate.from_template(RAG_TEMPLATE)

    def _set_k(self, k: int) -> None:
        """
        Set k for the retriever
        """
        if isinstance(self.retriever, QdrantRetriever):
            self.retriever.top_k = k
        elif hasattr(self.retriever, "search_kwargs"):
            self.retriever.search_kwargs["k"] = k
    
    @observe(name="crag_generate", as_type="generation")
    def generate(
        self, 
        query: str,
        confidential_threshold: float = CRAG_CONFIDENCE_THRESHOLD,
        verbose: bool = True
    ) -> Dict[str, Any]:
        if verbose:
            logger.info(f"🔍 Query: {query}")
            logger.success(f"🎯 Confidence threshold: {confidential_threshold}\n")
        
        # Step 1: Initial retrieval
        if verbose:
            logger.info(f"1️⃣  Initial retrieval (k={self.initial_k})...")
        
        self._set_k(self.initial_k)
        docs_initial = self.retriever.invoke(query)
        confidence_initial = calculate_confidence(docs_initial, query)
        
        if verbose:
            logger.info(f"   📊 Confidence: {confidence_initial:.2f}")
        
        # Step 2: Check if correction needed
        if confidence_initial >= confidential_threshold:
            if verbose:
                logger.success(f"   ✅ Confidence sufficient - proceeding with initial retrieval")
            final_docs = docs_initial
            confidence_final = confidence_initial
            correction_applied = False
        else:
            if verbose:
                logger.warning(f"   ⚠️  Low confidence - applying corrective retrieval...\n")
            
            # Step 3: Corrective retrieval
            if verbose:
                logger.info(f"2️⃣  Corrective retrieval (k={self.expanded_k}, expanded)...")
            
            # Expand k for more diverse results
            self._set_k(self.expanded_k)
            docs_corrected = self.retriever.invoke(query)
            confidence_final = calculate_confidence(docs_corrected, query)
            
            if verbose:
                logger.info(f"   📊 Corrected confidence: {confidence_final:.2f}")
                improvement = (confidence_final - confidence_initial) * 100
                logger.info(f"   📈 Confidence improved by {improvement:.1f}%")
            
            final_docs = docs_corrected
            correction_applied = True
        
        # Step 4: Generate answer
        if verbose:
            logger.info(f"\n3️⃣  Generating answer...")
        
        start = time.time()
        
        # Format docs and generate
        context = format_docs(final_docs)
        prompt_input = {"context": context, "question": query}
        answer = (self.prompt | self.llm | StrOutputParser()).invoke(prompt_input)
        
        elapsed = time.time() - start
        
        # Extract evidence URLs
        evidence_urls = list(set([doc.metadata['url'] for doc in final_docs]))
        
        update_current_observation(input=query, output=answer, metadata={
            "confidence_initial": confidence_initial,
            "confidence_final": confidence_final,
            "correction_applied": correction_applied
        })

        return {
            'answer': answer,
            'confidence_initial': confidence_initial,
            'confidence_final': confidence_final,
            'correction_applied': correction_applied,
            'docs_used': len(final_docs),
            'generation_time': elapsed,
            'evidence_urls': evidence_urls,
            'evidence': final_docs
        }

    def batch_generate(
        self,
        queries: List[str],
        confidence_threshold: float = CRAG_CONFIDENCE_THRESHOLD
    ) -> List[Dict[str, Any]]:
        """
        Generate answers for multiple queries with CRAG.
        
        Args:
            queries: List of user questions
            confidence_threshold: Minimum confidence score
        
        Returns:
            List of result dicts (same format as generate())
        """
        results = []
        for query in queries:
            result = self.generate(query, confidence_threshold, verbose=False)
            results.append(result)
        return results
    
    def analyze_confidence(self, query: str) -> Dict[str, Any]:
        """
        Analyze confidence without generating answer (for debugging).
        
        Args:
            query: User question
        
        Returns:
            Dict with confidence metrics
        """
        # Initial retrieval
        self._set_k(self.initial_k)
        docs_initial = self.retriever.invoke(query)
        confidence_initial = calculate_confidence(docs_initial, query)
        
        # Expanded retrieval
        self._set_k(self.expanded_k)
        docs_expanded = self.retriever.invoke(query)
        confidence_expanded = calculate_confidence(docs_expanded, query)
        
        return {
            'query': query,
            'confidence_initial': confidence_initial,
            'confidence_expanded': confidence_expanded,
            'improvement': confidence_expanded - confidence_initial,
            'docs_initial': len(docs_initial),
            'docs_expanded': len(docs_expanded)
        }


__all__ = ['CRAGService']
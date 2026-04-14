import json
import time
import uuid
from typing import Any, Dict, List, Optional

from loguru import logger

_DEFAULT_COLLECTION = "cag_cache"

class CAGCache:
    """
    Qdrant-backed semantic cache for caching LLM responses.
    """

    def __init__(
        self,
        embedder: Any,
        collection_name: str = _DEFAULT_COLLECTION,
        dim: Optional[int] = None,
        similarity_threshold: Optional[float] = None,
        ttl_seconds: Optional[int] = None,
    ) -> None: 
        from infrastructure.config import (
            CAG_SIMILARITY_THRESHOLD,
            CAG_CACHE_TTL,
            EMBEDDING_DIM,
            CAG_COLLECTION_NAME,
        )
        self.embedder = embedder
        self.collection_name = collection_name or CAG_COLLECTION_NAME
        self.dim = dim or EMBEDDING_DIM
        self.similarity_threshold = similarity_threshold or CAG_SIMILARITY_THRESHOLD
        self.ttl_seconds = ttl_seconds or CAG_CACHE_TTL
        
        self.available = False

        try:
            from infrastructure.db.qdrant_client import get_qdrant_client, collection_exists
            self.client = get_qdrant_client()

            if not collection_exists(self.collection_name):
                self._create_collection()
            
            self.available = True
            logger.info(
                 "✓ CAG cache ready (Qdrant collection='{}', dim={}, threshold={:.2f})",
                self.collection_name,
                self.dim,
                self.similarity_threshold,
            )
        except Exception as e:
            logger.warning(f"CAG cache unavailable: {e}")

    def _create_collection(self) -> None:
        from qdrant_client.http.models import VectorParams, Distance
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config = VectorParams(
                size=self.dim,
                distance=Distance.COSINE,
                on_disk=False
            )
        )
        logger.info(
            "✓ Created Qdrant collection '{}' for CAG cache",
            self.collection_name
        )


    def get(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Lookup cached response for a query.
        """
        if not self.available:
            return None
        
        try:
            query_vec = self.embedder.embed_query(query)
        except Exception as e:
            logger.warning(f"CAG cache lookup failed: {e}")
            return None

        try:
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=query_vec,
                limit=1,
                score_threshold=self.similarity_threshold,
            )
        except Exception as e:
            logger.warning(f"CAG cache lookup failed: {e}")
            return None
        
        if not response or not response.points:
            return None
        
        hit = response.points[0]
        similarity = hit.score
        payload = hit.payload or {}

        if self.ttl_seconds and self.ttl_seconds > 0:
            entry_ts = payload.get("ts", 0.0)
            if entry_ts and (time.time() - float(entry_ts)) > self.ttl_seconds:
                return None
        
        cached_query = payload.get("query", "")
        logger.info(
            "✓ CAG cache HIT: query='{}' (similarity={:.3f})",
            cached_query,
            similarity,
        )

        evidence_raw = payload.get("evidence_urls", [])

        try:
            evidence_urls = json.loads(evidence_raw) if isinstance(evidence_raw, str) else evidence_raw
        except (json.JSONDecodeError, TypeError):
            evidence_urls = []
        
        return {
            "query": cached_query,
            "answer" : payload.get("answer", ""),
            "evidence_urls": evidence_urls,
            "similarity": similarity,
            "source": payload.get("source", "unknown"),
        }

    def set(self, query: str, response: Dict[str, Any], source: str = "cache") -> None:
        """
        Cache a response, indexed by the query's embedding.

        Args:
            query: Original user query.
            response: Dict with ``answer`` and optionally ``evidence_urls``.
            source: Origin of the cache entry (e.g., 'cache', 'faq').
        """
        if not self.available:
            return

        # Embed query
        try:
            query_vec = self.embedder.embed_query(query)
        except Exception as exc:
            logger.warning("CAG embed failed on SET: {}", exc)
            return

        from qdrant_client.http.models import PointStruct

        point_id = str(uuid.uuid4())
        payload = {
            "query": query,
            "answer": response.get("answer", ""),
            "evidence_urls": json.dumps(response.get("evidence_urls", [])),
            "ts": time.time(),
            "source": source,
        }

        try:
            self.client.upsert(
                collection_name=self.collection_name,
                points=[PointStruct(id=point_id, vector=query_vec, payload=payload)],
            )
            logger.debug("CAG cache SET: '{}' → point={}", query[:60], point_id)
        except Exception as exc:
            logger.warning("CAG cache SET error: {}", exc)

    def import_faqs(self, json_path: str = "data/kapruka_all_faqs.json") -> int:
        """
        Import FAQ JSON data into the CAG cache.
        Treats each FAQ question as a cached query.
        """
        if not self.available:
            return 0
        
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load FAQ JSON from {json_path}: {e}")
            return 0

        count = 0
        for page in data.get("pages", []):
            url = page.get("source_url", "")
            for cat in page.get("categories", []):
                for faq in cat.get("faqs", []):
                    question = faq.get("question")
                    answer = faq.get("answer")
                    if question and answer:
                        # Optional: format bullet points into the answer string
                        bullets = faq.get("bullet_points", [])
                        if bullets:
                            bullet_text = "\\n" + "\\n".join(f"- {b}" for b in bullets)
                            answer += bullet_text
                            
                        response = {
                            "answer": answer,
                            "evidence_urls": [url] if url else []
                        }
                        self.set(question, response, source="faq")
                        count += 1
                        
        logger.info(f"Imported {count} FAQs into CAG cache from {json_path}")
        return count

    def clear(self) -> None:
        """
        Drop and recreate the CAG cache collection.

        All cached entries are removed. The collection is recreated
        immediately so the cache is ready for new entries.
        """
        if not self.available:
            return

        try:
            self.client.delete_collection(self.collection_name)
            logger.info("Dropped CAG cache collection '{}'", self.collection_name)
        except Exception:
            pass  # Collection may not exist

        self._create_collection()
        logger.info("CAG cache cleared and collection recreated")

    def stats(self) -> Dict[str, Any]:
        """
        Return cache statistics.

        Returns:
            Dict with ``total_cached``, ``backend``, ``collection``,
            ``similarity_threshold``, ``ttl_seconds``.
        """
        return {
            "total_cached": self._count(),
            "backend": "qdrant",
            "collection": self.collection_name,
            "similarity_threshold": self.similarity_threshold,
            "ttl_seconds": self.ttl_seconds,
            "available": self.available,
        }

    # ── internal helpers ──────────────────────────────────────

    def _count(self) -> int:
        """Return number of cached entries."""
        if not self.available:
            return 0
        try:
            info = self.client.get_collection(self.collection_name)
            return info.points_count or 0
        except Exception:
            return 0

    # ── dunder helpers ────────────────────────────────────────

    def __len__(self) -> int:
        return self._count()

    def __contains__(self, query: str) -> bool:
        return self.get(query) is not None

    def __repr__(self) -> str:
        return (
            f"CAGCache(collection='{self.collection_name}', "
            f"threshold={self.similarity_threshold}, "
            f"ttl={self.ttl_seconds}s, "
            f"entries={self._count()}, "
            f"backend='qdrant')"
        )

        
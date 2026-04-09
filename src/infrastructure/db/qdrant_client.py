from loguru import logger
import uuid
from typing import Any, Dict, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    PointStruct,
    VectorParams,
    Filter,
    FieldCondition,
    MatchValue
)


from infrastructure.config import (
    QDRANT_API_KEY,
    QDRANT_URL,
    QDRANT_COLLECTION_NAME,
    EMBEDDING_DIM
)

_qdrant_client:Optional[QdrantClient] = None

def get_qdrant_client() -> QdrantClient:
    """
    Get or create singleton Qdrant client.
    """
    global _qdrant_client

    if _qdrant_client is not None:
        return _qdrant_client

    if not QDRANT_URL:
        raise RuntimeError(
            "QDRANT_URL not set in environment"
        )

    if not QDRANT_API_KEY:
        raise RuntimeError(
            "QDRANT_API_KEY not set in environment"
        )

    _qdrant_client = QdrantClient(
        url = QDRANT_URL,
        api_key=QDRANT_API_KEY,
        timeout=30
    )

    logger.info(
        f"Conntect to Qdrant cloud at {QDRANT_URL}"
    )

    return _qdrant_client

def ensure_collection(
    collection_name: str = QDRANT_COLLECTION_NAME,
    vector_size: int = EMBEDDING_DIM,
    distance: Distance = Distance.COSINE,
    on_disk: bool = True,
) -> None:
    """
    Create the qdrant collection if it does not exist.

    Safe to call repeatedly (idempotent).
    """

    client = get_qdrant_client()

    existing = [c.name for c in client.get_collections().collections]

    if collection_name in existing:
        logger.info(
            f"Collection '{collection_name}' already exists - skipping creation"
        )
        return

    client.create_collection(
        collection_name=collection_name,
        vectors_config = VectorParams(
            size=vector_size,
            distance=distance,
            on_disk = on_disk
        )
    )


    logger.info(
        f"Create Qdrant collection {collection_name} (dim={vector_size}, distance={distance})"
    )


def delete_collection(collection_name: str = QDRANT_COLLECTION_NAME) -> None:
    """
    Delete the qdrant collection if it exists.
    """
    client = get_qdrant_client()

    client.delete_collection(collection_name=collection_name)

    logger.info(
        f"Delete Qdrant collection {collection_name}"
    )


def collection_info(collection_name: str= QDRANT_COLLECTION_NAME) -> Dict[str, Any]:
    """
    Get information about the qdrant collection.
    """
    client = get_qdrant_client()

    info = client.get_collection(collection_name=collection_name)
    return {
        "name" : collection_name,
        "points_count" : info.points_count,
        "indexed_vectors_count" : info.indexed_vectors_count,
        "vector_size" : info.config.params.vectors.size,
        "distance": info.config.params.vectors.distance.name,
        "status" : info.status.name,
    }


def upsert_chunks(
    chunks: List[Dict[str, Any]],
    embeddings: List[List[float]],
    collection_name: str = QDRANT_COLLECTION_NAME,
    batch_size: int = 100,
) -> int:
    """
    Upsert text chunks and their embeddings into Qdrant.

    Args:
        chunks: List of chunk dicts (each must have 'id' field)
        embeddings: List of embedding vectors (must match chunk count)
        collection_name: Target collection name
        batch_size: Number of points to upsert per batch

    Returns:
        Total number of points upserted
    """

    if len(chunks) != len(embeddings):
        raise ValueError(
            f"Number of chunks ({len(chunks)}) must match number of embeddings ({len(embeddings)})"
        )

    client = get_qdrant_client()

    total = 0

    for i in range(0, len(chunks), batch_size):
        batch_chunks = chunks[i: i+batch_size]
        batch_embeddings = embeddings[i: i+batch_size]

        points = []
        for chunk, vec in zip(batch_chunks, batch_embeddings):
            point_id = str(uuid.uuid4())
            payload = {
                "chunk_text" : chunk.get('text', ""),
                "url" : chunk.get("url", ""),
                "title" : chunk.get("title", ""),
                "strategy" : chunk.get("strategy", "unknown"),
                "chunk_index": chunk.get("chunk_index",0),
            }

            for k, v in chunk.items():
                if k not in ("text","url", "title", "strategy", "chunk_index"):
                    payload[k] = v

            points.append(
                PointStruct(
                    id=point_id,
                    vector=vec,
                    payload=payload,
                )
            )

        client.upsert(
            collection_name = collection_name,
            points= points
        )

        total  += len(points)
        logger.debug(f"Upserted batch {i}-{i+len(points)} ({len(points)} points)")
    
    logger.info(f"Upserted {total} points into {collection_name}")
    return total


def search_chunks(
    quesry_vector: List[float],
    top_k: int = 5,
    score_threshold: float = 0.0,
    collection_name: str = QDRANT_COLLECTION_NAME,
    strategy_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Semantic search over the RAG knowledge base.

    Args:
        query_vector: Embedding of the query
        top_k: Maximum number of results to return
        score_threshold: Minimum similarity score to return
        collection_name: Target collection name
        strategy_filter: Optional filter by strategy

    Returns:
        List of matching chunks with scores
    """

    client = get_qdrant_client()

    query_filter = None

    if strategy_filter:
        query_filter = Filter(
            must=[
                FieldCondition(
                    key="strategy",
                    match=MatchValue(value=strategy_filter)
                )
            ]
        )

    response = client.query_points(
        collection_name = collection_name,
        query = query_vector,
        query_filter=query_filter,
        limit = top_k,
        score_threshold = score_threshold,
    )

    results = []
    for hit in response.points:
        payload = hit.payload or {}
        result = {
            "chunk_text": payload.get("chunk_text", ""),
            "url": payload.get("url", ""),
            "title": payload.get("title", ""),
            "strategy": payload.get("strategy", "unknown"),
            "chunk_index": payload.get("chunk_index", 0),
            "score": hit.score,
        }
        
        if "parent_text" in payload:
            result["parent_text"] = payload["parent_text"]

        if "parent_id" in payload:
            result["parent_id"] = payload["parent_id"]

        results.append(result)

    return results


def count_points(collection_name: str = QDRANT_COLLECTION_NAME) -> int: 
    """
    Count the number of points in the collection.
    """
    client = get_qdrant_client()
    info = client.get_collection(collection_name)
    return info.points_count or 0

def collection_exists(collection_name: str = QDRANT_COLLECTION_NAME) -> bool:
    """
    Check if collection exists
    """
    client = get_qdrant_client()
    collections = client.get_collections()
    return collection_name in [c.name for c in collections.collections]


def ensure_kb_ingested(
    collection_name: str = QDRANT_COLLECTION_NAME,
    source: str = "kb",
    strategy: str = "parent_child",
) -> None:
    """ """
    pass

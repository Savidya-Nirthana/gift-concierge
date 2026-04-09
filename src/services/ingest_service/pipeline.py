"""
Qdrant ingestion pipeline - load, chunk, embed, upsert.
"""

import json
from loguru import logger
import sys
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from infrastructure.config import (
    MARKDOWN_DIR,
    JSONL_DIR,
    KB_DIR,
    QDRANT_COLLECTION_NAME,
    EMBEDDING_BATCH_SIZE
)

from infrastructure.llm.embeddings import get_default_embeddings
from infrastructure.db.qdrant_client import (
    ensure_collection,
    delete_collection,
    upsert_chunks,
    collection_info
)

from services.ingest_service import (
    semantic_chunk,
    fixed_chunk,
    sliding_chunk,
    parent_child_chunk
)


STRATEGY_MAP = {
    "semantic": semantic_chunk,
    "fixed": fixed_chunk,
    "sliding": sliding_chunk,
    "parent_child": parent_child_chunk
}

def load_kb_docs(kb_dir: Path|None = None,) -> List[Dict[str, Any]]:
    """load internal knowledge base markdown files"""

    kb_dir = Path(kb_dir or KB_DIR)
    if not kb_dir.exists():
        raise FileNotFoundError(f"Knowledge-base directory not found: {kb_dir}")
    
    docs: List[Dict[str, Any]] = []

    for md_file in sorted(kb_dir.glob("*.md")):
        content = md_file.read_text(encoding="utf-8").strip()
        if not content:
            continue
    
        title = content.split("\n", 1)[0].strip() or md_file.stem
        doc_slug = md_file.stem.lstrip("0123456789_")
        url = f"internal://kapruka/{doc_slug}"
        docs.append({
            "url": url,
            "title": title,
            "content": content,
        })

    logger.info(f"Loaded {len(docs)} internal KB documents from {kb_dir}")
    return docs


        

"""

Core domain models.
Define Document, Chunk, Evidence, and related data structures.

"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass
class Document:
    """
    Represents a clarwled web document.
    """
    doc_id: str
    url: str
    title: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
  
    def __post_init__(self):
        if not self.url:
            raise ValueError("Document URL is required")
        if not self.content:
            raise ValueError("Document content cannot be empty")
        
    

@dataclass
class Chunk:
    """
    Represent a text chunk from a document.
    Attricbutes:
        text: the chunk content
        strategy: chunking strategy used to create the chunk
        chunk_index: Position in the original document
        url: Source document URL
        title: Source document title
        metadata: Metadata associated with the chunk
    """
    text: str
    strategy: str
    chunk_index: int
    url: str
    title: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.strategy not in ["fixed_size", "semantic", "sliding_window", "parent_child", "late_chunk"]:
            raise ValueError(f"Invalid chunking strategy: {self.strategy}")


    
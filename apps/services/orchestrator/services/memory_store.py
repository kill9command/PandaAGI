"""Qdrant-based memory store for PandaAI Orchestrator.

Architecture Reference:
    architecture/DOCUMENT-IO-SYSTEM/MEMORY_ARCHITECTURE.md

Key Design:
    - Uses Qdrant for vector similarity search
    - Uses sentence-transformers (all-MiniLM-L6-v2) for embeddings
    - Collection name: "panda_memories"
    - Handles connection errors gracefully (works even if Qdrant is down)

Memory Categories:
    - preference: User preferences learned from interactions
    - fact: Facts about the user (location, budget, etc.)
    - context: Turn context summaries for retrieval
    - research: Research results for caching
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from libs.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class Memory:
    """Memory entry returned from search."""

    id: str
    content: str
    category: str
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "content": self.content,
            "category": self.category,
            "score": self.score,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class MemoryStore:
    """Qdrant-based memory storage service.

    Provides semantic search over stored memories using vector embeddings.
    Handles Qdrant connection errors gracefully - the service continues
    to work even if Qdrant is down, returning empty results.

    Example usage:
        store = MemoryStore()
        await store.initialize()

        # Store a memory
        memory_id = await store.store(
            content="User prefers NVIDIA GPUs for gaming",
            category="preference",
            metadata={"topic": "electronics.gpu"}
        )

        # Search memories
        results = await store.search("GPU preferences", limit=5)

        # Delete a memory
        await store.delete(memory_id)
    """

    COLLECTION_NAME = "panda_memories"
    EMBEDDING_DIMENSION = 384  # all-MiniLM-L6-v2 dimension

    def __init__(self):
        """Initialize memory store."""
        self._settings = get_settings()
        self._client: Optional[Any] = None
        self._embedding_model: Optional[Any] = None
        self._initialized = False
        self._qdrant_available = False

    async def initialize(self) -> bool:
        """Initialize Qdrant connection and ensure collection exists.

        Returns:
            True if Qdrant is available, False otherwise
        """
        if self._initialized:
            return self._qdrant_available

        try:
            from qdrant_client import AsyncQdrantClient
            from qdrant_client.models import Distance, VectorParams

            self._client = AsyncQdrantClient(
                host=self._settings.qdrant.host,
                port=self._settings.qdrant.port,
            )

            # Check if collection exists
            collections = await self._client.get_collections()
            collection_names = [c.name for c in collections.collections]

            if self.COLLECTION_NAME not in collection_names:
                # Create collection
                await self._client.create_collection(
                    collection_name=self.COLLECTION_NAME,
                    vectors_config=VectorParams(
                        size=self.EMBEDDING_DIMENSION,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info(f"Created Qdrant collection: {self.COLLECTION_NAME}")

            self._qdrant_available = True
            logger.info(f"Connected to Qdrant at {self._settings.qdrant.host}:{self._settings.qdrant.port}")

        except ImportError:
            logger.warning("qdrant-client not installed, memory store will return empty results")
            self._qdrant_available = False
        except Exception as e:
            logger.warning(f"Failed to connect to Qdrant: {e}. Memory store will return empty results")
            self._qdrant_available = False

        self._initialized = True
        return self._qdrant_available

    async def store(
        self,
        content: str,
        category: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """Store a memory entry.

        Args:
            content: The memory content to store
            category: Memory category (preference, fact, context, research)
            metadata: Optional metadata dict

        Returns:
            Memory ID (UUID string)

        Raises:
            RuntimeError: If Qdrant is not available
        """
        await self.initialize()

        if not self._qdrant_available:
            logger.warning("Cannot store memory: Qdrant is not available")
            # Return a placeholder ID but don't actually store
            return f"offline_{uuid4()}"

        try:
            from qdrant_client.models import PointStruct

            memory_id = str(uuid4())
            embedding = await self._get_embedding(content)

            payload = {
                "content": content,
                "category": category,
                "created_at": datetime.utcnow().isoformat(),
                **(metadata or {}),
            }

            await self._client.upsert(
                collection_name=self.COLLECTION_NAME,
                points=[
                    PointStruct(
                        id=memory_id,
                        vector=embedding,
                        payload=payload,
                    )
                ],
            )

            logger.debug(f"Stored memory {memory_id} in category '{category}'")
            return memory_id

        except Exception as e:
            logger.error(f"Failed to store memory: {e}")
            raise RuntimeError(f"Failed to store memory: {e}") from e

    async def search(
        self,
        query: str,
        limit: int = 10,
        category: Optional[str] = None,
        min_score: float = 0.5,
    ) -> list[Memory]:
        """Search memories by semantic similarity.

        Args:
            query: Search query string
            limit: Maximum number of results
            category: Optional category filter
            min_score: Minimum similarity score (0.0-1.0)

        Returns:
            List of Memory objects sorted by relevance
        """
        await self.initialize()

        if not self._qdrant_available:
            logger.debug("Qdrant not available, returning empty search results")
            return []

        try:
            embedding = await self._get_embedding(query)

            # Build filter if category specified
            search_filter = None
            if category:
                from qdrant_client.models import Filter, FieldCondition, MatchValue
                search_filter = Filter(
                    must=[
                        FieldCondition(
                            key="category",
                            match=MatchValue(value=category),
                        )
                    ]
                )

            results = await self._client.search(
                collection_name=self.COLLECTION_NAME,
                query_vector=embedding,
                limit=limit,
                score_threshold=min_score,
                query_filter=search_filter,
            )

            memories = []
            for hit in results:
                payload = hit.payload or {}
                created_at = None
                if payload.get("created_at"):
                    try:
                        created_at = datetime.fromisoformat(payload["created_at"])
                    except (ValueError, TypeError):
                        pass

                memories.append(Memory(
                    id=str(hit.id),
                    content=payload.get("content", ""),
                    category=payload.get("category", "unknown"),
                    score=hit.score,
                    metadata={k: v for k, v in payload.items()
                             if k not in ("content", "category", "created_at")},
                    created_at=created_at,
                ))

            logger.debug(f"Found {len(memories)} memories for query: {query[:50]}...")
            return memories

        except Exception as e:
            logger.error(f"Memory search failed: {e}")
            return []

    async def delete(self, memory_id: str) -> bool:
        """Delete a memory by ID.

        Args:
            memory_id: The memory ID to delete

        Returns:
            True if deleted, False if not found or error
        """
        await self.initialize()

        if not self._qdrant_available:
            logger.warning("Cannot delete memory: Qdrant is not available")
            return False

        try:
            from qdrant_client.models import PointIdsList

            await self._client.delete(
                collection_name=self.COLLECTION_NAME,
                points_selector=PointIdsList(points=[memory_id]),
            )

            logger.debug(f"Deleted memory: {memory_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete memory {memory_id}: {e}")
            return False

    async def list_memories(
        self,
        category: Optional[str] = None,
        limit: int = 100,
    ) -> list[Memory]:
        """List memories, optionally filtered by category.

        Args:
            category: Optional category filter
            limit: Maximum number of results

        Returns:
            List of Memory objects
        """
        await self.initialize()

        if not self._qdrant_available:
            logger.debug("Qdrant not available, returning empty list")
            return []

        try:
            # Build filter if category specified
            scroll_filter = None
            if category:
                from qdrant_client.models import Filter, FieldCondition, MatchValue
                scroll_filter = Filter(
                    must=[
                        FieldCondition(
                            key="category",
                            match=MatchValue(value=category),
                        )
                    ]
                )

            # Use scroll to list all points
            records, _ = await self._client.scroll(
                collection_name=self.COLLECTION_NAME,
                limit=limit,
                scroll_filter=scroll_filter,
                with_payload=True,
                with_vectors=False,
            )

            memories = []
            for record in records:
                payload = record.payload or {}
                created_at = None
                if payload.get("created_at"):
                    try:
                        created_at = datetime.fromisoformat(payload["created_at"])
                    except (ValueError, TypeError):
                        pass

                memories.append(Memory(
                    id=str(record.id),
                    content=payload.get("content", ""),
                    category=payload.get("category", "unknown"),
                    score=1.0,  # No score for list operation
                    metadata={k: v for k, v in payload.items()
                             if k not in ("content", "category", "created_at")},
                    created_at=created_at,
                ))

            return memories

        except Exception as e:
            logger.error(f"Failed to list memories: {e}")
            return []

    async def get_by_id(self, memory_id: str) -> Optional[Memory]:
        """Retrieve a specific memory by ID.

        Args:
            memory_id: The memory ID

        Returns:
            Memory object or None if not found
        """
        await self.initialize()

        if not self._qdrant_available:
            return None

        try:
            records = await self._client.retrieve(
                collection_name=self.COLLECTION_NAME,
                ids=[memory_id],
                with_payload=True,
                with_vectors=False,
            )

            if not records:
                return None

            record = records[0]
            payload = record.payload or {}
            created_at = None
            if payload.get("created_at"):
                try:
                    created_at = datetime.fromisoformat(payload["created_at"])
                except (ValueError, TypeError):
                    pass

            return Memory(
                id=str(record.id),
                content=payload.get("content", ""),
                category=payload.get("category", "unknown"),
                score=1.0,
                metadata={k: v for k, v in payload.items()
                         if k not in ("content", "category", "created_at")},
                created_at=created_at,
            )

        except Exception as e:
            logger.error(f"Failed to get memory {memory_id}: {e}")
            return None

    async def _get_embedding(self, text: str) -> list[float]:
        """Get embedding vector for text using sentence-transformers.

        Uses all-MiniLM-L6-v2 model running on CPU.
        """
        try:
            if self._embedding_model is None:
                from sentence_transformers import SentenceTransformer
                self._embedding_model = SentenceTransformer("all-MiniLM-L6-v2")

            embedding = self._embedding_model.encode(text)
            return embedding.tolist()

        except ImportError:
            logger.warning("sentence-transformers not installed, using zero vector")
            return [0.0] * self.EMBEDDING_DIMENSION
        except Exception as e:
            logger.error(f"Embedding failed: {e}")
            return [0.0] * self.EMBEDDING_DIMENSION

    async def close(self) -> None:
        """Close the Qdrant connection."""
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None
            self._initialized = False
            self._qdrant_available = False

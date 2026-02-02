"""
Embedding Service for Cache System

Provides CPU-only embeddings for semantic similarity matching.
Uses sentence-transformers all-MiniLM-L6-v2 model.

Model specs:
- Size: 22M parameters, 384 dimensions
- Hardware: CPU-only (no GPU required)
- Memory: ~200MB RAM when loaded
- Latency: 20-50ms per embedding (single text)
- Token cost: 0 tokens (separate from main LLM)
"""
import logging
import numpy as np
import os
from pathlib import Path
from typing import Union, List, Optional

logger = logging.getLogger(__name__)

class EmbeddingService:
    """
    CPU-optimized embedding service for semantic similarity.

    Singleton pattern - model loaded once and reused across all requests.
    """

    _model = None
    _fallback_mode = False
    _model_path = None
    _device = 'cpu'
    _batch_size = 8

    def __init__(self):
        """Initialize embedding service (lazy loading)"""
        if EmbeddingService._model is None:
            self._load_model()

    def _load_model(self):
        """Load sentence-transformers model with GPU support and fallback"""
        try:
            # Force CPU before importing torch to avoid CUDA initialization
            os.environ['CUDA_VISIBLE_DEVICES'] = ''

            from sentence_transformers import SentenceTransformer
            import torch

            # Set custom cache directory
            project_root = Path(__file__).parent.parent.parent
            model_dir = project_root / "models" / "embeddings"

            # Set environment variable for sentence-transformers
            os.environ['SENTENCE_TRANSFORMERS_HOME'] = str(model_dir)

            # Force CPU to avoid GPU OOM (vLLM uses 90% of GPU)
            # Small embedding model works fine on CPU (20-50ms latency)
            device = 'cpu'
            batch_size = 8

            logger.info(f"[EmbeddingService] Loading all-MiniLM-L6-v2 from {model_dir}...")
            logger.info(f"[EmbeddingService] Device: {device.upper()}, Batch size: {batch_size}")

            EmbeddingService._model = SentenceTransformer(
                'sentence-transformers/all-MiniLM-L6-v2',
                cache_folder=str(model_dir),
                device=device  # Auto-select GPU or CPU
            )

            EmbeddingService._model_path = model_dir
            EmbeddingService._device = device
            EmbeddingService._batch_size = batch_size

            if device == 'cuda':
                logger.info("[EmbeddingService] ✓ GPU acceleration enabled! (~5-10x faster)")
            else:
                logger.info("[EmbeddingService] Model loaded successfully (~200MB RAM, CPU-only)")

        except ImportError as e:
            logger.error(f"[EmbeddingService] sentence-transformers not installed: {e}")
            logger.warning("[EmbeddingService] Install with: pip install sentence-transformers")
            logger.warning("[EmbeddingService] Falling back to keyword-only search")
            EmbeddingService._fallback_mode = True

        except Exception as e:
            logger.error(f"[EmbeddingService] Failed to load model: {e}")
            logger.warning("[EmbeddingService] Falling back to keyword-only search")
            EmbeddingService._fallback_mode = True

    def is_available(self) -> bool:
        """Check if embedding service is available"""
        return not EmbeddingService._fallback_mode

    def embed(self, text: Union[str, List[str]]) -> Optional[np.ndarray]:
        """
        Generate embeddings for text.

        Args:
            text: Single string or list of strings

        Returns:
            numpy array of shape (384,) for single text
            numpy array of shape (N, 384) for list of N texts
            None if fallback mode (embeddings unavailable)

        Performance:
            - Single text: ~20-50ms on CPU, ~2-5ms on GPU
            - Batch of 10: ~100-150ms on CPU, ~10-20ms on GPU
        """
        if EmbeddingService._fallback_mode:
            logger.warning("[EmbeddingService] Embeddings unavailable (fallback mode)")
            return None

        try:
            if isinstance(text, str):
                return EmbeddingService._model.encode(
                    text,
                    convert_to_numpy=True,
                    show_progress_bar=False
                )
            else:
                # Use dynamic batch size based on device
                return EmbeddingService._model.encode(
                    text,
                    convert_to_numpy=True,
                    batch_size=EmbeddingService._batch_size,  # Dynamic: 32 for GPU, 8 for CPU
                    show_progress_bar=False
                )

        except Exception as e:
            logger.error(f"[EmbeddingService] Failed to generate embeddings: {e}")
            return None

    def embed_batch(self, texts: List[str]) -> Optional[np.ndarray]:
        """
        Batch embed multiple texts for efficiency.

        This is an optimized method for embedding many texts at once.
        Uses GPU batching if available for 5-10x speedup.

        Args:
            texts: List of strings to embed

        Returns:
            numpy array of shape (N, 384) where N = len(texts)
            None if fallback mode

        Performance:
            - 100 texts on CPU: ~1-2s
            - 100 texts on GPU: ~200-400ms (5-10x faster)
        """
        if not texts:
            return None

        return self.embed(texts)  # Reuse embed() which handles batching

    def cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """
        Compute cosine similarity between two vectors.

        Args:
            a: First vector (384,)
            b: Second vector (384,)

        Returns:
            Similarity score (0.0-1.0)
        """
        if a is None or b is None:
            return 0.0

        try:
            return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
        except Exception as e:
            logger.error(f"[EmbeddingService] Failed to compute similarity: {e}")
            return 0.0

    def get_model_info(self) -> dict:
        """Get model information"""
        return {
            "model": "sentence-transformers/all-MiniLM-L6-v2",
            "dimensions": 384,
            "parameters": "22M",
            "hardware": "CPU-only",
            "memory": "~200MB RAM",
            "available": self.is_available(),
            "fallback_mode": EmbeddingService._fallback_mode,
            "model_path": str(EmbeddingService._model_path) if EmbeddingService._model_path else None
        }


# Global singleton instance
EMBEDDING_SERVICE = EmbeddingService()


# Convenience functions for backward compatibility
def get_embedding(text: Union[str, List[str]]) -> Optional[np.ndarray]:
    """Get embedding(s) for text"""
    return EMBEDDING_SERVICE.embed(text)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors"""
    return EMBEDDING_SERVICE.cosine_similarity(a, b)

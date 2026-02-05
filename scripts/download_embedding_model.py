#!/usr/bin/env python3
"""
Download embedding model for cache system.

This script downloads the sentence-transformers embedding model
to the local models directory for offline use.
"""
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def download_embedding_model():
    """Download all-MiniLM-L6-v2 model to local cache"""
    try:
        from sentence_transformers import SentenceTransformer

        # Set custom cache directory
        model_dir = project_root / "models" / "embeddings"
        model_dir.mkdir(parents=True, exist_ok=True)

        print(f"[Download] Downloading all-MiniLM-L6-v2 to {model_dir}...")
        print("[Download] This will download ~90MB of model files...")

        # Download model (will cache to SENTENCE_TRANSFORMERS_HOME)
        os.environ['SENTENCE_TRANSFORMERS_HOME'] = str(model_dir)

        model = SentenceTransformer(
            'sentence-transformers/all-MiniLM-L6-v2',
            cache_folder=str(model_dir),
            device='cpu'
        )

        print(f"[Download] Model downloaded successfully!")
        print(f"[Download] Location: {model_dir}")
        print(f"[Download] Size: ~200MB RAM when loaded")

        # Test the model
        print("\n[Test] Testing model with sample text...")
        test_embedding = model.encode("This is a test sentence", convert_to_numpy=True)
        print(f"[Test] Embedding shape: {test_embedding.shape}")
        print(f"[Test] Embedding dims: {test_embedding.shape[0]}")

        assert test_embedding.shape[0] == 384, f"Expected 384 dims, got {test_embedding.shape[0]}"

        print("\n[Success] Model downloaded and tested successfully!")
        print(f"[Success] Ready for cache system use")

        return True

    except ImportError as e:
        print(f"[Error] sentence-transformers not installed: {e}")
        print("[Error] Install with: pip install sentence-transformers")
        return False

    except Exception as e:
        print(f"[Error] Failed to download model: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = download_embedding_model()
    sys.exit(0 if success else 1)

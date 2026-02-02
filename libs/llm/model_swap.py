"""Model swap manager for MIND/EYES on vLLM.

EYES (vision model, Qwen3-VL-2B, ~5GB) swaps with MIND (Qwen3-4B-AWQ, ~3.3GB).
Only one model can be loaded at a time within the 8GB VRAM budget.

When vision tasks are needed:
1. Stop MIND vLLM instance
2. Start EYES vLLM instance
3. Execute vision task
4. Stop EYES, restart MIND

This swap takes ~60-90 seconds each way (model loads from disk).
"""

import asyncio
import subprocess
from pathlib import Path
from typing import Optional

from libs.core.config import get_settings
from libs.core.exceptions import InterventionRequired


class ModelSwapManager:
    """Manages MIND <-> EYES model swapping on single vLLM instance."""

    def __init__(self):
        self.settings = get_settings()
        self._current_model: str = "mind"  # mind or eyes
        self._swap_lock = asyncio.Lock()
        self._vllm_process: Optional[subprocess.Popen] = None

    @property
    def is_eyes_loaded(self) -> bool:
        """Check if EYES is currently loaded."""
        return self._current_model == "eyes"

    @property
    def is_mind_loaded(self) -> bool:
        """Check if MIND is currently loaded."""
        return self._current_model == "mind"

    @property
    def current_model(self) -> str:
        """Get the currently loaded model name."""
        return self._current_model

    async def ensure_eyes(self) -> bool:
        """
        Ensure EYES model is loaded.

        Stops MIND and starts EYES if needed.
        All text processing pauses during swap.

        Returns:
            True if EYES is now loaded
        """
        async with self._swap_lock:
            if self._current_model == "eyes":
                return True

            try:
                # 1. Stop MIND vLLM instance
                await self._stop_vllm()

                # 2. Start EYES vLLM instance
                await self._start_eyes()

                self._current_model = "eyes"
                return True

            except Exception as e:
                raise InterventionRequired(
                    component="ModelSwapManager",
                    error=f"Failed to swap to EYES: {e}",
                    context={"current_model": self._current_model},
                )

    async def ensure_mind(self) -> bool:
        """
        Ensure MIND model is loaded.

        Stops EYES and starts MIND if needed.

        Returns:
            True if MIND is now loaded
        """
        async with self._swap_lock:
            if self._current_model == "mind":
                return True

            try:
                # 1. Stop EYES vLLM instance
                await self._stop_vllm()

                # 2. Start MIND vLLM instance
                await self._start_mind()

                self._current_model = "mind"
                return True

            except Exception as e:
                raise InterventionRequired(
                    component="ModelSwapManager",
                    error=f"Failed to swap to MIND: {e}",
                    context={"current_model": self._current_model},
                )

    async def _stop_vllm(self):
        """Stop current vLLM instance."""
        if self._vllm_process:
            self._vllm_process.terminate()
            self._vllm_process.wait()
            self._vllm_process = None
            await asyncio.sleep(5)  # Allow GPU memory to free

    async def _start_mind(self):
        """Start MIND vLLM instance (Qwen3-4B-AWQ)."""
        models_dir = self.settings.project_root / "models"
        logs_dir = self.settings.project_root / "logs"

        # Ensure logs directory exists
        logs_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            "python", "-m", "vllm.entrypoints.openai.api_server",
            "--host", "0.0.0.0",
            "--port", "8000",
            "--model", str(models_dir / "Qwen3-4B-Instruct-2507-AWQ"),
            "--served-model-name", "mind",
            "--gpu-memory-utilization", "0.80",
            "--max-model-len", "4096",
            "--enforce-eager",  # Required on WSL
            "--trust-remote-code",
        ]

        self._vllm_process = subprocess.Popen(
            cmd,
            stdout=open(logs_dir / "vllm_mind.log", "a"),
            stderr=subprocess.STDOUT,
        )

        # Wait for model to load (~30-45s)
        await asyncio.sleep(45)

    async def _start_eyes(self):
        """Start EYES vLLM instance (Qwen3-VL-2B)."""
        models_dir = self.settings.project_root / "models"
        logs_dir = self.settings.project_root / "logs"

        # Ensure logs directory exists
        logs_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            "python", "-m", "vllm.entrypoints.openai.api_server",
            "--host", "0.0.0.0",
            "--port", "8000",  # Same port - models swap
            "--model", str(models_dir / "Qwen3-VL-2B-Instruct"),
            "--served-model-name", "eyes",
            "--gpu-memory-utilization", "0.80",
            "--max-model-len", "4096",
            "--enforce-eager",  # Required on WSL
            "--trust-remote-code",
        ]

        self._vllm_process = subprocess.Popen(
            cmd,
            stdout=open(logs_dir / "vllm_eyes.log", "a"),
            stderr=subprocess.STDOUT,
        )

        # Wait for model to load (~30-45s)
        await asyncio.sleep(45)


# Singleton instance
_model_swap_manager: ModelSwapManager | None = None


def get_model_swap_manager() -> ModelSwapManager:
    """Get model swap manager singleton."""
    global _model_swap_manager
    if _model_swap_manager is None:
        _model_swap_manager = ModelSwapManager()
    return _model_swap_manager

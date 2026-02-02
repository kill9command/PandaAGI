"""
CM Error Recovery with Checkpointing

Implements checkpoint/resume for streaming Context Manager calls to handle
partial failures gracefully.

Quality Agent Requirement: Handle partial CM failures gracefully, save partial
capsules after each successful call, resume from last checkpoint on failure.
"""
import logging
import json
import os
from typing import List, Dict, Any, Optional, Callable
from pathlib import Path

logger = logging.getLogger(__name__)


class CMStreamProcessor:
    """
    Context Manager stream processor with checkpoint/resume.

    Quality Agent Requirement: Handle partial CM failures gracefully,
    save partial capsules after each successful call, resume from
    last checkpoint on failure.
    """

    def __init__(self, turn_dir: str):
        """
        Initialize CM stream processor.

        Args:
            turn_dir: Turn directory path (e.g., panda_system_docs/turns/{turn_id})
        """
        self.turn_dir = turn_dir
        self.checkpoint_dir = os.path.join(turn_dir, ".cm_checkpoints")
        os.makedirs(self.checkpoint_dir, exist_ok=True)

    async def process_with_recovery(
        self,
        parts: List[str],  # List of bundle part paths
        cm_fn: Callable,   # CM processing function
        tool_name: str = "unknown"
    ) -> Dict[str, Any]:
        """
        Process bundle parts with checkpoint/resume capability.

        Args:
            parts: List of document part paths to process
            cm_fn: Async function that processes one part and returns claims
                   Signature: async def cm_fn(part_data: dict) -> List[dict]
            tool_name: Tool name for logging

        Returns:
            {
                "claims": List[dict],
                "capsule_path": str,
                "cm_calls": int,
                "parts_processed": int,
                "recovered_from_failure": bool,
                "checkpoint_used": bool
            }
        """

        all_claims = []
        cm_calls = 0
        checkpoint_used = False
        recovered_from_failure = False

        # Check for existing checkpoint
        checkpoint = self._load_checkpoint()
        if checkpoint:
            logger.info(
                f"[CMRecovery] Found checkpoint: {checkpoint['parts_processed']} parts already processed"
            )
            all_claims = checkpoint["claims"]
            cm_calls = checkpoint["cm_calls"]
            checkpoint_used = True

            # Skip already-processed parts
            start_index = checkpoint["parts_processed"]
        else:
            start_index = 0

        # Process remaining parts
        for i in range(start_index, len(parts)):
            part_path = parts[i]

            try:
                # Read part
                with open(part_path, 'r') as f:
                    part_data = json.load(f)

                logger.info(f"[CMRecovery] Processing part {i+1}/{len(parts)}: {part_path}")

                # Call CM
                claims = await cm_fn(part_data)
                cm_calls += 1

                # Extend claims
                if claims:
                    all_claims.extend(claims)

                # Save partial capsule
                partial_capsule_path = os.path.join(
                    self.turn_dir,
                    f"capsule_part_{cm_calls:03d}.md"
                )
                self._write_partial_capsule(partial_capsule_path, claims)

                # Checkpoint after successful processing
                self._save_checkpoint({
                    "parts_processed": i + 1,
                    "claims": all_claims,
                    "cm_calls": cm_calls,
                    "last_part": part_path,
                    "tool_name": tool_name
                })

                logger.info(f"[CMRecovery] Checkpoint saved: {i+1}/{len(parts)} parts")

            except Exception as e:
                logger.error(f"[CMRecovery] Failed to process part {i+1}/{len(parts)}: {e}")

                # Check if we have any successful claims
                if all_claims:
                    logger.warning(
                        f"[CMRecovery] Partial success: {len(all_claims)} claims from {i} parts"
                    )
                    recovered_from_failure = True
                    break  # Stop processing, return partial results
                else:
                    # No claims yet - this is a total failure
                    logger.error(f"[CMRecovery] Total failure: No claims extracted")
                    raise

        # Write final capsule
        final_capsule_path = os.path.join(self.turn_dir, "capsule.md")
        self._write_final_capsule(final_capsule_path, all_claims, tool_name)

        # Clean up checkpoints on complete success
        if len(all_claims) > 0 and not recovered_from_failure:
            self._clear_checkpoint()

        logger.info(
            f"[CMRecovery] Complete: {len(all_claims)} claims from {len(parts)} parts "
            f"({cm_calls} CM calls)"
        )

        return {
            "claims": all_claims,
            "capsule_path": final_capsule_path,
            "cm_calls": cm_calls,
            "parts_processed": len(parts) if not recovered_from_failure else start_index + len(all_claims),
            "recovered_from_failure": recovered_from_failure,
            "checkpoint_used": checkpoint_used
        }

    def _save_checkpoint(self, data: Dict[str, Any]):
        """Save checkpoint to disk."""
        checkpoint_path = os.path.join(self.checkpoint_dir, "checkpoint.json")
        with open(checkpoint_path, 'w') as f:
            json.dump(data, f, indent=2)

    def _load_checkpoint(self) -> Optional[Dict[str, Any]]:
        """Load checkpoint from disk if exists."""
        checkpoint_path = os.path.join(self.checkpoint_dir, "checkpoint.json")
        if os.path.exists(checkpoint_path):
            with open(checkpoint_path, 'r') as f:
                return json.load(f)
        return None

    def _clear_checkpoint(self):
        """Delete checkpoint after successful completion."""
        checkpoint_path = os.path.join(self.checkpoint_dir, "checkpoint.json")
        if os.path.exists(checkpoint_path):
            os.remove(checkpoint_path)
            logger.info("[CMRecovery] Checkpoint cleared")

    def _write_partial_capsule(self, path: str, claims: List[dict]):
        """Write partial capsule for debugging/recovery."""
        with open(path, 'w') as f:
            f.write("# Partial Capsule\n\n")
            if not claims:
                f.write("No claims in this part.\n")
            else:
                for claim in claims:
                    text = claim.get('text', claim.get('claim', 'N/A'))
                    confidence = claim.get('confidence', 0.0)
                    f.write(f"- [{confidence:.2f}] {text}\n")

    def _write_final_capsule(self, path: str, claims: List[dict], tool_name: str):
        """Write final aggregated capsule."""
        with open(path, 'w') as f:
            f.write("# Context Manager Capsule\n\n")
            f.write(f"**Tool**: {tool_name}\n")
            f.write(f"**Total Claims**: {len(claims)}\n\n")

            if not claims:
                f.write("No claims extracted.\n")
            else:
                for i, claim in enumerate(claims, 1):
                    text = claim.get('text', claim.get('claim', 'N/A'))
                    confidence = claim.get('confidence', 0.0)
                    source = claim.get('source', 'unknown')

                    f.write(f"## Claim {i}\n")
                    f.write(f"- **Text**: {text}\n")
                    f.write(f"- **Confidence**: {confidence:.2f}\n")
                    f.write(f"- **Source**: {source}\n\n")

    def has_checkpoint(self) -> bool:
        """Check if checkpoint exists."""
        checkpoint_path = os.path.join(self.checkpoint_dir, "checkpoint.json")
        return os.path.exists(checkpoint_path)


# Convenience function for backward compatibility
async def process_tool_output_with_recovery(
    tool_result: Dict[str, Any],
    turn_dir: str,
    cm_fn: Callable
) -> Dict[str, Any]:
    """
    Process tool output documents with streaming CM intake and error recovery.

    Args:
        tool_result: Tool result with documents.parts
        turn_dir: Turn directory
        cm_fn: CM processing function

    Returns:
        CM processing result with recovery info
    """

    parts = tool_result.get("documents", {}).get("parts", [])

    if not parts:
        # Single file - no streaming needed
        primary = tool_result.get("documents", {}).get("primary")
        if not primary:
            return {
                "claims": [],
                "capsule_path": None,
                "cm_calls": 0,
                "parts_processed": 0,
                "recovered_from_failure": False,
                "checkpoint_used": False
            }

        # Process single file
        with open(primary, 'r') as f:
            data = json.load(f)

        claims = await cm_fn(data)

        # Write capsule
        capsule_path = os.path.join(turn_dir, "capsule.md")
        processor = CMStreamProcessor(turn_dir)
        processor._write_final_capsule(
            capsule_path,
            claims,
            tool_result.get("tool_name", "unknown")
        )

        return {
            "claims": claims,
            "capsule_path": capsule_path,
            "cm_calls": 1,
            "parts_processed": 1,
            "recovered_from_failure": False,
            "checkpoint_used": False
        }

    # Multiple parts - use stream processor with recovery
    processor = CMStreamProcessor(turn_dir)
    return await processor.process_with_recovery(
        parts=parts,
        cm_fn=cm_fn,
        tool_name=tool_result.get("tool_name", "unknown")
    )

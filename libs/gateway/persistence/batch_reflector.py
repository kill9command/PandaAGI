"""
Batch Memory Reflector for Phase 8.1.

Periodically reviews recent conversation history as a batch and extracts
differential knowledge: new facts, corrections, connections, open questions.

One LLM call per batch (~10 turns). Writes to Knowledge_staging/ with
auto-promotion after independent confirmation across batches.

Architecture Reference:
    architecture/main-system-patterns/phase8.1-batch-memory-reflector.md
"""

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from libs.gateway.persistence.user_paths import UserPathResolver
from libs.gateway.persistence.reflector_signal import reset_after_batch

logger = logging.getLogger(__name__)

# Hard caps on LLM output (enforced by code)
MAX_NEW_FACTS = 2
MAX_CORRECTIONS = 1
MAX_CONNECTIONS = 2
MAX_OPEN_QUESTIONS = 2

# Promotion thresholds
PROMOTION_COUNT_REQUIRED = 2
BM25_PROMOTION_THRESHOLD = 0.7
BM25_DEDUP_THRESHOLD = 0.8

# Staging expiry
STAGING_EXPIRY_DAYS = 30

# GPU contention delay
GPU_YIELD_SECONDS = 5
GPU_RETRY_DELAY_SECONDS = 30

# Max tokens for batch input assembly
MAX_BATCH_TOKENS_ESTIMATE = 4000  # ~16000 chars at 4 chars/token


class BatchReflector:
    """
    Runs batch memory reflection as a background task.

    Usage:
        reflector = BatchReflector(user_id="default")
        await reflector.run_batch(signal_state, trigger_reason)
    """

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.resolver = UserPathResolver(user_id)
        self.staging_dir = self.resolver.user_dir / "Knowledge_staging"
        self.log_dir = self.resolver.logs_dir / "reflector"

    async def run_batch(
        self,
        signal_state: Any,
        trigger_reason: str,
    ) -> Dict[str, Any]:
        """
        Execute one batch reflection cycle.

        Called as a background task via asyncio.create_task().
        Returns batch log data (also written to disk).
        """
        start_time = time.time()
        batch_id = self._next_batch_id()

        logger.info(
            f"[BatchReflector] Starting batch {batch_id} for user={self.user_id} "
            f"(trigger={trigger_reason})"
        )

        try:
            # Yield GPU to next turn
            await asyncio.sleep(GPU_YIELD_SECONDS)

            # 1. Get turns to review
            turns = self._get_batch_turns(signal_state)
            if not turns:
                logger.info("[BatchReflector] No turns to review, skipping batch")
                reset_after_batch(self.user_id, signal_state.last_batch_turn)
                return {"batch_id": batch_id, "skipped": True, "reason": "no_turns"}

            turn_numbers = [t["turn_number"] for t in turns]
            logger.info(f"[BatchReflector] Reviewing turns: {turn_numbers}")

            # 2. Assemble batch input document
            batch_input = self._assemble_batch_input(turns)

            # 3. Get existing knowledge summaries for dedup context
            existing_knowledge = self._get_existing_knowledge_summaries(turns)

            # 4. Call LLM
            llm_output = await self._call_llm(batch_input, existing_knowledge)
            if llm_output is None:
                logger.warning("[BatchReflector] LLM call failed, aborting batch")
                self._write_batch_log(
                    batch_id, turn_numbers, trigger_reason,
                    signal_state.urgency_score, 0, 0, [], [], [],
                    time.time() - start_time
                )
                reset_after_batch(self.user_id, turn_numbers[-1])
                return {"batch_id": batch_id, "skipped": True, "reason": "llm_failure"}

            # 5. Apply quality gates
            filtered = self._apply_quality_gates(llm_output, turns)

            # 6. Write to staging
            staged_files = self._write_to_staging(filtered, batch_id, turn_numbers)

            # 7. Check promotions (staged items that appeared in multiple batches)
            promoted_files = self._check_promotions(filtered)

            # 8. Write observability log
            items_proposed = (
                len(llm_output.get("new_facts", []))
                + len(llm_output.get("corrections", []))
                + len(llm_output.get("connections", []))
                + len(llm_output.get("open_questions", []))
            )
            items_passed = (
                len(filtered.get("new_facts", []))
                + len(filtered.get("corrections", []))
                + len(filtered.get("connections", []))
                + len(filtered.get("open_questions", []))
            )
            rejections = filtered.get("_rejections", [])

            duration_ms = (time.time() - start_time) * 1000
            self._write_batch_log(
                batch_id, turn_numbers, trigger_reason,
                signal_state.urgency_score,
                items_proposed, items_passed,
                rejections, staged_files, promoted_files,
                duration_ms
            )

            # 9. Reset signal counters
            reset_after_batch(self.user_id, turn_numbers[-1])

            logger.info(
                f"[BatchReflector] Batch {batch_id} complete: "
                f"{items_passed}/{items_proposed} items passed gates, "
                f"{len(staged_files)} staged, {len(promoted_files)} promoted "
                f"({duration_ms:.0f}ms)"
            )

            return {
                "batch_id": batch_id,
                "turns_reviewed": turn_numbers,
                "items_proposed": items_proposed,
                "items_passed": items_passed,
                "staged_files": staged_files,
                "promoted_files": promoted_files,
            }

        except Exception as e:
            logger.error(f"[BatchReflector] Batch {batch_id} failed: {e}", exc_info=True)
            # Always reset counters even on failure to prevent infinite retrigger
            last_turn = signal_state.last_batch_turn
            if hasattr(signal_state, 'turns_since_last_batch') and signal_state.turns_since_last_batch > 0:
                # Estimate last turn from context
                last_turn = signal_state.last_batch_turn + signal_state.turns_since_last_batch
            reset_after_batch(self.user_id, last_turn)
            return {"batch_id": batch_id, "error": str(e)}

    # =========================================================================
    # Turn retrieval
    # =========================================================================

    def _get_batch_turns(self, signal_state: Any) -> List[Dict[str, Any]]:
        """
        Get turns to review for this batch.

        Reads turn directories from disk (filesystem is source of truth).
        Returns list of dicts with turn_number and paths.
        """
        turns_dir = self.resolver.turns_dir
        if not turns_dir.exists():
            return []

        last_batch_turn = signal_state.last_batch_turn

        # Find turn directories after last_batch_turn
        turn_dirs = []
        for entry in sorted(turns_dir.iterdir()):
            if not entry.is_dir() or not entry.name.startswith("turn_"):
                continue
            try:
                turn_num = int(entry.name.replace("turn_", ""))
            except ValueError:
                continue

            if turn_num > last_batch_turn:
                context_path = entry / "context.md"
                response_path = entry / "response.md"
                if context_path.exists():
                    turn_dirs.append({
                        "turn_number": turn_num,
                        "turn_dir": entry,
                        "context_path": context_path,
                        "response_path": response_path,
                    })

        # Cap at 10 turns (most recent if more)
        if len(turn_dirs) > 10:
            turn_dirs = turn_dirs[-10:]

        return turn_dirs

    # =========================================================================
    # Batch input assembly
    # =========================================================================

    def _assemble_batch_input(self, turns: List[Dict[str, Any]]) -> str:
        """
        Compile turn data into a single batch document for LLM.

        Reads §0 (query), §2 (context), §3 (plan), §6 (response) from context.md
        plus response.md. Caps total at ~4000 tokens.
        """
        parts = []
        total_chars = 0
        char_limit = MAX_BATCH_TOKENS_ESTIMATE * 4  # ~4 chars per token

        for turn_info in turns:
            turn_num = turn_info["turn_number"]
            context_path = turn_info["context_path"]
            response_path = turn_info["response_path"]

            turn_text = f"\n[Turn {turn_num}]\n"

            # Read context.md and extract sections
            try:
                context_content = context_path.read_text()
                sections = self._parse_sections(context_content)

                # §0: Query
                if "0" in sections:
                    query_text = sections["0"][:500]
                    turn_text += f"Query: {query_text}\n"

                # §2: Context (truncated)
                if "2" in sections:
                    ctx_text = sections["2"][:800]
                    turn_text += f"Context: {ctx_text}\n"

                # §3: Plan (truncated)
                if "3" in sections:
                    plan_text = sections["3"][:400]
                    turn_text += f"Plan: {plan_text}\n"

                # §6: Response (truncated)
                if "6" in sections:
                    resp_text = sections["6"][:600]
                    turn_text += f"Response: {resp_text}\n"

            except Exception as e:
                logger.warning(f"[BatchReflector] Failed to read context.md for turn {turn_num}: {e}")
                continue

            # Also read response.md if §6 was empty
            if "6" not in sections:
                try:
                    if response_path.exists():
                        resp_content = response_path.read_text()[:600]
                        turn_text += f"Response: {resp_content}\n"
                except Exception as e:
                    logger.debug(f"[BatchReflector] Failed to read response.md for turn {turn_num}: {e}")

            # Check budget - truncate oldest first
            if total_chars + len(turn_text) > char_limit and parts:
                break
            parts.append(turn_text)
            total_chars += len(turn_text)

        return "\n".join(parts)

    def _parse_sections(self, content: str) -> Dict[str, str]:
        """Parse context.md sections by §N markers."""
        sections = {}
        # Match section headers like "## 0. Original Query" or "## 3. Plan"
        section_pattern = re.compile(r'^## (\d+)\.\s+', re.MULTILINE)
        matches = list(section_pattern.finditer(content))

        for i, match in enumerate(matches):
            section_num = match.group(1)
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            sections[section_num] = content[start:end].strip()

        return sections

    # =========================================================================
    # Existing knowledge context
    # =========================================================================

    def _get_existing_knowledge_summaries(self, turns: List[Dict[str, Any]]) -> str:
        """
        BM25 search existing Knowledge/ with batch keywords.

        Returns top 10 file snippets so LLM knows what already exists.
        """
        knowledge_dir = self.resolver.knowledge_dir
        if not knowledge_dir.exists():
            return ""

        # Extract keywords from batch turns
        all_text = ""
        for turn_info in turns:
            try:
                content = turn_info["context_path"].read_text()
                all_text += content[:1000] + " "
            except Exception:
                continue

        if not all_text.strip():
            return ""

        # Collect knowledge files
        knowledge_files = []
        for md_file in knowledge_dir.rglob("*.md"):
            try:
                file_content = md_file.read_text()
                if len(file_content) < 10:
                    continue
                rel_path = md_file.relative_to(knowledge_dir)
                knowledge_files.append({
                    "path": str(rel_path),
                    "content": file_content,
                    "snippet": file_content[:200],
                })
            except Exception:
                continue

        if not knowledge_files:
            return ""

        # BM25 search
        try:
            from rank_bm25 import BM25Okapi

            query_tokens = self._tokenize(all_text)
            corpus_tokens = [self._tokenize(f["content"]) for f in knowledge_files]

            # Filter empty docs
            valid = [(i, tokens) for i, tokens in enumerate(corpus_tokens) if tokens]
            if not valid:
                return ""

            valid_indices = [i for i, _ in valid]
            valid_tokens = [t for _, t in valid]

            bm25 = BM25Okapi(valid_tokens)
            scores = bm25.get_scores(query_tokens)

            # Get top 10
            scored = sorted(
                zip(valid_indices, scores),
                key=lambda x: x[1],
                reverse=True,
            )[:10]

            lines = []
            for idx, score in scored:
                if score <= 0:
                    continue
                f = knowledge_files[idx]
                lines.append(f"- {f['path']}: {f['snippet']}")

            return "\n".join(lines)

        except ImportError:
            logger.warning("[BatchReflector] rank_bm25 not available, skipping knowledge search")
            return ""
        except Exception as e:
            logger.warning(f"[BatchReflector] BM25 search failed: {e}")
            return ""

    def _tokenize(self, text: str) -> List[str]:
        """Simple whitespace + lowercase tokenizer."""
        return re.findall(r'\b[a-z0-9]{2,}\b', text.lower())

    # =========================================================================
    # LLM call
    # =========================================================================

    async def _call_llm(
        self,
        batch_input: str,
        existing_knowledge: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Call the LLM to reflect on the batch.

        Uses the phase8_1_batch_reflector recipe via libs.llm.client.
        Returns parsed JSON output or None on failure.
        """
        try:
            from libs.gateway.llm.recipe_loader import load_recipe
            from libs.llm.client import get_llm_client
        except ImportError as e:
            logger.error(f"[BatchReflector] Cannot import LLM dependencies: {e}")
            return None

        try:
            recipe = load_recipe("pipeline/phase8_1_batch_reflector")
        except Exception as e:
            logger.error(f"[BatchReflector] Cannot load recipe: {e}")
            return None

        # Build the full prompt
        system_prompt = recipe.get_prompt()

        user_content = f"## BATCH TURNS\n{batch_input}"
        if existing_knowledge:
            user_content += f"\n\n## EXISTING KNOWLEDGE\n{existing_knowledge}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        # Call LLM
        llm_client = get_llm_client()
        try:
            response = await llm_client.complete(
                model_layer="mind",
                messages=messages,
                temperature=recipe._raw_spec.get("llm_params", {}).get("temperature", 0.6),
                max_tokens=1500,
            )
            raw_text = response.content
        except Exception as e:
            # Retry once after delay (GPU contention)
            logger.warning(f"[BatchReflector] LLM call failed, retrying in {GPU_RETRY_DELAY_SECONDS}s: {e}")
            await asyncio.sleep(GPU_RETRY_DELAY_SECONDS)
            try:
                response = await llm_client.complete(
                    model_layer="mind",
                    messages=messages,
                    temperature=recipe._raw_spec.get("llm_params", {}).get("temperature", 0.6),
                    max_tokens=1500,
                )
                raw_text = response.content
            except Exception as e2:
                logger.error(f"[BatchReflector] LLM retry also failed: {e2}")
                return None

        # Parse JSON from response
        return self._parse_llm_output(raw_text)

    def _parse_llm_output(self, raw_text: str) -> Optional[Dict[str, Any]]:
        """Parse and validate LLM JSON output, applying hard caps."""
        # Manual JSON extraction is justified here per CLAUDE.md exceptions:
        # extracting structured JSON from a prompt that explicitly requests bare JSON output.
        # Using a second LLM call for parsing would double GPU time for a background task.
        text = raw_text.strip()
        if text.startswith("```"):
            # Remove markdown code fence
            lines = text.split("\n")
            # Remove first line (```json or ```) and last line (```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            # Find the JSON object
            brace_start = text.index("{")
            # Find matching closing brace
            depth = 0
            for i in range(brace_start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        json_str = text[brace_start:i + 1]
                        break
            else:
                logger.warning("[BatchReflector] No complete JSON object found in LLM output")
                logger.debug(f"[BatchReflector] Raw output: {raw_text[:500]}")
                return None

            data = json.loads(json_str)
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning(f"[BatchReflector] Failed to parse LLM JSON: {e}")
            logger.debug(f"[BatchReflector] Raw output: {raw_text[:500]}")
            return None

        # Validate structure and apply hard caps
        result = {
            "new_facts": data.get("new_facts", [])[:MAX_NEW_FACTS],
            "corrections": data.get("corrections", [])[:MAX_CORRECTIONS],
            "connections": data.get("connections", [])[:MAX_CONNECTIONS],
            "open_questions": data.get("open_questions", [])[:MAX_OPEN_QUESTIONS],
        }

        return result

    # =========================================================================
    # Quality gates
    # =========================================================================

    def _apply_quality_gates(
        self,
        llm_output: Dict[str, Any],
        turns: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Apply quality gates to LLM output.

        Gates: turn existence, keyword match, file existence, BM25 dedup, drift guard.
        Returns filtered output with _rejections metadata.
        """
        turn_numbers = {t["turn_number"] for t in turns}
        turn_content_cache = {}  # turn_number -> context text
        rejections = []

        # Pre-cache turn content for keyword matching
        for t in turns:
            try:
                turn_content_cache[t["turn_number"]] = t["context_path"].read_text().lower()
            except Exception:
                turn_content_cache[t["turn_number"]] = ""

        # --- Gate new_facts ---
        filtered_facts = []
        for fact in llm_output.get("new_facts", []):
            # Gate 1: Turn existence
            source_turns = fact.get("source_turns", [])
            if not all(t in turn_numbers for t in source_turns):
                rejections.append({
                    "item": fact.get("title", ""),
                    "gate": "turn_existence",
                    "reason": f"Referenced turns {source_turns} not all in batch",
                })
                continue

            # Gate 2: Keyword match
            fact_content = fact.get("content", "").lower()
            fact_words = set(re.findall(r'\b[a-z]{3,}\b', fact_content))
            has_keyword_match = False
            for st in source_turns:
                turn_text = turn_content_cache.get(st, "")
                if any(w in turn_text for w in fact_words):
                    has_keyword_match = True
                    break
            if not has_keyword_match:
                rejections.append({
                    "item": fact.get("title", ""),
                    "gate": "keyword_match",
                    "reason": "No keywords from fact found in cited turns",
                })
                continue

            # Gate 3: Related file exists
            related = fact.get("related_existing", [])
            knowledge_dir = self.resolver.knowledge_dir
            valid_related = [r for r in related if (knowledge_dir / r).exists()]
            fact["related_existing"] = valid_related  # Clean up invalid refs

            # Gate 4: BM25 dedup against existing knowledge
            if self._is_duplicate_knowledge(fact_content):
                rejections.append({
                    "item": fact.get("title", ""),
                    "gate": "dedup",
                    "reason": "Similar content already in Knowledge/",
                })
                continue

            # Assign confidence based on source turn count
            fact["_confidence"] = self._assign_confidence(source_turns, turns)
            filtered_facts.append(fact)

        # --- Gate corrections ---
        filtered_corrections = []
        for correction in llm_output.get("corrections", []):
            existing_file = correction.get("existing_file", "")
            knowledge_dir = self.resolver.knowledge_dir

            # Gate 3: File exists
            if not (knowledge_dir / existing_file).exists():
                rejections.append({
                    "item": existing_file,
                    "gate": "file_exists",
                    "reason": f"Target file {existing_file} not found",
                })
                continue

            # Gate 1: Turn existence
            source_turns = correction.get("source_turns", [])
            if not all(t in turn_numbers for t in source_turns):
                rejections.append({
                    "item": existing_file,
                    "gate": "turn_existence",
                    "reason": f"Referenced turns {source_turns} not all in batch",
                })
                continue

            # Gate 5: Drift guard — don't override high-confidence with single turn
            if len(source_turns) <= 1:
                file_path = knowledge_dir / existing_file
                try:
                    file_content = file_path.read_text()
                    # Check frontmatter for confidence
                    conf_match = re.search(r'confidence:\s*([\d.]+)', file_content)
                    if conf_match and float(conf_match.group(1)) > 0.9:
                        rejections.append({
                            "item": existing_file,
                            "gate": "drift_guard",
                            "reason": f"Existing confidence > 0.9, only 1 source turn",
                        })
                        continue
                except Exception:
                    pass

            filtered_corrections.append(correction)

        # --- Gate connections ---
        filtered_connections = []
        for conn in llm_output.get("connections", []):
            knowledge_dir = self.resolver.knowledge_dir
            file_a = conn.get("file_a", "")
            file_b = conn.get("file_b", "")

            # Gate 3: Both files exist
            if not (knowledge_dir / file_a).exists() or not (knowledge_dir / file_b).exists():
                rejections.append({
                    "item": f"{file_a} <-> {file_b}",
                    "gate": "file_exists",
                    "reason": "One or both files not found",
                })
                continue

            # Gate 1: Turn existence
            source_turns = conn.get("source_turns", [])
            if not all(t in turn_numbers for t in source_turns):
                rejections.append({
                    "item": f"{file_a} <-> {file_b}",
                    "gate": "turn_existence",
                    "reason": f"Referenced turns {source_turns} not all in batch",
                })
                continue

            filtered_connections.append(conn)

        # --- Gate open_questions ---
        filtered_questions = []
        for q in llm_output.get("open_questions", []):
            source_turns = q.get("source_turns", [])
            if not all(t in turn_numbers for t in source_turns):
                rejections.append({
                    "item": q.get("question", "")[:50],
                    "gate": "turn_existence",
                    "reason": f"Referenced turns {source_turns} not all in batch",
                })
                continue
            filtered_questions.append(q)

        return {
            "new_facts": filtered_facts,
            "corrections": filtered_corrections,
            "connections": filtered_connections,
            "open_questions": filtered_questions,
            "_rejections": rejections,
        }

    def _is_duplicate_knowledge(self, content: str) -> bool:
        """BM25 dedup check against existing Knowledge/ files."""
        knowledge_dir = self.resolver.knowledge_dir
        if not knowledge_dir.exists():
            return False

        try:
            from rank_bm25 import BM25Okapi

            # Collect existing knowledge
            corpus = []
            for md_file in knowledge_dir.rglob("*.md"):
                try:
                    file_text = md_file.read_text()
                    if len(file_text) > 10:
                        corpus.append(file_text)
                except Exception:
                    continue

            if not corpus:
                return False

            query_tokens = self._tokenize(content)
            corpus_tokens = [self._tokenize(doc) for doc in corpus]

            # Filter empty
            valid_tokens = [t for t in corpus_tokens if t]
            if not valid_tokens or not query_tokens:
                return False

            bm25 = BM25Okapi(valid_tokens)
            scores = bm25.get_scores(query_tokens)
            max_score = max(scores) if len(scores) > 0 else 0

            # Normalize: BM25 scores aren't bounded, use relative threshold
            # If max score is significantly high, consider it a duplicate
            return max_score > BM25_DEDUP_THRESHOLD

        except ImportError:
            return False
        except Exception as e:
            logger.debug(f"[BatchReflector] BM25 dedup check failed: {e}")
            return False

    def _assign_confidence(
        self,
        source_turns: List[int],
        turns: List[Dict[str, Any]],
    ) -> float:
        """
        Assign confidence based on source turn count.

        1 turn → 0.60, 2 turns → 0.75, 3+ → 0.75 (0.85 if high-quality turn).
        """
        n = len(source_turns)
        if n <= 0:
            return 0.50
        if n == 1:
            return 0.60
        if n == 2:
            return 0.75

        # 3+ turns: check if any had high quality
        for turn_info in turns:
            if turn_info["turn_number"] in source_turns:
                # Check for metadata.json quality
                metadata_path = turn_info["turn_dir"] / "metadata.json"
                if metadata_path.exists():
                    try:
                        meta = json.loads(metadata_path.read_text())
                        if meta.get("quality_score", 0) >= 0.80:
                            val_outcome = meta.get("validation_outcome", "")
                            if val_outcome == "APPROVE":
                                return 0.85
                    except Exception:
                        pass
        return 0.75

    # =========================================================================
    # Staging area
    # =========================================================================

    def _write_to_staging(
        self,
        filtered: Dict[str, Any],
        batch_id: int,
        turn_numbers: List[int],
    ) -> List[str]:
        """Write filtered items to Knowledge_staging/ with YAML frontmatter."""
        staged_files = []

        for fact in filtered.get("new_facts", []):
            category = fact.get("category", "Facts")
            if category not in ("Facts", "Concepts", "Patterns"):
                category = "Facts"

            title = fact.get("title", "unnamed")
            # Slugify title
            slug = re.sub(r'[^a-z0-9_]', '_', title.lower())
            slug = re.sub(r'_+', '_', slug).strip('_')

            staging_subdir = self.staging_dir / category
            staging_subdir.mkdir(parents=True, exist_ok=True)

            file_path = staging_subdir / f"{slug}.md"
            confidence = fact.get("_confidence", 0.60)
            related = fact.get("related_existing", [])
            source_turns = fact.get("source_turns", [])

            frontmatter = (
                f"---\n"
                f"staged_at: {datetime.now().isoformat()}\n"
                f"batch_id: {batch_id}\n"
                f"promotion_count: 0\n"
                f"source_turns: {json.dumps(source_turns)}\n"
                f"confidence: {confidence}\n"
                f"related: {json.dumps(related)}\n"
                f"---\n\n"
            )

            content = frontmatter + f"# {title.replace('_', ' ').title()}\n\n{fact.get('content', '')}\n"

            try:
                file_path.write_text(content)
                rel_path = str(file_path.relative_to(self.resolver.user_dir))
                staged_files.append(rel_path)
                logger.info(f"[BatchReflector] Staged: {rel_path}")
            except Exception as e:
                logger.warning(f"[BatchReflector] Failed to write staged file: {e}")

        # Write open questions to staging
        for q in filtered.get("open_questions", []):
            staging_subdir = self.staging_dir / "OpenQuestions"
            staging_subdir.mkdir(parents=True, exist_ok=True)

            question_text = q.get("question", "")
            slug = re.sub(r'[^a-z0-9_]', '_', question_text[:50].lower())
            slug = re.sub(r'_+', '_', slug).strip('_')

            file_path = staging_subdir / f"{slug}.md"
            source_turns = q.get("source_turns", [])

            frontmatter = (
                f"---\n"
                f"staged_at: {datetime.now().isoformat()}\n"
                f"batch_id: {batch_id}\n"
                f"promotion_count: 0\n"
                f"source_turns: {json.dumps(source_turns)}\n"
                f"type: open_question\n"
                f"---\n\n"
            )

            content = (
                frontmatter
                + f"# Open Question\n\n"
                + f"**Question:** {question_text}\n\n"
                + f"**Why unresolved:** {q.get('why_unresolved', 'Unknown')}\n"
            )

            try:
                file_path.write_text(content)
                rel_path = str(file_path.relative_to(self.resolver.user_dir))
                staged_files.append(rel_path)
                logger.info(f"[BatchReflector] Staged question: {rel_path}")
            except Exception as e:
                logger.warning(f"[BatchReflector] Failed to write staged question: {e}")

        return staged_files

    def _check_promotions(self, current_batch: Dict[str, Any]) -> List[str]:
        """
        Check if any staged files should be promoted to Knowledge/.

        A staged file is promoted when it appears in 2+ separate batches
        (BM25 similarity > 0.7 with current batch output).

        Also auto-expires staged files older than 30 days with promotion_count < 2.
        """
        promoted_files = []

        if not self.staging_dir.exists():
            return promoted_files

        # Collect current batch content for comparison
        current_texts = []
        for fact in current_batch.get("new_facts", []):
            current_texts.append(fact.get("content", ""))
        for q in current_batch.get("open_questions", []):
            current_texts.append(q.get("question", ""))

        now = datetime.now()

        for md_file in self.staging_dir.rglob("*.md"):
            try:
                file_content = md_file.read_text()
            except Exception:
                continue

            # Parse frontmatter
            frontmatter = self._parse_frontmatter(file_content)
            if not frontmatter:
                continue

            promotion_count = frontmatter.get("promotion_count", 0)
            staged_at_str = frontmatter.get("staged_at", "")

            # Auto-expire old staged files
            try:
                staged_at = datetime.fromisoformat(staged_at_str)
                age_days = (now - staged_at).days
                if age_days > STAGING_EXPIRY_DAYS and promotion_count < PROMOTION_COUNT_REQUIRED:
                    logger.info(f"[BatchReflector] Expiring staged file: {md_file.name} (age={age_days}d)")
                    md_file.unlink()
                    continue
            except (ValueError, TypeError):
                pass

            # BM25 compare with current batch
            if current_texts:
                body = self._strip_frontmatter(file_content)
                similarity = self._bm25_similarity(body, current_texts)

                if similarity > BM25_PROMOTION_THRESHOLD:
                    promotion_count += 1
                    logger.debug(
                        f"[BatchReflector] Promotion count incremented: "
                        f"{md_file.name} -> {promotion_count}"
                    )

                    if promotion_count >= PROMOTION_COUNT_REQUIRED:
                        # Promote to Knowledge/
                        promoted_path = self._promote_to_knowledge(md_file, file_content, frontmatter)
                        if promoted_path:
                            promoted_files.append(promoted_path)
                            md_file.unlink()
                            continue

                    # Update promotion count in frontmatter
                    self._update_frontmatter_field(md_file, "promotion_count", promotion_count)

        return promoted_files

    def _promote_to_knowledge(
        self,
        staged_file: Path,
        file_content: str,
        frontmatter: Dict[str, Any],
    ) -> Optional[str]:
        """Move a staged file to Knowledge/ via direct write."""
        try:
            body = self._strip_frontmatter(file_content)
            confidence = frontmatter.get("confidence", 0.60)
            related = frontmatter.get("related", [])
            source_turns = frontmatter.get("source_turns", [])

            # Determine category from staging path
            category_dir = staged_file.parent.name  # e.g., "Facts", "Concepts"

            knowledge_dir = self.resolver.knowledge_dir / category_dir
            knowledge_dir.mkdir(parents=True, exist_ok=True)

            dest_path = knowledge_dir / staged_file.name
            new_frontmatter = (
                f"---\n"
                f"promoted_at: {datetime.now().isoformat()}\n"
                f"source_turns: {json.dumps(source_turns)}\n"
                f"confidence: {confidence}\n"
                f"related: {json.dumps(related if isinstance(related, list) else [])}\n"
                f"---\n\n"
            )
            dest_path.write_text(new_frontmatter + body)

            rel_path = str(dest_path.relative_to(self.resolver.user_dir))
            logger.info(f"[BatchReflector] Promoted: {rel_path}")
            return rel_path

        except Exception as e:
            logger.warning(f"[BatchReflector] Failed to promote {staged_file.name}: {e}")
            return None

    # =========================================================================
    # Frontmatter helpers
    # =========================================================================

    def _parse_frontmatter(self, content: str) -> Optional[Dict[str, Any]]:
        """Parse YAML frontmatter from markdown file."""
        if not content.startswith("---"):
            return None
        end = content.find("---", 3)
        if end == -1:
            return None
        try:
            import yaml
            fm_text = content[3:end].strip()
            return yaml.safe_load(fm_text) or {}
        except Exception:
            # Fallback: manual parsing
            fm = {}
            for line in content[3:end].strip().split("\n"):
                if ":" in line:
                    key, _, value = line.partition(":")
                    value = value.strip()
                    # Try to parse JSON values
                    try:
                        fm[key.strip()] = json.loads(value)
                    except (json.JSONDecodeError, ValueError):
                        fm[key.strip()] = value
            return fm

    def _strip_frontmatter(self, content: str) -> str:
        """Remove YAML frontmatter from markdown."""
        if not content.startswith("---"):
            return content
        end = content.find("---", 3)
        if end == -1:
            return content
        return content[end + 3:].strip()

    def _update_frontmatter_field(self, file_path: Path, key: str, value: Any) -> None:
        """Update a single field in a file's YAML frontmatter."""
        try:
            content = file_path.read_text()
            if not content.startswith("---"):
                return

            end = content.find("---", 3)
            if end == -1:
                return

            fm_text = content[3:end]
            body = content[end + 3:]

            # Replace the specific key
            pattern = re.compile(rf'^{re.escape(key)}:.*$', re.MULTILINE)
            if pattern.search(fm_text):
                new_value = json.dumps(value) if isinstance(value, (list, dict)) else str(value)
                fm_text = pattern.sub(f"{key}: {new_value}", fm_text)
            else:
                new_value = json.dumps(value) if isinstance(value, (list, dict)) else str(value)
                fm_text += f"\n{key}: {new_value}"

            file_path.write_text(f"---{fm_text}---{body}")
        except Exception as e:
            logger.debug(f"[BatchReflector] Failed to update frontmatter: {e}")

    # =========================================================================
    # BM25 similarity
    # =========================================================================

    def _bm25_similarity(self, text: str, reference_texts: List[str]) -> float:
        """Compute BM25 similarity between text and a set of reference texts."""
        try:
            from rank_bm25 import BM25Okapi

            query_tokens = self._tokenize(text)
            if not query_tokens:
                return 0.0

            corpus_tokens = [self._tokenize(t) for t in reference_texts]
            valid_tokens = [t for t in corpus_tokens if t]
            if not valid_tokens:
                return 0.0

            bm25 = BM25Okapi(valid_tokens)
            scores = bm25.get_scores(query_tokens)
            return max(scores) if len(scores) > 0 else 0.0

        except Exception:
            return 0.0

    # =========================================================================
    # Observability
    # =========================================================================

    def _next_batch_id(self) -> int:
        """Get next batch ID by scanning existing logs."""
        self.log_dir.mkdir(parents=True, exist_ok=True)

        existing = list(self.log_dir.glob("batch_*.json"))
        if not existing:
            return 1

        max_id = 0
        for f in existing:
            try:
                # Extract number from batch_NNN.json
                num = int(f.stem.replace("batch_", ""))
                max_id = max(max_id, num)
            except ValueError:
                continue
        return max_id + 1

    def _write_batch_log(
        self,
        batch_id: int,
        turn_numbers: List[int],
        trigger_reason: str,
        urgency_score: float,
        items_proposed: int,
        items_passed: int,
        rejections: List[Dict],
        staged_files: List[str],
        promoted_files: List[str],
        duration_ms: float,
    ) -> None:
        """Write observability log for this batch."""
        self.log_dir.mkdir(parents=True, exist_ok=True)

        log_data = {
            "batch_id": batch_id,
            "timestamp": datetime.now().isoformat(),
            "turns_reviewed": turn_numbers,
            "trigger": trigger_reason,
            "urgency_score": urgency_score,
            "quality_gate_results": {
                "items_proposed": items_proposed,
                "items_passed": items_passed,
                "rejections": rejections[:20],  # Cap logged rejections
            },
            "staged_files": staged_files,
            "promoted_files": promoted_files,
            "duration_ms": round(duration_ms, 1),
        }

        log_path = self.log_dir / f"batch_{batch_id:03d}.json"
        try:
            log_path.write_text(json.dumps(log_data, indent=2))
            logger.debug(f"[BatchReflector] Wrote batch log: {log_path}")
        except Exception as e:
            logger.warning(f"[BatchReflector] Failed to write batch log: {e}")

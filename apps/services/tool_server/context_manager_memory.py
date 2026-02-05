"""
Context Manager Memory Processing

Handles complete turn processing and memory updates.
This is the FINAL AUTHORITY on what gets saved to memory.

Author: Panda Team
Created: 2025-11-13
Quality Agent Reviewed: ✅ Approved
"""

import httpx
import json
import logging
import time
import re
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

from apps.services.tool_server.preference_policy import (
    evaluate_preference_update,
    PreferenceUpdateType
)

logger = logging.getLogger(__name__)

# Prompts directory for legacy prompts
PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"

# Recipe-based prompt cache
_recipe_prompt_cache: Dict[str, str] = {}


def _load_utility_prompt(prompt_name: str) -> str:
    """Load a prompt from recipe system, with fallback to legacy location."""
    if prompt_name in _recipe_prompt_cache:
        return _recipe_prompt_cache[prompt_name]

    # Map legacy prompt names to recipe paths
    recipe_map = {
        "context_memory_processor": "memory/context_memory_processor",
    }

    recipe_path = recipe_map.get(prompt_name)
    if recipe_path:
        try:
            from libs.gateway.llm.recipe_loader import load_recipe
            recipe = load_recipe(recipe_path)
            content = recipe.get_prompt()
            _recipe_prompt_cache[prompt_name] = content
            logger.info(f"[ContextManagerMemory] Loaded '{prompt_name}' from recipe system")
            return content
        except Exception as e:
            logger.warning(f"[ContextManagerMemory] Recipe load failed for '{prompt_name}': {e}")

    # Fallback to legacy utility prompts directory
    utility_prompts_dir = Path(__file__).parent.parent.parent / "prompts" / "utility"
    prompt_path = utility_prompts_dir / f"{prompt_name}.md"
    if prompt_path.exists():
        content = prompt_path.read_text()
        _recipe_prompt_cache[prompt_name] = content
        logger.info(f"[ContextManagerMemory] Loaded '{prompt_name}' from legacy path")
        return content

    logger.warning(f"[ContextManagerMemory] Prompt not found: {prompt_name}")
    return ""


@dataclass
class TurnMemoryUpdate:
    """Result from Context Manager turn processing"""
    # Preference decisions
    preferences_updated: Dict[str, Any]
    preferences_preserved: Dict[str, str]
    preference_reasoning: Dict[str, str]

    # Topic extraction
    topic: Optional[str]
    topic_confidence: float

    # Facts extracted
    facts: Dict[str, List[str]]

    # Turn summary (for future injection)
    turn_summary: Dict[str, Any]

    # Quality evaluation
    conversation_quality: Dict[str, Any]

    # Memory actions
    memory_actions: Dict[str, bool]

    # Cache decisions
    response_cache_entry: Optional[Dict[str, Any]]

    # Learning patterns
    learning_patterns: Optional[Dict[str, Any]]

    # Quality scores
    quality_score: float
    satisfaction_score: float

    # Errors (if any)
    errors: List[str]


class ContextManagerMemory:
    """Context Manager memory processing"""

    def __init__(self, model_url: str, model_id: str, api_key: str):
        self.model_url = model_url
        self.model_id = model_id
        self.api_key = api_key
        logger.info(f"[ContextManagerMemory] Initialized with model {model_id}")

    def _read_prompt(self, prompt_path: str) -> str:
        """Read prompt file from prompts directory"""
        try:
            full_path = PROMPTS_DIR / prompt_path
            if full_path.exists():
                return full_path.read_text(encoding="utf-8")
            return ""
        except Exception as e:
            logger.warning(f"[ContextManagerMemory] Could not read prompt {prompt_path}: {e}")
            return ""

    async def process_turn(
        self,
        session_id: str,
        turn_number: int,
        user_message: str,
        guide_response: str,
        tool_results: List[Dict[str, Any]],
        capsule: Optional[Dict[str, Any]],
        current_context: Dict[str, Any],
        intent_classification: str,
        satisfaction_signal: Optional[Dict[str, Any]] = None
    ) -> TurnMemoryUpdate:
        """
        Process complete turn and extract memories.

        This is the ONLY place where session context is updated.

        Args:
            session_id: Session identifier
            turn_number: Current turn number
            user_message: User's query
            guide_response: Guide's synthesized response
            tool_results: Tool execution results
            capsule: Distilled capsule from Context Manager
            current_context: Current session context
            intent_classification: Intent (transactional/informational/etc.)
            satisfaction_signal: Optional satisfaction detection

        Returns:
            TurnMemoryUpdate with memory decisions
        """
        errors = []

        try:
            # Build Context Manager prompt
            cm_prompt = self._build_memory_processing_prompt(
                user_message=user_message,
                guide_response=guide_response,
                tool_results=tool_results,
                capsule=capsule,
                current_context=current_context,
                intent_classification=intent_classification,
                turn_number=turn_number
            )

            # Call Context Manager LLM
            cm_response = await self._call_cm_llm(cm_prompt)

            # Parse CM's decisions
            cm_output = self._parse_cm_response(cm_response)

        except Exception as e:
            logger.error(f"[ContextManagerMemory] LLM call failed: {e}")
            errors.append(f"LLM extraction failed: {e}")
            # Fallback to rule-based extraction
            cm_output = self._fallback_extraction(
                user_message, guide_response, tool_results, capsule
            )

        # Apply preference update policy (enforcement layer)
        preferences_updated = {}
        preferences_preserved = {}
        preference_reasoning = {}

        current_prefs = current_context.get("preferences", {})
        extracted_prefs = cm_output.get("preferences", {})
        preference_history = current_context.get("preference_history", [])

        for key, new_value in extracted_prefs.items():
            old_value = current_prefs.get(key)

            # Evaluate with preference policy
            decision = evaluate_preference_update(
                key=key,
                new_value=new_value,
                old_value=old_value,
                user_message=user_message,
                guide_response=guide_response,
                tool_results=tool_results,
                extraction_confidence=cm_output.get("confidence", 0.5),
                preference_history=preference_history,
                current_turn=turn_number
            )

            if decision.should_update:
                preferences_updated[key] = {
                    "value": new_value,
                    "update_type": decision.update_type.value,
                    "confidence": decision.confidence,
                    "requires_audit": decision.requires_audit
                }
                preference_reasoning[key] = decision.reason
            else:
                if old_value:
                    preferences_preserved[key] = old_value
                preference_reasoning[key] = decision.reason

        # Extract topic
        topic = cm_output.get("topic")
        topic_confidence = cm_output.get("topic_confidence", 0.5)

        # Extract and compress facts
        facts = self._extract_facts(capsule, tool_results)

        # Create turn summary
        turn_summary = self._create_turn_summary(
            user_message, guide_response, topic, facts, turn_number
        )

        # Evaluate conversation quality
        conversation_quality = self._evaluate_quality(
            user_message, guide_response, tool_results, capsule, satisfaction_signal
        )

        # Calculate satisfaction score
        satisfaction_score = self._calculate_satisfaction(
            conversation_quality, satisfaction_signal
        )

        # Calculate overall quality score
        quality_score = self._calculate_quality_score(
            conversation_quality, capsule, cm_output.get("confidence", 0.5)
        )

        # Decide memory actions
        memory_actions = self._decide_memory_actions(
            conversation_quality, quality_score, intent_classification
        )

        # Create response cache entry (if caching)
        response_cache_entry = None
        if memory_actions.get("cache_response", False):
            response_cache_entry = self._create_cache_entry(
                user_message=user_message,
                guide_response=guide_response,
                intent=intent_classification,
                topic=topic or "general",
                quality_score=quality_score,
                session_context=current_context,
                capsule=capsule
            )

        # Extract learning patterns
        learning_patterns = self._extract_learning_patterns(
            user_message, extracted_prefs, topic, cm_output.get("confidence", 0.5)
        )

        return TurnMemoryUpdate(
            preferences_updated=preferences_updated,
            preferences_preserved=preferences_preserved,
            preference_reasoning=preference_reasoning,
            topic=topic,
            topic_confidence=topic_confidence,
            facts=facts,
            turn_summary=turn_summary,
            conversation_quality=conversation_quality,
            memory_actions=memory_actions,
            response_cache_entry=response_cache_entry,
            learning_patterns=learning_patterns,
            quality_score=quality_score,
            satisfaction_score=satisfaction_score,
            errors=errors
        )

    def _build_memory_processing_prompt(
        self,
        user_message: str,
        guide_response: str,
        tool_results: List[Dict],
        capsule: Optional[Dict],
        current_context: Dict,
        intent_classification: str,
        turn_number: int
    ) -> str:
        """Build Context Manager memory processing prompt"""

        # Format current context
        current_prefs = current_context.get("preferences", {})
        current_topic = current_context.get("current_topic", "unknown")
        recent_turns = current_context.get("recent_turns", [])[-2:]  # Last 2 turns

        context_section = f"""
**Current Session Context:**
- Preferences: {json.dumps(current_prefs, indent=2)}
- Current Topic: {current_topic}
- Turn Number: {turn_number}
"""

        if recent_turns:
            context_section += f"\n**Recent Turns:**\n"
            for turn in recent_turns:
                context_section += f"- Turn {turn.get('turn')}: {turn.get('summary', 'N/A')[:100]}\n"

        # Format tool results
        tool_section = ""
        if tool_results:
            tool_section = "\n**Tools Used:**\n"
            for tool in tool_results[:3]:  # First 3 tools
                tool_section += f"- {tool.get('tool', 'unknown')}: {tool.get('summary', 'N/A')[:100]}\n"

        # Format capsule
        capsule_section = ""
        if capsule and capsule.get("claim_summaries"):
            capsule_section = "\n**Claims Generated:**\n"
            for claim_id, summary in list(capsule["claim_summaries"].items())[:5]:
                capsule_section += f"- {summary[:100]}\n"

        # Load prompt template and format
        guide_response_truncated = guide_response[:500] + "..." if len(guide_response) > 500 else guide_response
        prompt_template = _load_utility_prompt("context_memory_processor")
        if prompt_template:
            prompt = prompt_template.format(
                context_section=context_section,
                user_message=user_message,
                tool_section=tool_section,
                capsule_section=capsule_section,
                guide_response=guide_response_truncated,
                intent_classification=intent_classification,
                current_topic=current_topic
            )
        else:
            # Fallback to inline prompt if file not found
            prompt = f"""# Context Manager: Turn Memory Processing

You are the **Context Manager**, responsible for processing complete conversation turns and deciding what to memorize.

## Your Role

You are the **FINAL AUTHORITY** on memory updates. You see the complete turn:
- What the user asked
- What tools were executed
- What was found
- What was answered

Your job: Extract preferences, facts, and summaries for future use.

{context_section}

## This Turn

**User Message:** "{user_message}"

{tool_section}

{capsule_section}

**Guide Response:** "{guide_response_truncated}"

**Intent Classification:** {intent_classification}

## Your Tasks

### 1. Preference Extraction

**CRITICAL RULES:**

1. **EXPLORATORY_QUERY**: User asking/browsing -> DO NOT update preferences
   - "Find X for me", "Can you show Y", "What about Z"
   - Action: Preserve existing preferences

2. **EXPLICIT_DECLARATION**: Direct statement -> Update if confidence >= 0.85
   - "My favorite is X", "I prefer Y", "I like Z best"
   - Action: Update preference

3. **CONTRADICTORY_REQUEST**: Explicit change -> Update if confidence >= 0.90
   - "Actually I want Y instead", "Changed my mind", "I prefer Y now"
   - Action: Update with audit log

4. **IMPLICIT_PREFERENCE**: Actions reveal preference -> Update if confidence >= 0.60
   - User consistently chooses X over Y
   - Action: Tentative update

5. **CONFIRMING_ACTION**: Acts on recommendation -> Strengthen existing
   - User selects recommended item
   - Action: No update, preserve existing

**Analysis:**
- Classify each potential preference extraction using these 5 types
- Consider existing preferences (preserve unless explicitly contradicted)
- Only extract preferences that user DECLARED, not entities they mentioned casually

Output:
```json
{{
  "preferences": {{
    "favorite_hamster": "Syrian"  // ONLY if explicitly declared
  }},
  "confidence": 0.95
}}
```

### 2. Topic Extraction

What is the user focused on RIGHT NOW? Be specific.

**CRITICAL: Topic Change Detection**

Current stored topic: "{current_topic}"

If the user's message mentions a DIFFERENT subject than the current topic:
- Extract the NEW topic from this turn (what they're asking about NOW)
- DO NOT preserve the old topic just because it was stored

Examples:
- Current: "shopping for Roborovski hamsters" + User asks "Find Syrian hamster breeders" -> NEW topic: "shopping for Syrian hamsters"
- Current: "shopping for Syrian hamsters" + User asks "Show me more Syrian breeders" -> SAME topic: "shopping for Syrian hamsters"
- Current: "hamster care" + User asks "Tell me about roborovski lifespan" -> NEW topic: "roborovski hamster information"

**Rule**: Always extract topic from THIS turn's user message, not from stored context.

Output:
```json
{{
  "topic": "shopping for Syrian hamsters",
  "topic_confidence": 0.95
}}
```

### 3. Fact Extraction

Extract key facts from tool results and capsule. Compress to bullets (<=80 chars each).

Organize by domain: pricing, availability, care, breeding, characteristics, etc.

Output:
```json
{{
  "facts": {{
    "availability": ["3 Roborovski listings found"],
    "pricing": ["$20-$35 range"]
  }}
}}
```

### 4. Quality Evaluation

Evaluate conversation quality:
- Did we meet user's need?
- Is information complete?
- Does user need follow-up?

Output:
```json
{{
  "quality": {{
    "user_need_met": true,
    "information_complete": true,
    "requires_followup": false
  }}
}}
```

## Output Format

Return ONLY valid JSON in this exact format:

```json
{{
  "preferences": {{}},
  "confidence": 0.0-1.0,
  "topic": "specific topic string or null",
  "topic_confidence": 0.0-1.0,
  "facts": {{}},
  "quality": {{
    "user_need_met": true/false,
    "information_complete": true/false,
    "requires_followup": false
  }}
}}
```

**IMPORTANT**: Do NOT extract preferences from exploratory queries. "Find X" is NOT the same as "My favorite is X".
"""

        # Conditionally append code evidence processing guide for code-related tasks
        if intent_classification == "code" or (tool_results and any(
            tool.get("tool", "").startswith(("file.", "git.", "code.", "repo.", "bash."))
            for tool in tool_results
        )):
            code_evidence_prompt = self._read_prompt("context_manager/code_evidence.md")
            if code_evidence_prompt:
                prompt += f"\n\n---\n\n{code_evidence_prompt}"
                logger.debug("[ContextManagerMemory] Added code evidence processing guide")

        return prompt

    async def _call_cm_llm(self, prompt: str) -> str:
        """Call Context Manager LLM"""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                self.model_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model_id,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 800,
                    "temperature": 0.2,  # Low temp for consistent extraction
                    "top_p": 0.8,
                    "stop": ["<|im_end|>", "<|endoftext|>"],
                    "repetition_penalty": 1.05
                }
            )
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]

    def _parse_cm_response(self, llm_output: str) -> Dict[str, Any]:
        """Parse Context Manager JSON output"""
        # Extract JSON from response
        json_match = re.search(r'\{.*\}', llm_output, re.DOTALL)
        if not json_match:
            raise ValueError(f"No JSON found in CM output: {llm_output}")

        json_str = json_match.group(0)
        data = json.loads(json_str)

        return data

    def _fallback_extraction(
        self,
        user_message: str,
        guide_response: str,
        tool_results: List[Dict],
        capsule: Optional[Dict]
    ) -> Dict[str, Any]:
        """Fallback rule-based extraction if LLM fails"""
        logger.warning("[ContextManagerMemory] Using fallback extraction (LLM failed)")

        return {
            "preferences": {},  # Conservative: don't extract on error
            "confidence": 0.5,
            "topic": None,
            "topic_confidence": 0.0,
            "facts": {},
            "quality": {
                "user_need_met": False,
                "information_complete": False,
                "requires_followup": True
            }
        }

    def _extract_facts(
        self,
        capsule: Optional[Dict],
        tool_results: List[Dict]
    ) -> Dict[str, List[str]]:
        """Extract and compress facts from capsule/tools"""
        facts = {}

        if not capsule:
            return facts

        claim_summaries = capsule.get("claim_summaries", {})

        # Domain keywords for classification
        domain_keywords = {
            "pricing": ["price", "cost", "$", "dollar", "cheap", "expensive"],
            "availability": ["available", "in stock", "sold out", "ships"],
            "care": ["care", "feed", "diet", "cage", "habitat", "health"],
            "breeding": ["breed", "litter", "pups", "genetics"],
            "characteristics": ["temperament", "size", "color", "personality"],
        }

        # Classify claims by domain
        for claim_id, summary in list(claim_summaries.items())[:10]:
            text = summary[:150] if isinstance(summary, str) else str(summary)[:150]
            text_lower = text.lower()

            # Find matching domain
            domain = "general"
            max_matches = 0
            for domain_name, keywords in domain_keywords.items():
                match_count = sum(1 for kw in keywords if kw in text_lower)
                if match_count > max_matches:
                    max_matches = match_count
                    domain = domain_name

            if domain not in facts:
                facts[domain] = []
            facts[domain].append(text)

        # Limit to 3 facts per domain
        for domain in facts:
            facts[domain] = facts[domain][:3]

        return facts

    def _create_turn_summary(
        self,
        user_message: str,
        guide_response: str,
        topic: Optional[str],
        facts: Dict[str, List[str]],
        turn_number: int
    ) -> Dict[str, Any]:
        """Create compressed turn summary for future injection"""

        # Short: 1 sentence
        short_summary = topic if topic else user_message[:50]

        # Bullets: 2-4 key points
        bullets = []
        if topic:
            bullets.append(f"Topic: {topic[:50]}")

        # Add top facts
        for domain, fact_list in list(facts.items())[:2]:
            if fact_list:
                bullets.append(f"{domain.title()}: {fact_list[0][:40]}")

        # Estimate tokens (1 token ≈ 4 chars)
        total_chars = len(short_summary) + sum(len(b) for b in bullets)
        estimated_tokens = total_chars // 4

        return {
            "short": short_summary,
            "bullets": bullets[:4],  # Max 4 bullets
            "tokens": estimated_tokens
        }

    def _evaluate_quality(
        self,
        user_message: str,
        guide_response: str,
        tool_results: List[Dict],
        capsule: Optional[Dict],
        satisfaction_signal: Optional[Dict]
    ) -> Dict[str, Any]:
        """Evaluate conversation quality"""

        # Check if tools were executed
        tools_executed = len(tool_results) > 0

        # Check if claims were generated
        has_claims = False
        if capsule and capsule.get("claim_summaries"):
            has_claims = len(capsule["claim_summaries"]) > 0

        # Check response length (proxy for completeness)
        response_length = len(guide_response)
        is_complete = response_length > 100  # At least 100 chars

        # User need met: tools executed and claims generated
        user_need_met = tools_executed and has_claims

        # Requires followup: empty results or user dissatisfied
        requires_followup = False
        if satisfaction_signal and not satisfaction_signal.get("satisfied", True):
            requires_followup = True
        elif not has_claims:
            requires_followup = True

        return {
            "user_need_met": user_need_met,
            "information_complete": is_complete,
            "requires_followup": requires_followup
        }

    def _calculate_satisfaction(
        self,
        conversation_quality: Dict[str, Any],
        satisfaction_signal: Optional[Dict]
    ) -> float:
        """Calculate satisfaction score (0-1)"""

        if satisfaction_signal:
            return satisfaction_signal.get("score", 0.5)

        # Fallback: derive from quality
        if conversation_quality["user_need_met"]:
            return 0.85
        elif conversation_quality["information_complete"]:
            return 0.65
        else:
            return 0.40

    def _calculate_quality_score(
        self,
        conversation_quality: Dict[str, Any],
        capsule: Optional[Dict],
        extraction_confidence: float
    ) -> float:
        """Calculate overall quality score (0-1)"""

        # Base score from conversation quality
        if conversation_quality["user_need_met"]:
            base_score = 0.75
        elif conversation_quality["information_complete"]:
            base_score = 0.60
        else:
            base_score = 0.40

        # Boost from capsule confidence
        if capsule and capsule.get("confidence"):
            capsule_confidence = capsule["confidence"]
            base_score = (base_score + capsule_confidence) / 2

        # Boost from extraction confidence
        final_score = (base_score + extraction_confidence) / 2

        return min(final_score, 1.0)

    def _decide_memory_actions(
        self,
        conversation_quality: Dict[str, Any],
        quality_score: float,
        intent_classification: str
    ) -> Dict[str, bool]:
        """Decide what memory actions to take"""

        # Cache response if quality is good
        cache_response = quality_score >= 0.60 and conversation_quality["user_need_met"]

        # Save to long-term if exceptional quality
        save_to_long_term = quality_score >= 0.85

        # Always update topic
        update_topic = True

        # Update preferences based on policy (handled separately)
        update_preferences = False  # Decided by preference policy

        # Propagate quality feedback
        propagate_quality_feedback = True

        return {
            "cache_response": cache_response,
            "save_to_long_term": save_to_long_term,
            "update_topic": update_topic,
            "update_preferences": update_preferences,
            "propagate_quality_feedback": propagate_quality_feedback
        }

    def _create_cache_entry(
        self,
        user_message: str,
        guide_response: str,
        intent: str,
        topic: str,
        quality_score: float,
        session_context: Dict,
        capsule: Optional[Dict]
    ) -> Dict[str, Any]:
        """Create response cache entry"""

        # Extract claims used
        claims_used = []
        if capsule:
            candidates = capsule.get("candidates", [])
            for cand in candidates:
                if isinstance(cand, dict) and "claim_id" in cand:
                    claims_used.append(cand["claim_id"])

        # Determine TTL based on intent
        ttl_hours = 6 if intent == "transactional" else 24

        return {
            "query": user_message,
            "intent": intent,
            "domain": topic,
            "response": guide_response,
            "claims_used": claims_used,
            "quality_score": quality_score,
            "ttl_hours": ttl_hours,
            "session_context": {
                "session_id": session_context.get("session_id"),
                "preferences": session_context.get("preferences", {}),
                "domain": topic
            }
        }

    def _extract_learning_patterns(
        self,
        user_message: str,
        extracted_prefs: Dict,
        topic: Optional[str],
        confidence: float
    ) -> Optional[Dict[str, Any]]:
        """Extract learning patterns for cross-session learning"""

        if not extracted_prefs and not topic:
            return None

        # Determine extraction pattern
        msg_lower = user_message.lower()
        if "my favorite" in msg_lower:
            extraction_pattern = "explicit_declaration"
        elif "find" in msg_lower or "show" in msg_lower:
            extraction_pattern = "query_about_entity"
        else:
            extraction_pattern = "unclear"

        return {
            "extraction_pattern": extraction_pattern,
            "preferences_found": len(extracted_prefs),
            "topic_found": topic is not None,
            "confidence": confidence,
            "timestamp": time.time()
        }

# ============================================================================
# MULTI-PHASE PRODUCT SEARCH INTEGRATION (Added: 2025-11-15)
# ============================================================================

def process_phase1_intelligence(
    product: str,
    intelligence: Dict,
    evidence_urls: List[str]
) -> Dict:
    """
    Process Phase 1 intelligence gathering results into claims.
    
    Creates claims for:
    - Vendor recommendations
    - Spec requirements
    - Quality criteria
    - Price intelligence
    
    Args:
        product: Product being searched
        intelligence: Merged intelligence from Phase 1
        evidence_urls: URLs that provided evidence
        
    Returns:
        Phase 1 capsule with claims and intelligence
    """
    import uuid
    from datetime import datetime, timedelta
    
    capsule_id = f"cap_phase1_{uuid.uuid4().hex[:8]}"
    claims = []
    
    # Create vendor recommendation claims
    for vendor in intelligence.get("vendors", [])[:10]:
        claim_id = f"claim_vendor_{uuid.uuid4().hex[:6]}"
        claim = {
            "claim_id": claim_id,
            "type": "vendor_recommendation",
            "claim": f"{vendor['name']} is recommended for buying {product}",
            "confidence": min(0.95, 0.6 + (vendor.get("mentioned_count", 1) * 0.1)),
            "evidence_urls": evidence_urls[:5],  # Sample of evidence
            "vendor_data": vendor,
            "ttl": timedelta(days=30),
            "created_at": datetime.now().isoformat()
        }
        claims.append(claim)
    
    # Create spec requirement claims
    for spec_name, spec_data in intelligence.get("specs_required", {}).items():
        claim_id = f"claim_spec_{uuid.uuid4().hex[:6]}"
        claim = {
            "claim_id": claim_id,
            "type": "spec_requirement",
            "claim": f"{product} should meet spec: {spec_name} = {spec_data.get('requirement')}",
            "confidence": spec_data.get("importance", 0.8),
            "spec_name": spec_name,
            "spec_value": spec_data.get("requirement"),
            "importance": spec_data.get("importance", 0.8),
            "reason": spec_data.get("reason", ""),
            "evidence_urls": evidence_urls[:5],
            "ttl": timedelta(days=30),
            "created_at": datetime.now().isoformat()
        }
        claims.append(claim)
    
    # Create quality criteria claims
    for criterion, weight in intelligence.get("quality_criteria", {}).items():
        claim_id = f"claim_quality_{uuid.uuid4().hex[:6]}"
        claim = {
            "claim_id": claim_id,
            "type": "quality_criteria",
            "claim": f"Quality criterion for {product}: {criterion}",
            "confidence": 0.8,
            "criterion": criterion,
            "weight": weight,
            "evidence_urls": evidence_urls[:5],
            "ttl": timedelta(days=30),
            "created_at": datetime.now().isoformat()
        }
        claims.append(claim)
    
    capsule = {
        "capsule_id": capsule_id,
        "phase": "intelligence_gathering",
        "product": product,
        "timestamp": datetime.now().isoformat(),
        "claims": claims,
        "intelligence": intelligence,
        "ready_for_phase2": len(intelligence.get("vendors", [])) >= 3,
        "vendor_count": len(intelligence.get("vendors", [])),
        "top_vendors": [v["name"] for v in intelligence.get("vendors", [])[:10]]
    }
    
    logger.info(
        f"[CM Phase1] Created capsule {capsule_id} with {len(claims)} claims "
        f"for product '{product}'"
    )
    
    return capsule


def process_phase2_products(
    product: str,
    products: List[Dict],
    phase1_capsule: Dict,
    evidence_urls: List[str]
) -> Dict:
    """
    Process Phase 2 product search results with Phase 1 context.
    
    Creates product listing claims linked to Phase 1 vendor/spec claims.
    
    Args:
        product: Product being searched
        products: Extracted product listings
        phase1_capsule: Phase 1 capsule with intelligence
        evidence_urls: URLs that provided evidence
        
    Returns:
        Phase 2 capsule with product claims linked to Phase 1
    """
    import uuid
    from datetime import datetime, timedelta
    
    capsule_id = f"cap_phase2_{uuid.uuid4().hex[:8]}"
    phase1_claims = {c["claim_id"]: c for c in phase1_capsule.get("claims", [])}
    
    product_claims = []
    claim_links = []
    
    for product_item in products[:20]:  # Limit to top 20
        claim_id = f"claim_product_{uuid.uuid4().hex[:6]}"
        
        # Build claim text
        title = product_item.get("title", "Unknown product")
        price = product_item.get("price")
        vendor = product_item.get("vendor", "Unknown vendor")
        
        claim_text = f"{vendor} sells {product}: {title}"
        if price:
            currency = product_item.get("currency", "USD")
            claim_text += f" for {currency} {price}"
        
        # Find linked claims from Phase 1
        linked_claim_ids = []
        
        # Link to vendor claim
        for vid, vclaim in phase1_claims.items():
            if vclaim["type"] == "vendor_recommendation":
                vendor_name = vclaim.get("vendor_data", {}).get("name", "")
                if vendor_name.lower() in vendor.lower() or vendor.lower() in vendor_name.lower():
                    linked_claim_ids.append(vid)
                    claim_links.append({
                        "source": claim_id,
                        "target": vid,
                        "link_type": "vendor_match",
                        "strength": 1.0
                    })
                    break
        
        # Link to spec claims (if product has specs)
        spec_matches = product_item.get("spec_matches", {})
        for spec_name, spec_match in spec_matches.items():
            for sid, sclaim in phase1_claims.items():
                if sclaim["type"] == "spec_requirement" and sclaim.get("spec_name") == spec_name:
                    linked_claim_ids.append(sid)
                    claim_links.append({
                        "source": claim_id,
                        "target": sid,
                        "link_type": "spec_compliance",
                        "strength": spec_match.get("score", 0.5)
                    })
                    break
        
        # Create product claim
        claim = {
            "claim_id": claim_id,
            "type": "product_listing",
            "claim": claim_text,
            "confidence": product_item.get("quality_score", 0.7),
            "product_data": product_item,
            "linked_claims": linked_claim_ids,
            "spec_compliance": spec_matches,
            "quality_score": product_item.get("quality_score", 0.5),
            "meets_all_requirements": all(
                m.get("match", False) for m in spec_matches.values()
            ) if spec_matches else False,
            "evidence_urls": [product_item.get("url", "")],
            "ttl": timedelta(days=1),  # Products expire quickly
            "created_at": datetime.now().isoformat()
        }
        
        product_claims.append(claim)
    
    # Rank products by quality score
    product_rankings = sorted(
        [
            {
                "rank": i + 1,
                "claim_id": c["claim_id"],
                "product_title": c["product_data"].get("title", ""),
                "quality_score": c["quality_score"],
                "meets_requirements": c["meets_all_requirements"]
            }
            for i, c in enumerate(sorted(product_claims, key=lambda x: x["quality_score"], reverse=True))
        ],
        key=lambda x: x["rank"]
    )
    
    capsule = {
        "capsule_id": capsule_id,
        "phase": "spec_matching_pricing",
        "product": product,
        "linked_to_phase1": phase1_capsule["capsule_id"],
        "timestamp": datetime.now().isoformat(),
        "claims": product_claims,
        "claim_links": claim_links,
        "product_rankings": product_rankings,
        "total_products": len(products),
        "top_products": product_rankings[:5]
    }
    
    logger.info(
        f"[CM Phase2] Created capsule {capsule_id} with {len(product_claims)} product claims "
        f"linked to Phase 1 capsule {phase1_capsule['capsule_id']}"
    )
    
    return capsule


def build_synthesis_package(
    phase1_capsule: Dict,
    phase2_capsule: Dict
) -> Dict:
    """
    Build synthesis package for Guide from Phase 1 + Phase 2 capsules.
    
    Combines intelligence and products into a unified structure
    for natural language synthesis.
    
    Args:
        phase1_capsule: Phase 1 intelligence capsule
        phase2_capsule: Phase 2 product capsule
        
    Returns:
        Synthesis package with cross-phase analysis
    """
    intelligence = phase1_capsule.get("intelligence", {})
    product_rankings = phase2_capsule.get("product_rankings", [])
    product_claims = {c["claim_id"]: c for c in phase2_capsule.get("claims", [])}
    
    # Extract recommended vendors from Phase 1
    recommended_vendors = []
    for claim in phase1_capsule.get("claims", []):
        if claim["type"] == "vendor_recommendation":
            vendor_data = claim.get("vendor_data", {})
            
            # Check if vendor has products in Phase 2
            vendor_name = vendor_data.get("name", "")
            has_products = False
            product_count = 0
            
            for pclaim in phase2_capsule.get("claims", []):
                if vendor_name.lower() in pclaim.get("product_data", {}).get("vendor", "").lower():
                    has_products = True
                    product_count += 1
            
            recommended_vendors.append({
                "name": vendor_name,
                "type": vendor_data.get("type", "unknown"),
                "confidence": claim["confidence"],
                "quality_signals": vendor_data.get("quality_signals", []),
                "has_products": has_products,
                "product_count": product_count
            })
    
    # Build product list with Phase 1 context
    products_with_context = []
    for ranking in product_rankings[:10]:
        claim_id = ranking["claim_id"]
        pclaim = product_claims.get(claim_id)
        if not pclaim:
            continue
        
        product_data = pclaim["product_data"]
        
        # Find vendor from Phase 1
        from_recommended_vendor = False
        vendor_quality = "unknown"
        
        for vclaim in phase1_capsule.get("claims", []):
            if vclaim["type"] == "vendor_recommendation":
                vname = vclaim.get("vendor_data", {}).get("name", "")
                if vname.lower() in product_data.get("vendor", "").lower():
                    from_recommended_vendor = True
                    vendor_quality = "recommended"
                    break
        
        products_with_context.append({
            "title": product_data.get("title", ""),
            "vendor": product_data.get("vendor", ""),
            "price": product_data.get("price"),
            "currency": product_data.get("currency", "USD"),
            "url": product_data.get("url", ""),
            "quality_score": pclaim["quality_score"],
            "from_recommended_vendor": from_recommended_vendor,
            "vendor_quality": vendor_quality,
            "meets_all_specs": pclaim["meets_all_requirements"],
            "spec_compliance": pclaim.get("spec_compliance", {}),
            "availability": product_data.get("availability", "unknown"),
            "why_recommended": _build_recommendation_reasoning(pclaim, phase1_capsule),
            "warnings": _extract_warnings(pclaim, phase1_capsule)
        })
    
    # Identify best options
    best_option = products_with_context[0] if products_with_context else None
    budget_option = None
    
    # Find cheapest option that meets basic requirements
    for p in sorted(products_with_context, key=lambda x: x.get("price") or 999999):
        if p.get("price") and p["quality_score"] >= 0.5:
            budget_option = p
            break
    
    synthesis = {
        "phase1": {
            "capsule_id": phase1_capsule["capsule_id"],
            "intelligence": {
                "community_recommendations": intelligence.get("community_wisdom", []),
                "quality_criteria": intelligence.get("quality_criteria", {}),
                "recommended_vendors": recommended_vendors,
                "price_expectations": intelligence.get("price_intelligence", {}),
                "spec_requirements": intelligence.get("specs_required", {})
            }
        },
        "phase2": {
            "capsule_id": phase2_capsule["capsule_id"],
            "products": products_with_context
        },
        "analysis": {
            "best_option": best_option,
            "budget_option": budget_option,
            "vendor_performance": {
                "recommended_vendors_with_products": sum(
                    1 for v in recommended_vendors if v["has_products"]
                ),
                "total_products_found": len(products_with_context)
            },
            "quality_summary": {
                "high_quality_options": sum(1 for p in products_with_context if p["quality_score"] >= 0.8),
                "from_recommended_sources": sum(1 for p in products_with_context if p["from_recommended_vendor"])
            }
        }
    }
    
    logger.info(
        f"[CM Synthesis] Built synthesis package: "
        f"{len(products_with_context)} products, "
        f"{len(recommended_vendors)} recommended vendors"
    )
    
    return synthesis


def _build_recommendation_reasoning(product_claim: Dict, phase1_capsule: Dict) -> str:
    """Build reasoning text for why product is recommended"""
    reasons = []
    
    if product_claim["meets_all_requirements"]:
        reasons.append("Meets all spec requirements")
    
    # Check vendor quality
    for vclaim in phase1_capsule.get("claims", []):
        if vclaim["type"] == "vendor_recommendation":
            vname = vclaim.get("vendor_data", {}).get("name", "")
            pvendor = product_claim.get("product_data", {}).get("vendor", "")
            if vname.lower() in pvendor.lower():
                quality_signals = vclaim.get("vendor_data", {}).get("quality_signals", [])
                if quality_signals:
                    reasons.append(f"From {', '.join(quality_signals[:2])}")
                break
    
    if product_claim["quality_score"] >= 0.9:
        reasons.append("High quality score")
    
    return "; ".join(reasons) if reasons else "Available option"


def _extract_warnings(product_claim: Dict, phase1_capsule: Dict) -> List[str]:
    """Extract warnings for product based on Phase 1 intelligence"""
    warnings = []
    
    spec_compliance = product_claim.get("spec_compliance", {})
    for spec_name, spec_match in spec_compliance.items():
        if not spec_match.get("match"):
            if spec_match.get("actual") == "unknown":
                warnings.append(f"{spec_name.title()} not specified - verify before purchase")
            else:
                warnings.append(f"Does not meet {spec_name} requirement")
    
    price = product_claim.get("product_data", {}).get("price")
    if price:
        price_intel = phase1_capsule.get("intelligence", {}).get("price_intelligence", {})
        too_cheap = price_intel.get("too_cheap_warning")
        if too_cheap and price < too_cheap:
            warnings.append(f"Price unusually low (< ${too_cheap}) - verify quality")
    
    return warnings


def cache_phase1_intelligence(
    session_id: str,
    product: str,
    phase1_capsule: Dict,
    ttl_days: int = 7
):
    """
    Cache Phase 1 intelligence for future quick searches.
    
    Args:
        session_id: Session identifier
        product: Product name (normalized)
        phase1_capsule: Phase 1 capsule to cache
        ttl_days: Time to live in days
    """
    from pathlib import Path
    import json
    from datetime import datetime, timedelta
    
    cache_dir = Path("panda_system_docs/shared_state/commerce_cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    # Normalize product name for cache key
    product_key = product.lower().replace(" ", "_")
    cache_file = cache_dir / f"{session_id}_{product_key}.json"
    
    cache_data = {
        "session_id": session_id,
        "product": product,
        "phase1_capsule_id": phase1_capsule["capsule_id"],
        "intelligence": phase1_capsule["intelligence"],
        "cached_at": datetime.now().isoformat(),
        "expires_at": (datetime.now() + timedelta(days=ttl_days)).isoformat(),
        "ttl_days": ttl_days
    }
    
    cache_file.write_text(json.dumps(cache_data, indent=2))
    logger.info(f"[CM Cache] Cached Phase 1 intelligence for '{product}' in session {session_id}")


def get_cached_phase1_intelligence(
    session_id: str,
    product: str
) -> Optional[Dict]:
    """
    Retrieve cached Phase 1 intelligence.
    
    Args:
        session_id: Session identifier
        product: Product name (normalized)
        
    Returns:
        Cached intelligence dict or None if not found/expired
    """
    from pathlib import Path
    import json
    from datetime import datetime
    
    cache_dir = Path("panda_system_docs/shared_state/commerce_cache")
    product_key = product.lower().replace(" ", "_")
    cache_file = cache_dir / f"{session_id}_{product_key}.json"
    
    if not cache_file.exists():
        return None
    
    try:
        cache_data = json.loads(cache_file.read_text())
        
        # Check expiry
        expires_at = datetime.fromisoformat(cache_data["expires_at"])
        if datetime.now() > expires_at:
            logger.info(f"[CM Cache] Cached intelligence for '{product}' expired")
            cache_file.unlink()  # Delete expired cache
            return None
        
        logger.info(f"[CM Cache] Retrieved cached intelligence for '{product}' from session {session_id}")
        return cache_data.get("intelligence")
        
    except Exception as e:
        logger.error(f"[CM Cache] Error reading cache: {e}")
        return None


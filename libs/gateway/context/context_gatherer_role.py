"""
DEPRECATED: Use ContextGatherer2Phase instead.

This module is kept for backwards compatibility with test scripts but is no longer
used in production. The unified_flow.py now uses ContextGatherer2Phase exclusively
(22% token reduction, 50% fewer LLM calls).

See: libs/gateway/context_gatherer_2phase.py

---
Original docstring:

Context Gatherer Role: Searches and retrieves relevant context from prior turns.

This role replaces the Context Builder. Key differences:
- Searches ALL prior turn documents (not just last turn summary)
- Searches research documents by topic (not just exact query match)
- Summarizes at retrieval time (not at save time)
- Outputs to context.md §1 (Gathered Context)
- Includes source references for provenance

The Context Gatherer answers: "What context does this query need?"
"""

from pathlib import Path
from typing import Optional, Dict, List, Any
import logging
import json

from .context_document import ContextDocument
from .turn_search_index import TurnSearchIndex, SearchResult
from .research_index_db import get_research_index_db, SearchResult as ResearchSearchResult

logger = logging.getLogger(__name__)


class ContextGathererRole:
    """
    Searches and retrieves relevant context for the current query.

    Usage:
        gatherer = ContextGathererRole(session_id="default")
        context_doc = gatherer.gather(query="What's my current project status?", turn_number=743)
        # context_doc now has §0 (query) and §1 (gathered context)
    """

    def __init__(
        self,
        session_id: str,
        turns_dir: Path = None,
        sessions_dir: Path = None,
        memory_dir: Path = None,
        llm_client: Any = None  # For LLM-driven summarization
    ):
        self.session_id = session_id
        self.turns_dir = turns_dir or Path("panda_system_docs/turns")
        self.sessions_dir = sessions_dir or Path("panda_system_docs/sessions")
        self.memory_dir = memory_dir or Path("panda_system_docs/memory")
        self.llm_client = llm_client

        self.search_index = TurnSearchIndex(
            session_id=session_id,
            turns_dir=self.turns_dir,
            sessions_dir=self.sessions_dir,
            memory_dir=self.memory_dir
        )

        # Research index for topic-based retrieval
        self.research_index = get_research_index_db()

        # Knowledge retriever for claim-based retrieval (Phase 1/2 intelligence)
        self._knowledge_retriever = None

    @property
    def knowledge_retriever(self):
        """Lazy-load knowledge retriever."""
        if self._knowledge_retriever is None:
            try:
                from apps.services.tool_server.knowledge_retriever import get_knowledge_retriever
                self._knowledge_retriever = get_knowledge_retriever(self.session_id)
            except Exception as e:
                logger.warning(f"[ContextGatherer] Failed to load knowledge retriever: {e}")
                self._knowledge_retriever = None
        return self._knowledge_retriever

    def gather(
        self,
        query: str,
        turn_number: int,
        max_prior_turns: int = 5,
        max_memory_results: int = 3,
        max_research_results: int = 3,
        intent: str = None
    ) -> ContextDocument:
        """
        Gather context for a query and create the initial ContextDocument.

        Args:
            query: The user's query
            turn_number: Current turn number
            max_prior_turns: Maximum prior turns to include
            max_memory_results: Maximum memory results to include
            max_research_results: Maximum research documents to include
            intent: Query intent (transactional, informational) for research filtering

        Returns:
            ContextDocument with §0 (query) and §1 (gathered context)
        """
        # Create document with §0 (query)
        context_doc = ContextDocument(
            turn_number=turn_number,
            session_id=self.session_id,
            query=query
        )

        # Gather context components - load preferences FIRST
        preferences = self._load_preferences()
        facts = self._load_facts()
        prior_turns = self._search_prior_turns(query, limit=max_prior_turns)
        memory_results = self._search_memory(query, limit=max_memory_results)

        # NEW: Always load immediate previous turn for conversation continuity
        # This ensures follow-up questions have context even without keyword match
        # Pass current query for intelligent link tracing
        previous_turn_context = self._load_immediate_previous_turn(turn_number, current_query=query)

        # Search for relevant research documents by topic
        # Pass preferences so topic inference can resolve pronouns
        research_results = self._search_research(
            query=query,
            intent=intent,
            limit=max_research_results,
            preferences=preferences  # NEW: Pass preferences for topic resolution
        )

        # NEW: Retrieve cached knowledge (claims/topics) for research intelligence
        knowledge_context = self._retrieve_knowledge(query)

        # Build §1 content
        section_content = self._build_gathered_context_section(
            preferences=preferences,
            facts=facts,
            prior_turns=prior_turns,
            memory_results=memory_results,
            research_results=research_results,
            knowledge_context=knowledge_context,  # NEW: Include knowledge
            previous_turn_context=previous_turn_context  # NEW: Conversation context
        )

        # Append §2
        context_doc.append_section(2, "Gathered Context", section_content)

        # NEW: Store knowledge context in document metadata for downstream use
        if knowledge_context:
            context_doc.metadata["knowledge_context"] = knowledge_context

        # Add source references for prior turns
        for result in prior_turns:
            context_doc.add_source_reference(
                path=result.document_path,
                summary=result.snippet[:100],
                relevance=result.relevance_score
            )

        # Add source references for research documents
        for result in research_results:
            context_doc.add_source_reference(
                path=result.entry.doc_path,
                summary=f"Research: {result.entry.primary_topic}",
                relevance=result.score
            )

        return context_doc

    def gather_more(
        self,
        context_doc: ContextDocument,
        refined_query: str,
        max_additional_turns: int = 3,
        max_additional_research: int = 2
    ) -> ContextDocument:
        """
        Gather additional context based on a refined search query.

        Called when Reflection returns GATHER_MORE.

        This preserves the original document and extends §1 with new results,
        maintaining all source_references and claims from the original document.

        Searches BOTH prior turns AND research documents.

        Args:
            context_doc: Current context document
            refined_query: Refined search query from Reflection
            max_additional_turns: Maximum additional turns to search
            max_additional_research: Maximum additional research docs to search

        Returns:
            Updated ContextDocument with additional context appended to §1
        """
        new_content = ""
        found_anything = False

        # Load preferences for topic inference
        preferences = self._load_preferences()

        # Search research documents first (more valuable for follow-up)
        additional_research = self._search_research(
            query=refined_query,
            limit=max_additional_research,
            preferences=preferences
        )

        if additional_research:
            found_anything = True
            new_content += "### Additional Research (Refined Search)\n\n"
            new_content += f"*Searched for: \"{refined_query}\"*\n\n"

            for result in additional_research:
                entry = result.entry
                new_content += f"#### Topic: {entry.primary_topic}\n"
                new_content += f"*Score: {result.score:.2f}, Quality: {entry.overall_quality:.2f}, Age: {entry.age_hours:.1f}h*\n\n"

                # Load and include content
                content = self._load_research_content(entry.doc_path)
                if content:
                    new_content += content + "\n\n"
                else:
                    new_content += f"- Keywords: {', '.join(entry.keywords[:5])}\n"
                    new_content += f"- Intent: {entry.intent}\n\n"

                # Add source reference
                context_doc.add_source_reference(
                    path=entry.doc_path,
                    summary=f"Research: {entry.primary_topic}",
                    relevance=result.score
                )

        # Search prior turns
        additional_turns = self._search_prior_turns(
            refined_query,
            limit=max_additional_turns
        )

        if additional_turns:
            found_anything = True
            new_content += "### Additional Turns (Refined Search)\n\n"
            new_content += f"*Searched for: \"{refined_query}\"*\n\n"

            for result in additional_turns:
                new_content += f"**Turn {result.turn_number}** (relevance: {result.relevance_score:.2f}):\n"
                new_content += f"{result.snippet}\n\n"

                # Add source reference
                context_doc.add_source_reference(
                    path=result.document_path,
                    summary=result.snippet[:100],
                    relevance=result.relevance_score
                )

        if not found_anything:
            logger.info(f"[ContextGatherer] gather_more found no additional context for: {refined_query}")
            return context_doc

        # Use extend_section to append to §1 (preserves existing content and provenance)
        context_doc.extend_section(1, new_content)

        logger.info(
            f"[ContextGatherer] gather_more added {len(additional_research)} research docs, "
            f"{len(additional_turns)} turns for: {refined_query}"
        )

        return context_doc

    def _load_preferences(self) -> Dict[str, str]:
        """Load user preferences from session directory."""
        return self.search_index.search_preferences()

    def _load_facts(self) -> List[str]:
        """Load user facts from session directory."""
        return self.search_index.search_facts()

    def _load_immediate_previous_turn(
        self,
        turn_number: int,
        current_query: str = ""
    ) -> Optional[Dict[str, Any]]:
        """
        Load the immediate previous turn's context and trace source references.

        This is the intelligent context gathering approach:
        1. Load previous turn's context.md
        2. Parse source references to find linked documents
        3. Evaluate which sources are relevant to current query
        4. Follow relevant links and extract needed information

        Args:
            turn_number: Current turn number
            current_query: Current user query (for relevance filtering)

        Returns:
            Dict with 'query', 'response', 'knowledge', 'findings', 'traced_sources'
        """
        if turn_number <= 1:
            return None

        prev_turn_num = turn_number - 1
        prev_turn_dir = self.turns_dir / f"turn_{prev_turn_num:06d}"

        if not prev_turn_dir.exists():
            logger.debug(f"[ContextGatherer] Previous turn directory not found: {prev_turn_dir}")
            return None

        result = {}

        # 1. Load and parse previous context.md
        context_path = prev_turn_dir / "context.md"
        prev_context_content = ""
        source_references = []

        if context_path.exists():
            try:
                prev_context_content = context_path.read_text()

                # Extract query from §0 section
                if "## 0. User Query" in prev_context_content:
                    query_section = prev_context_content.split("## 0. User Query")[1]
                    if "---" in query_section:
                        query_section = query_section.split("---")[0]
                    query_text = query_section.strip()
                    if query_text:
                        result['query'] = query_text[:500]

                # Parse source references section
                source_references = self._parse_source_references(prev_context_content)
                logger.info(f"[ContextGatherer] Found {len(source_references)} source references in previous context")

            except Exception as e:
                logger.debug(f"[ContextGatherer] Failed to load previous context: {e}")

        # 2. Load previous response
        response_path = prev_turn_dir / "response.md"
        if response_path.exists():
            try:
                response_text = response_path.read_text().strip()
                if response_text:
                    result['response'] = response_text[:1500]
                    if len(response_text) > 1500:
                        result['response'] += "\n...[truncated]"
            except Exception as e:
                logger.debug(f"[ContextGatherer] Failed to load previous response: {e}")

        # 3. Trace relevant source references based on current query
        traced_content = self._trace_relevant_sources(
            source_references=source_references,
            current_query=current_query,
            prev_turn_dir=prev_turn_dir
        )

        if traced_content.get('knowledge'):
            result['knowledge'] = traced_content['knowledge']
        if traced_content.get('findings'):
            result['findings'] = traced_content['findings']
        if traced_content.get('traced_sources'):
            result['traced_sources'] = traced_content['traced_sources']

        if result:
            logger.info(f"[ContextGatherer] Loaded previous turn {prev_turn_num} with {len(traced_content.get('traced_sources', []))} traced sources")
            return result

        return None

    def _parse_source_references(self, context_content: str) -> List[Dict[str, str]]:
        """
        Parse the Source References section from context.md.

        Returns list of {'path': '...', 'summary': '...', 'type': 'research|memory|turn'}
        """
        references = []

        if "### Source References" not in context_content:
            return references

        try:
            ref_section = context_content.split("### Source References")[1]
            # Stop at next section or end
            if "\n## " in ref_section:
                ref_section = ref_section.split("\n## ")[0]

            for line in ref_section.split("\n"):
                line = line.strip()
                if line.startswith("- [") and "]" in line:
                    # Parse: - [1] path/to/file - "summary..."
                    parts = line.split("] ", 1)
                    if len(parts) >= 2:
                        rest = parts[1]
                        if " - " in rest:
                            path, summary = rest.split(" - ", 1)
                            path = path.strip()
                            summary = summary.strip().strip('"')

                            # Determine type
                            ref_type = "unknown"
                            if "research.md" in path:
                                ref_type = "research"
                            elif "toolresults.md" in path:
                                ref_type = "toolresults"
                            elif "memory" in path:
                                ref_type = "memory"
                            elif "context.md" in path:
                                ref_type = "context"

                            references.append({
                                'path': path,
                                'summary': summary[:200],
                                'type': ref_type
                            })

        except Exception as e:
            logger.debug(f"[ContextGatherer] Failed to parse source references: {e}")

        return references

    def _trace_relevant_sources(
        self,
        source_references: List[Dict[str, str]],
        current_query: str,
        prev_turn_dir: Path
    ) -> Dict[str, Any]:
        """
        Trace source references and extract relevant content.

        Evaluates each source reference for relevance to current query,
        then follows links to extract needed information.
        """
        result = {
            'knowledge': {},
            'findings': {'products': []},
            'traced_sources': []
        }

        # Extract keywords from current query for relevance matching
        query_keywords = set(current_query.lower().split())
        # Add common product/tech keywords that indicate need for research data
        tech_keywords = {'gpu', 'cpu', 'ram', 'price', 'compare', 'vs', 'better', 'best',
                        'cheap', 'budget', '4050', '4060', '4070', '4080', 'rtx', 'nvidia',
                        'laptop', 'computer', 'buy', 'should', 'recommend'}

        needs_research = bool(query_keywords & tech_keywords)

        # Always load research.md and toolresults.md from previous turn if they exist
        # (these are most likely to have relevant product/comparison data)
        research_path = prev_turn_dir / "research.md"
        if research_path.exists():
            try:
                research_content = research_path.read_text()
                knowledge = self._extract_research_knowledge(research_content)
                if knowledge:
                    result['knowledge'] = knowledge
                    result['traced_sources'].append({
                        'path': str(research_path),
                        'type': 'research',
                        'reason': 'Previous turn research data'
                    })
                    logger.info(f"[ContextGatherer] Traced research.md: {len(knowledge)} sections")
            except Exception as e:
                logger.debug(f"[ContextGatherer] Failed to trace research.md: {e}")

        toolresults_path = prev_turn_dir / "toolresults.md"
        if toolresults_path.exists():
            try:
                toolresults_content = toolresults_path.read_text()
                findings = self._extract_product_findings(toolresults_content)
                if findings.get('products'):
                    result['findings'] = findings
                    result['traced_sources'].append({
                        'path': str(toolresults_path),
                        'type': 'toolresults',
                        'reason': 'Previous turn product findings'
                    })
                    logger.info(f"[ContextGatherer] Traced toolresults.md: {len(findings.get('products', []))} products")
            except Exception as e:
                logger.debug(f"[ContextGatherer] Failed to trace toolresults.md: {e}")

        # Trace additional source references if query needs more context
        if needs_research and source_references:
            for ref in source_references[:5]:  # Limit to 5 additional sources
                ref_path = ref.get('path', '')
                ref_type = ref.get('type', '')
                ref_summary = ref.get('summary', '').lower()

                # Check if this source is relevant to current query
                is_relevant = False
                for kw in query_keywords:
                    if kw in ref_summary or kw in ref_path.lower():
                        is_relevant = True
                        break

                if is_relevant and ref_type == 'research':
                    # Follow link to research document
                    full_path = Path(ref_path)
                    if full_path.exists():
                        try:
                            content = full_path.read_text()
                            extra_knowledge = self._extract_research_knowledge(content)
                            if extra_knowledge:
                                # Merge with existing knowledge
                                for key, value in extra_knowledge.items():
                                    if key not in result['knowledge']:
                                        result['knowledge'][key] = value
                                result['traced_sources'].append({
                                    'path': ref_path,
                                    'type': 'research',
                                    'reason': f'Relevant to: {ref_summary[:50]}'
                                })
                        except Exception as e:
                            logger.debug(f"[ContextGatherer] Failed to trace {ref_path}: {e}")

        return result

    def _extract_research_knowledge(self, research_content: str) -> Dict[str, Any]:
        """
        Extract knowledge sections from research.md.

        Pulls out:
        - Expert recommendations
        - Forum tips
        - Specs discovered
        - Reputable sources
        """
        knowledge = {}

        # Extract Evergreen Knowledge section
        if "## Evergreen Knowledge" in research_content:
            evergreen_section = research_content.split("## Evergreen Knowledge")[1]
            if "## Time-Sensitive" in evergreen_section:
                evergreen_section = evergreen_section.split("## Time-Sensitive")[0]

            # Extract reputable sources
            if "### Reputable Sources" in evergreen_section:
                sources_section = evergreen_section.split("### Reputable Sources")[1]
                if "###" in sources_section:
                    sources_section = sources_section.split("###")[0]
                knowledge['reputable_sources'] = sources_section.strip()[:500]

            # Extract community tips
            if "### Community Tips" in evergreen_section:
                tips_section = evergreen_section.split("### Community Tips")[1]
                if "###" in tips_section or "---" in tips_section:
                    tips_section = tips_section.split("###")[0].split("---")[0]
                tips = [line.strip("- ").strip() for line in tips_section.strip().split("\n") if line.strip().startswith("-")]
                knowledge['community_tips'] = tips[:10]

        # Extract Current Listings summary (first 5 products)
        if "### Current Listings" in research_content:
            listings_section = research_content.split("### Current Listings")[1]
            if "### Listing Details" in listings_section:
                listings_section = listings_section.split("### Listing Details")[0]
            knowledge['current_listings'] = listings_section.strip()[:1500]

        # Extract topic and intent
        if "### Topic Classification" in research_content:
            topic_section = research_content.split("### Topic Classification")[1]
            if "###" in topic_section:
                topic_section = topic_section.split("###")[0]
            for line in topic_section.split("\n"):
                if "Primary Topic:" in line:
                    knowledge['topic'] = line.split("Primary Topic:")[1].strip().strip("*")
                if "Intent:" in line:
                    knowledge['intent'] = line.split("Intent:")[1].strip().strip("*")

        return knowledge

    def _extract_product_findings(self, toolresults_content: str) -> Dict[str, Any]:
        """
        Extract product findings from toolresults.md.

        Pulls out structured product data for comparison.
        """
        findings = {'products': []}

        try:
            # Try to parse JSON from toolresults if available
            if '"findings":' in toolresults_content:
                import json
                import re

                # Find the findings array in the JSON
                json_match = re.search(r'"findings":\s*\[(.*?)\]', toolresults_content, re.DOTALL)
                if json_match:
                    # This is tricky - try to extract individual product objects
                    findings_text = json_match.group(0)

                    # Find each product object
                    product_matches = re.findall(
                        r'\{\s*"name":\s*"([^"]+)"[^}]*"price":\s*"([^"]+)"[^}]*"vendor":\s*"([^"]+)"',
                        toolresults_content
                    )

                    for name, price, vendor in product_matches[:10]:  # Limit to 10
                        findings['products'].append({
                            'name': name[:100],
                            'price': price,
                            'vendor': vendor
                        })

        except Exception as e:
            logger.debug(f"[ContextGatherer] JSON extraction failed, trying text: {e}")

        # Fallback: extract from markdown table if present
        if not findings['products'] and "| Product |" in toolresults_content:
            lines = toolresults_content.split("\n")
            for line in lines:
                if line.startswith("|") and "$" in line:
                    parts = [p.strip() for p in line.split("|") if p.strip()]
                    if len(parts) >= 3:
                        findings['products'].append({
                            'name': parts[0][:100],
                            'price': parts[1] if "$" in parts[1] else parts[2],
                            'vendor': parts[2] if len(parts) > 2 else ''
                        })

        return findings

    def _search_prior_turns(self, query: str, limit: int) -> List[SearchResult]:
        """Search prior turns for relevant context."""
        return self.search_index.search(query, limit=limit)

    def _search_memory(self, query: str, limit: int) -> List[SearchResult]:
        """Search long-term memory for relevant context."""
        return self.search_index.search_memory(query, limit=limit)

    def _search_research(
        self,
        query: str,
        intent: Optional[str] = None,
        limit: int = 3,
        preferences: Optional[Dict[str, str]] = None
    ) -> List[ResearchSearchResult]:
        """
        Search research documents by topic.

        This enables topic-based retrieval where related queries can benefit
        from prior research (e.g., "hamster care" finds research from "buy hamster").

        Args:
            query: User's query
            intent: Query intent for filtering
            limit: Max results
            preferences: User preferences for topic resolution (e.g., favorite_hamster: Syrian)
        """
        # Infer topic from query AND preferences
        topic = self._infer_topic_from_query(query, preferences)

        if not topic:
            logger.info(f"[ContextGatherer] Could not infer topic from query: {query}")
            return []

        logger.info(f"[ContextGatherer] Inferred topic: {topic} (from query + preferences)")

        try:
            # Search by topic
            results = self.research_index.search(
                topic=topic,
                intent=intent,
                session_id=self.session_id,
                limit=limit
            )

            # Also search by keywords as fallback
            # BUT only use query keywords, not preference values
            # (preference values are only for resolving vague pronouns, not for search)
            if len(results) < limit:
                keywords = self._extract_keywords(query)
                # Only add preference values if query has vague references
                # (e.g., "find some for sale" needs preferences to know what "some" means)
                vague_words = ["some", "them", "it", "those", "these", "any", "one", "ones"]
                has_vague_reference = any(word in query.lower().split() for word in vague_words)

                if has_vague_reference and preferences:
                    for value in preferences.values():
                        if value and len(value) > 2:
                            keywords.append(value.lower())

                keyword_results = self.research_index.search_by_keywords(
                    keywords=keywords,
                    session_id=self.session_id,
                    limit=limit - len(results)
                )

                # Merge, avoiding duplicates
                seen_ids = {r.entry.id for r in results}
                for kr in keyword_results:
                    if kr.entry.id not in seen_ids:
                        results.append(kr)
                        seen_ids.add(kr.entry.id)

            # Increment usage count for found research
            for result in results:
                self.research_index.increment_usage(result.entry.id)

                # Check for promotion
                new_scope = self.research_index.check_promotion(result.entry.id)
                if new_scope and new_scope != result.entry.scope:
                    self.research_index.promote(result.entry.id, new_scope)

            logger.info(
                f"[ContextGatherer] Found {len(results)} research documents "
                f"for topic={topic}, intent={intent}"
            )

            return results

        except Exception as e:
            logger.warning(f"[ContextGatherer] Research search failed: {e}")
            return []

    def _infer_topic_from_query(
        self,
        query: str,
        preferences: Optional[Dict[str, str]] = None
    ) -> Optional[str]:
        """
        Infer topic classification from query AND preferences.

        DESIGN PRINCIPLE: This method extracts topics without hardcoded product patterns.
        Complex topic classification (e.g., distinguishing "Syrian hamster" from "dwarf hamster")
        should be handled by LLM prompts in upstream components.

        Priority:
        1. Extract meaningful words from query
        2. Use preferences to resolve vague references (e.g., "some", "them")
        3. Build topic hierarchy from extracted words

        Args:
            query: User's query
            preferences: User preferences that may hint at topic
        """
        query_lower = query.lower()
        preferences = preferences or {}

        # Stop words to filter out
        stop_words = {
            "find", "me", "some", "for", "sale", "online", "please", "can", "you",
            "the", "a", "an", "what", "where", "how", "them", "it", "those",
            "these", "any", "one", "to", "buy", "get", "show", "best", "cheapest"
        }

        # Extract meaningful words from query
        words = [w.strip("?,.'\"!") for w in query_lower.split()]
        meaningful_words = [w for w in words if len(w) > 2 and w not in stop_words]

        # Check for vague references that preferences can resolve
        vague_words = {"some", "them", "it", "those", "these", "any", "one"}
        has_vague_reference = any(word in query_lower.split() for word in vague_words)

        if has_vague_reference and not meaningful_words and preferences:
            # Query is vague, try to use preferences
            for key, value in preferences.items():
                if value and len(value) > 2:
                    # Use preference value as topic hint
                    return f"preference.{value.lower().replace(' ', '_')}"

        # Build topic from meaningful words
        if meaningful_words:
            primary = meaningful_words[0]
            if len(meaningful_words) > 1:
                secondary = meaningful_words[1]
                return f"general.{primary}.{secondary}"
            return f"general.{primary}"

        return None

    def _extract_keywords(self, query: str) -> List[str]:
        """Extract search keywords from query."""
        stop_words = {"find", "me", "some", "for", "sale", "online", "please",
                      "can", "you", "the", "a", "an", "what", "where", "how",
                      "is", "are", "do", "does", "about", "tell"}
        keywords = []
        for word in query.lower().split():
            word = word.strip("?,.")
            if len(word) > 2 and word not in stop_words:
                keywords.append(word)
        return keywords

    def _load_research_content(self, doc_path: str) -> Optional[str]:
        """Load evergreen summary from a research document."""
        try:
            path = Path(doc_path)
            if not path.exists():
                # Try JSON version
                json_path = path.with_suffix('.json')
                if json_path.exists():
                    data = json.loads(json_path.read_text())
                    # Build summary from JSON
                    lines = []
                    if data.get("general_facts"):
                        lines.append("**Key Facts:**")
                        for fact in data["general_facts"][:3]:
                            lines.append(f"- {fact}")
                    if data.get("vendors"):
                        lines.append("**Known Sources:**")
                        for v in data["vendors"][:3]:
                            lines.append(f"- {v['name']} ({v.get('source_type', 'unknown')})")
                    return "\n".join(lines) if lines else None

            # Read markdown and extract evergreen section
            content = path.read_text()

            # Find evergreen section
            if "## Evergreen Knowledge" in content:
                start = content.find("## Evergreen Knowledge")
                end = content.find("## Time-Sensitive Data", start)
                if end == -1:
                    end = content.find("---", start + 1)
                if end == -1:
                    end = len(content)

                evergreen = content[start:end].strip()
                # Limit length
                if len(evergreen) > 1000:
                    evergreen = evergreen[:1000] + "\n...(truncated)"
                return evergreen

            return None

        except Exception as e:
            logger.warning(f"[ContextGatherer] Failed to load research content: {e}")
            return None

    def _retrieve_knowledge(self, query: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve cached knowledge (claims/topics) for the query.

        This integrates the Knowledge Retriever system which provides:
        - Topic matching via semantic similarity
        - Cached claims (retailers, specs, prices, tips)
        - Phase 1 skip recommendation

        Returns dict with knowledge context or None if unavailable.
        """
        import asyncio

        if not self.knowledge_retriever:
            return None

        try:
            # Run async retrieval
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Already in async context - create task
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(
                        asyncio.run,
                        self.knowledge_retriever.retrieve_for_query(query)
                    )
                    knowledge_context = future.result(timeout=5.0)
            else:
                knowledge_context = loop.run_until_complete(
                    self.knowledge_retriever.retrieve_for_query(query)
                )

            if knowledge_context:
                # Convert to dict for serialization
                return knowledge_context.to_dict()

        except Exception as e:
            logger.warning(f"[ContextGatherer] Knowledge retrieval failed: {e}")

        return None

    def _build_gathered_context_section(
        self,
        preferences: Dict[str, str],
        facts: List[str],
        prior_turns: List[SearchResult],
        memory_results: List[SearchResult],
        research_results: List[ResearchSearchResult] = None,
        knowledge_context: Optional[Dict[str, Any]] = None,
        previous_turn_context: Optional[Dict[str, str]] = None
    ) -> str:
        """Build the §1 Gathered Context section content."""
        research_results = research_results or []
        lines = []

        # NEW: Conversation Context (immediate previous turn) - FIRST for visibility
        # This ensures follow-up questions have the previous Q&A readily available
        if previous_turn_context:
            lines.append("### Conversation Context (Previous Turn)")
            lines.append("")
            if previous_turn_context.get('query'):
                lines.append(f"**User asked:** {previous_turn_context['query']}")
                lines.append("")
            if previous_turn_context.get('response'):
                lines.append("**System responded:**")
                lines.append(previous_turn_context['response'])
                lines.append("")

            # Include research knowledge from previous turn
            knowledge = previous_turn_context.get('knowledge', {})
            if knowledge:
                lines.append("### Research Knowledge (from previous turn)")
                lines.append("")

                if knowledge.get('topic'):
                    lines.append(f"**Topic:** {knowledge['topic']}")
                if knowledge.get('intent'):
                    lines.append(f"**Intent:** {knowledge['intent']}")
                lines.append("")

                # Community tips / expert recommendations
                if knowledge.get('community_tips'):
                    lines.append("**Expert & Community Recommendations:**")
                    for tip in knowledge['community_tips'][:5]:
                        lines.append(f"- {tip}")
                    lines.append("")

                # Reputable sources
                if knowledge.get('reputable_sources'):
                    lines.append("**Reputable Sources:**")
                    lines.append(knowledge['reputable_sources'])
                    lines.append("")

                # Current listings summary
                if knowledge.get('current_listings'):
                    lines.append("**Product Listings Found:**")
                    lines.append(knowledge['current_listings'])
                    lines.append("")

            # Include product findings from previous turn
            findings = previous_turn_context.get('findings', {})
            products = findings.get('products', [])
            if products:
                lines.append("### Product Findings (from previous research)")
                lines.append("")
                lines.append("| Product | Price | Vendor |")
                lines.append("|---------|-------|--------|")
                for p in products[:10]:
                    name = p.get('name', '')[:60]
                    if len(p.get('name', '')) > 60:
                        name += "..."
                    lines.append(f"| {name} | {p.get('price', '')} | {p.get('vendor', '')} |")
                lines.append("")

            lines.append("---")
            lines.append("")

        # Session Preferences
        lines.append("### Session Preferences")
        if preferences:
            for key, value in preferences.items():
                lines.append(f"- **{key}:** {value}")
        else:
            lines.append("*(No preferences stored)*")
        lines.append("")

        # User Facts
        if facts:
            lines.append("### User Facts")
            for fact in facts:
                lines.append(f"- {fact}")
            lines.append("")

        # Cached Research Intelligence (NEW - from knowledge retriever)
        if knowledge_context:
            lines.append("### Cached Research Intelligence")
            lines.append("")

            # Topic match info
            if knowledge_context.get("best_match_topic_name"):
                lines.append(f"**Topic Match:** {knowledge_context['best_match_topic_name']} "
                           f"(similarity: {knowledge_context.get('best_match_similarity', 0):.0%})")
                lines.append(f"**Knowledge Completeness:** {knowledge_context.get('knowledge_completeness', 0):.0%}")
                lines.append("")

            # Retailers (handle both dict and list formats)
            retailers_raw = knowledge_context.get("retailers", [])
            if retailers_raw:
                if isinstance(retailers_raw, dict):
                    retailers = list(retailers_raw.keys())[:5]
                elif isinstance(retailers_raw, list):
                    retailers = retailers_raw[:5]
                else:
                    retailers = []
                if retailers:
                    lines.append("**Known Retailers:**")
                    for retailer in retailers:
                        lines.append(f"- {retailer}")
                    lines.append("")

            # Key specs
            specs = knowledge_context.get("key_specs", [])
            if specs:
                lines.append("**Key Specs/Features:**")
                for spec in specs[:5]:
                    lines.append(f"- {spec}")
                lines.append("")

            # Price expectations
            prices = knowledge_context.get("price_expectations", {})
            if prices:
                lines.append("**Price Expectations:**")
                if "min" in prices:
                    lines.append(f"- Min: ${prices['min']:.2f}")
                if "max" in prices:
                    lines.append(f"- Max: ${prices['max']:.2f}")
                lines.append("")

            # Buying tips
            tips = knowledge_context.get("buying_tips", [])
            if tips:
                lines.append("**Buying Tips:**")
                for tip in tips[:3]:
                    lines.append(f"- {tip}")
                lines.append("")

            # Phase recommendation (important for Planner/Research Role)
            skip_recommended = knowledge_context.get("phase1_skip_recommended", False)
            skip_reason = knowledge_context.get("phase1_skip_reason", "")
            lines.append(f"**Research Phase Recommendation:** {'Skip Phase 1 (use cached intelligence)' if skip_recommended else 'Run Phase 1 (gather fresh intelligence)'}")
            if skip_reason:
                lines.append(f"*Reason: {skip_reason}*")
            lines.append("")

        # Prior Research Knowledge (from research documents)
        if research_results:
            lines.append("### Prior Research Knowledge")
            lines.append("")
            lines.append("*Relevant research from previous queries:*")
            lines.append("")

            for result in research_results:
                entry = result.entry
                lines.append(f"#### Topic: {entry.primary_topic}")
                lines.append(f"*Score: {result.score:.2f}, Quality: {entry.overall_quality:.2f}, Age: {entry.age_hours:.1f}h*")
                lines.append(f"*Match: {result.match_reason}*")
                # CRITICAL: Output content types for sufficiency checking
                if entry.content_types:
                    lines.append(f"*Content Types: {', '.join(entry.content_types)}*")
                lines.append("")

                # Load and include evergreen content
                content = self._load_research_content(entry.doc_path)
                if content:
                    lines.append(content)
                else:
                    # Fallback: show basic info
                    lines.append(f"- Keywords: {', '.join(entry.keywords[:5])}")
                    lines.append(f"- Intent: {entry.intent}")

                lines.append("")

        # Prior Turn Context
        if prior_turns:
            lines.append("### Relevant Prior Turns")
            lines.append("")
            lines.append("| Turn | Relevance | Topic | Summary |")
            lines.append("|------|-----------|-------|---------|")

            for result in prior_turns:
                topic = result.metadata.topic if result.metadata else "unknown"
                snippet = result.snippet[:80].replace("|", "\\|").replace("\n", " ")
                lines.append(f"| {result.turn_number} | {result.relevance_score:.2f} | {topic} | {snippet}... |")
            lines.append("")

        # Memory Context
        if memory_results:
            lines.append("### Long-Term Memory")
            for result in memory_results:
                snippet = result.snippet[:150].replace("\n", " ")
                lines.append(f"- {snippet}")
            lines.append("")

        # Source References
        all_results = prior_turns + memory_results
        if all_results or research_results:
            lines.append("### Source References")
            ref_num = 1

            for result in prior_turns + memory_results:
                summary = result.snippet[:60].replace("\n", " ")
                lines.append(f"- [{ref_num}] {result.document_path} - \"{summary}...\"")
                ref_num += 1

            for result in research_results:
                lines.append(f"- [{ref_num}] {result.entry.doc_path} - \"Research: {result.entry.primary_topic}\"")
                ref_num += 1

            lines.append("")

        # If no context found
        if not preferences and not facts and not prior_turns and not memory_results and not research_results:
            lines.append("*(No relevant prior context found)*")
            lines.append("")

        return "\n".join(lines)


# Convenience function for quick context gathering
def gather_context(
    query: str,
    turn_number: int,
    session_id: str,
    **kwargs
) -> ContextDocument:
    """
    Convenience function to gather context for a query.

    Args:
        query: The user's query
        turn_number: Current turn number
        session_id: User session ID
        **kwargs: Additional arguments for ContextGathererRole

    Returns:
        ContextDocument with §0 and §1 populated
    """
    gatherer = ContextGathererRole(session_id=session_id, **kwargs)
    return gatherer.gather(query=query, turn_number=turn_number)

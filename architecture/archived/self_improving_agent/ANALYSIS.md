# Self-Improving Agent Analysis

## Source
https://github.com/NirDiamant/GenAI_Agents/blob/main/all_agents_tutorials/self_improving_agent.ipynb

## Overview

This notebook implements a conversational AI agent that learns from its interactions through a reflection-learning loop. The agent analyzes its past conversations to generate insights, then applies those insights to improve subsequent responses.

## Architecture

```
User Input → Response Generation (with insights) → Conversation History
                                                          ↓
                                                    Reflection
                                                          ↓
                                                    Learning
                                                          ↓
                                                    Insights Store
```

### Key Components

1. **Chat History Management**: Session-based conversation storage using LangChain's `ChatMessageHistory`
2. **Response Generation**: LLM response with conversation history + accumulated insights
3. **Reflection Mechanism**: Analyzes conversation history to identify improvement areas
4. **Learning System**: Converts reflection insights into actionable principles

## Code Structure

```python
class SelfImprovingAgent:
    def __init__(self):
        self.llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.7)
        self.store = {}      # Session → ChatMessageHistory
        self.insights = ""   # Accumulated learning

    def respond(self, human_input, session_id):
        # Generate response using history + insights

    def reflect(self, session_id):
        # Analyze conversation, generate improvement insights

    def learn(self, session_id):
        # Convert insights to key points, store in history
```

### Reflection Prompt
```python
reflection_prompt = ChatPromptTemplate.from_messages([
    ("system", "Based on the following conversation history, provide insights on how to improve responses:"),
    MessagesPlaceholder(variable_name="history"),
    ("human", "Generate insights for improvement:")
])
```

### Learning Prompt
```python
learning_prompt = ChatPromptTemplate.from_messages([
    ("system", "Based on these insights, update the agent's knowledge and behavior:"),
    ("human", "{insights}"),
    ("human", "Summarize the key points to remember:")
])
```

## Comparison to Pandora

### What This Agent Does

| Aspect | Self-Improving Agent | Pandora |
|--------|---------------------|---------|
| Reflection Trigger | Manual (explicit `learn()` call) | Automatic (Phase 6 Validator) |
| Learning Storage | In-memory `insights` string | Turn Index DB + Memory Bank |
| Scope of Learning | Single session | Cross-session, persistent |
| Application | Injected into system prompt | Retrieved via semantic search |

### What Pandora Already Has (Better)

1. **Persistent Learning**
   - Self-Improving Agent: `self.insights = ""` (in-memory, lost on restart)
   - Pandora: TurnIndexDB stores indexed turns, Memory Bank stores distilled knowledge

2. **Automatic Validation Loop**
   - Self-Improving Agent: Requires explicit `agent.learn()` call
   - Pandora: Phase 6 Validator automatically triggers REVISE/RETRY when quality is low

3. **Evidence-Based Improvement**
   - Self-Improving Agent: Generic "improve responses" reflection
   - Pandora: Validator provides structured feedback with `revision_focus`, `specific_fixes`, `goal_statuses`

4. **Multi-Phase Architecture**
   - Self-Improving Agent: Single LLM call with prompt engineering
   - Pandora: 8-phase pipeline with specialized roles (REFLEX, NERVES, MIND, VOICE)

5. **Context Retrieval**
   - Self-Improving Agent: Injects all insights into every response
   - Pandora: Semantic search retrieves only relevant prior knowledge

### Techniques Worth Considering

1. **Explicit Improvement Principles**

   The learning phase generates concrete principles:
   ```
   1. Prioritize Key Information
   2. Incorporate Storytelling Elements
   3. Use Clear, Vivid Language
   4. Personalize Responses
   5. Inclusion of Lesser-Known Facts
   ```

   **Pandora equivalent**: Our Validator identifies issues but doesn't generate reusable improvement principles. We could:
   - Have Validator generate a "lesson learned" when REVISE succeeds
   - Store these as searchable improvement principles in Memory Bank

2. **Session-Level Adaptation**

   The agent maintains `self.insights` which evolves during a session, affecting all subsequent responses.

   **Pandora equivalent**: We have session context but don't explicitly accumulate "this session's lessons learned". Could add:
   - Session-level insight accumulator in UnifiedFlow
   - Apply within-session learnings to reduce repeated mistakes

3. **Reflection as Separate Phase**

   The explicit `reflect()` → `learn()` separation is clean.

   **Pandora equivalent**: Our Phase 6 Validator does this implicitly. We could make it more explicit by:
   - Adding a "meta-reflection" phase after successful turns
   - Generating transferable insights (not just "this response was good")

## Recommendations

### Priority 1: Session-Level Insight Accumulation (Low Effort, Medium Value)

Add a session insights accumulator to UnifiedFlow:

```python
class UnifiedFlow:
    def __init__(self):
        self.session_insights: Dict[str, List[str]] = {}

    def add_session_insight(self, session_id: str, insight: str):
        if session_id not in self.session_insights:
            self.session_insights[session_id] = []
        self.session_insights[session_id].append(insight)

    def get_session_insights(self, session_id: str) -> str:
        insights = self.session_insights.get(session_id, [])
        return "\n".join(f"- {i}" for i in insights[-5:])  # Last 5
```

Include in context.md §1 for the session:
```markdown
### Session Learnings
- User prefers concise responses
- User wants prices in table format
```

### Priority 2: Improvement Principle Extraction (Medium Effort, High Value)

When Validator approves a REVISE result, extract a transferable principle:

```python
# In unified_flow.py after successful REVISE
if previous_decision == "REVISE" and current_decision == "APPROVE":
    principle = await self.extract_principle(
        original_response=previous_synthesis,
        revised_response=current_synthesis,
        revision_hints=previous_hints
    )
    await self.store_improvement_principle(principle)
```

Store in Memory Bank under `Improvements/Principles/`:
```markdown
---
category: formatting
trigger: price_comparison
---
When presenting price comparisons, use a markdown table with columns for Product, Price, and Source rather than prose paragraphs. Users can scan tables faster.
```

### Priority 3: Meta-Reflection Phase (High Effort, High Value)

Add optional Phase 6.5 that runs after successful turns:

```yaml
# recipes/meta_reflector.yaml
name: meta_reflector
trigger: after_approve
prompt: |
  Review this successful interaction:
  - Query: {query}
  - Response: {response}
  - Validation: APPROVE with confidence {confidence}

  Extract ONE transferable insight that could help with similar future queries.
  Focus on: what made this response successful that could be replicated?
```

This would run async (not blocking response) and feed into Memory Bank.

## Not Recommended

1. **In-Memory Only Insights**: The self-improving agent's `self.insights` string is lost on restart. Pandora's persistent storage is better.

2. **Injecting All Insights**: Putting all accumulated insights into every prompt doesn't scale. Pandora's semantic retrieval is more efficient.

3. **Temperature 0.7 for Everything**: The notebook uses single temperature. Pandora's role-based temperatures (0.1-0.7) are more appropriate.

## Summary

The Self-Improving Agent demonstrates a simple but effective pattern: reflect on interactions, distill lessons, apply to future responses. Pandora already has more sophisticated versions of these components:

- **Reflection** → Phase 6 Validator with structured output
- **Learning** → Turn Index + Memory Bank with semantic retrieval
- **Application** → Context Gatherer retrieves relevant prior knowledge

The main gap is **explicit principle extraction**: when Pandora successfully revises a response, we don't currently extract "what made the revision better" as a reusable principle. Adding this would create a true self-improvement loop where the system gets measurably better over time.

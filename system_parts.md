# system parts
LLM - qwen 3 30b coder awq, qwen 3 4b awq
obsidian memory system - provides the persistent memory for the system, used by the context gatherer
context system - context.md provides the context required for the current user query
document based system - every llm role reads from docs and outputs a doc. 
ralph loop - initiated by the planner when necessary

# internet research mcp requirements:
uses guided intelligent llm phases for navigation and extraction
phase 1 - intelligence gathering, handles all general internet research and extraction
phase 2 - uses intelligence gathered from phase 1 and user requirements to find products/vendors and extract them
output to research.md file > synthesize to context.md
uses human browsing system, no batched internet calls, 

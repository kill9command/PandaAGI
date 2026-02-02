# Clawdbot Patterns for Pandora

**Status:** PROPOSAL
**Created:** 2026-01-26
**Purpose:** Integration plan for Clawdbot-inspired patterns into Pandora

---

## Overview

This document outlines how patterns from Clawdbot can enhance Pandora. Each pattern is evaluated for fit with Pandora's 8-phase pipeline architecture.

---

## Pattern 1: Memory Extraction Pass (Phase 7 Enhancement)

### The Problem

When a turn ends, valuable information lives only in context.md and turn documents. If the user asks a similar question months later, the system may not remember key findings, preferences learned, or lessons from that research.

### The Solution

Add a memory extraction step to Phase 7 (Save) that reviews the turn and persists important knowledge to obsidian_memory.

### Implementation

```
Enhanced Phase 7 (Save):

  1. [NEW] Memory Extraction Pass
     - LLM reviews context.md sections §2-§6
     - Extracts:
       * User preferences expressed or implied
       * Product findings worth remembering
       * Research conclusions
       * Lessons learned (what worked, what didn't)
     - Writes to obsidian_memory/ using existing infrastructure

  2. Save turn document (existing)

  3. Update indexes (existing)
```

### Memory Extraction Prompt

```markdown
## Memory Extraction Task

Review this turn's context.md and extract knowledge worth remembering permanently.

### What to Extract

**User Preferences** (save to /Preferences/):
- Budget constraints mentioned
- Brand preferences (positive or negative)
- Feature priorities
- Shopping preferences

**Research Findings** (save to /Knowledge/Research/):
- Key conclusions from research
- Price ranges discovered
- Quality vendors identified
- Warnings or things to avoid

**Product Knowledge** (save to /Knowledge/Products/):
- Specific products researched with specs
- Price points found
- Pros/cons identified

**Lessons Learned** (save to /Knowledge/Facts/):
- What search strategies worked
- What sources were reliable
- What to do differently next time

### Output Format

```json
{
  "preferences": [
    {"type": "budget", "value": "$500-800", "confidence": 0.9}
  ],
  "research_findings": [
    {"topic": "RTX 4060 laptops", "finding": "Lenovo LOQ best value", "confidence": 0.85}
  ],
  "products": [
    {"name": "Lenovo LOQ 15", "category": "gaming laptop", "key_facts": [...]}
  ],
  "lessons": [
    {"lesson": "Reddit r/GamingLaptops has reliable recommendations", "category": "source_quality"}
  ]
}
```

Only extract information that would be useful for future queries. Skip trivial or obvious information.
```

### Integration Points

| Component | Change |
|-----------|--------|
| `libs/gateway/unified_flow.py` | Add memory extraction after synthesis |
| `apps/phases/phase7_save.py` | New extraction step before save |
| `apps/prompts/memory/extraction.md` | New prompt for extraction |
| `apps/tools/memory/write.py` | Use existing obsidian_memory writer |

### Token Budget

| Step | Tokens |
|------|--------|
| Extraction prompt | ~500 |
| Context input (§2-§6 summary) | ~2000 |
| Extraction output | ~500 |
| **Total** | **~3000** |

Only runs on turns that actually did research or learned something new. Skip for simple recall queries.

---

## Pattern 2: Signal CLI Mobile Channel

### The Problem

Working on code requires sitting at a computer. Sometimes you want to send a quick instruction to Claude Code from your phone - "fix that bug we talked about" or "run the tests" - without opening a laptop.

### The Solution

Use Signal CLI to bridge your phone's Signal app to Claude Code running in VSCode. Text a message, Claude receives it and works on your codebase.

### Why Signal

- **End-to-end encrypted**: Your code instructions stay private
- **No platform policies**: Unlike Telegram/Discord bots, no approval needed
- **Already installed**: You probably have Signal on your phone
- **Free**: No per-message costs like Twilio
- **Works offline-ish**: Messages queue if your server is temporarily down

### Implementation Phases

#### Phase 1: Claude Code in VSCode (Current Priority)

Text your Signal → Claude Code receives message → Works on Pandora codebase

```
┌─────────────────────────────────────────────────────────────────┐
│              Signal → Claude Code Architecture                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Your Phone (Signal App)                                        │
│      │                                                           │
│      │ Signal message: "fix the bug in unified_flow.py"         │
│      ▼                                                           │
│  Signal Server (encrypted)                                       │
│      │                                                           │
│      ▼                                                           │
│  Your Dev Machine                                                │
│      │                                                           │
│      ▼                                                           │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ signal-cli daemon (background process)                  │    │
│  │                                                          │    │
│  │   Receives messages, writes to named pipe or file       │    │
│  │                                                          │    │
│  └─────────────────────────────────────────────────────────┘    │
│      │                                                           │
│      ▼                                                           │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ signal-bridge.py (adapter script)                       │    │
│  │                                                          │    │
│  │   1. Read incoming Signal messages                      │    │
│  │   2. Filter to allowed sender (your number)             │    │
│  │   3. Inject message into Claude Code session            │    │
│  │   4. Capture Claude's response                          │    │
│  │   5. Send response back via Signal                      │    │
│  │                                                          │    │
│  └─────────────────────────────────────────────────────────┘    │
│      │                                                           │
│      ▼                                                           │
│  Claude Code (VSCode) → Works on Pandora codebase              │
│      │                                                           │
│      ▼                                                           │
│  Signal response back to your phone                             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

#### Phase 2: Pandora Gateway (Future)

Same architecture, but targeting Pandora's /chat endpoint instead of Claude Code.

### Setup Guide

#### Step 1: Install signal-cli

```bash
# On Ubuntu/Debian
sudo apt install openjdk-17-jre-headless

# Download signal-cli (check for latest version)
wget https://github.com/AsamK/signal-cli/releases/download/v0.13.2/signal-cli-0.13.2-Linux.tar.gz
tar xf signal-cli-0.13.2-Linux.tar.gz
sudo mv signal-cli-0.13.2 /opt/signal-cli
sudo ln -s /opt/signal-cli/bin/signal-cli /usr/local/bin/signal-cli
```

#### Step 2: Register or Link Your Number

**Option A: Register a new number** (needs a phone that can receive SMS)
```bash
signal-cli -u +1YOURNUMBER register
# Enter verification code received via SMS
signal-cli -u +1YOURNUMBER verify CODE
```

**Option B: Link to existing Signal account** (recommended)
```bash
signal-cli link -n "claude-code-bridge"
# Scan the QR code with Signal app: Settings → Linked Devices → +
```

#### Step 3: Test signal-cli

```bash
# Send a test message to yourself
signal-cli -u +1YOURNUMBER send -m "Test from signal-cli" +1YOURNUMBER

# Receive messages (blocks and waits)
signal-cli -u +1YOURNUMBER receive --json
```

#### Step 4: Create the Bridge Script

```python
#!/usr/bin/env python3
"""
signal-bridge.py - Bridge Signal messages to Claude Code

Usage:
    python signal-bridge.py --number +1YOURNUMBER --allowed +1YOURPHONE
"""

import subprocess
import json
import sys
import os
import argparse
from pathlib import Path

def receive_messages(signal_number: str) -> list[dict]:
    """Receive pending Signal messages."""
    result = subprocess.run(
        ["signal-cli", "-u", signal_number, "receive", "--json", "-t", "1"],
        capture_output=True,
        text=True
    )

    messages = []
    for line in result.stdout.strip().split('\n'):
        if line:
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return messages

def send_message(signal_number: str, recipient: str, message: str):
    """Send a Signal message."""
    # Truncate long messages
    if len(message) > 4000:
        message = message[:3950] + "\n\n[truncated]"

    subprocess.run(
        ["signal-cli", "-u", signal_number, "send", "-m", message, recipient],
        capture_output=True
    )

def inject_to_claude_code(message: str) -> str:
    """
    Inject a message into Claude Code.

    This uses Claude Code's stdin or the /inject endpoint if available.
    For now, we'll write to a file that a VSCode task monitors.
    """
    # Write to input file
    input_file = Path.home() / ".claude" / "signal_input.txt"
    input_file.parent.mkdir(parents=True, exist_ok=True)
    input_file.write_text(message)

    # Wait for response file (Claude Code writes here when done)
    output_file = Path.home() / ".claude" / "signal_output.txt"

    # Poll for response (timeout after 5 minutes)
    import time
    start = time.time()
    while time.time() - start < 300:
        if output_file.exists():
            response = output_file.read_text()
            output_file.unlink()  # Clean up
            return response
        time.sleep(2)

    return "[No response within 5 minutes]"

def main():
    parser = argparse.ArgumentParser(description="Bridge Signal to Claude Code")
    parser.add_argument("--number", required=True, help="Your signal-cli number")
    parser.add_argument("--allowed", required=True, help="Phone number allowed to send commands")
    args = parser.parse_args()

    print(f"Signal bridge started. Listening for messages from {args.allowed}...")

    while True:
        messages = receive_messages(args.number)

        for msg in messages:
            envelope = msg.get("envelope", {})
            source = envelope.get("source")
            data_message = envelope.get("dataMessage", {})
            text = data_message.get("message")

            if not text:
                continue

            # Security: only accept from allowed number
            if source != args.allowed:
                print(f"Ignoring message from {source} (not allowed)")
                continue

            print(f"Received: {text[:100]}...")

            # Send acknowledgment
            send_message(args.number, source, f"⚡ Working on: {text[:50]}...")

            # Inject to Claude Code and get response
            response = inject_to_claude_code(text)

            # Send response back
            send_message(args.number, source, response)
            print(f"Responded with {len(response)} chars")

if __name__ == "__main__":
    main()
```

#### Step 5: VSCode Integration

Create a VSCode task that monitors the signal input file:

```json
// .vscode/tasks.json
{
    "version": "2.0.0",
    "tasks": [
        {
            "label": "Signal Bridge Monitor",
            "type": "shell",
            "command": "python",
            "args": ["scripts/signal_bridge.py", "--number", "+1YOURNUMBER", "--allowed", "+1YOURPHONE"],
            "isBackground": true,
            "problemMatcher": [],
            "presentation": {
                "reveal": "silent",
                "panel": "dedicated"
            }
        }
    ]
}
```

### Claude Code Integration Options

#### Option A: File-based (Simple)

The bridge writes to `~/.claude/signal_input.txt`, and a Claude Code hook reads it.

```python
# In Claude Code hook configuration
# Watches for signal_input.txt and injects as user message
```

#### Option B: Named Pipe (Real-time)

```bash
# Create named pipe
mkfifo ~/.claude/signal_pipe

# Bridge writes to pipe, Claude Code reads from it
```

#### Option C: Claude Code CLI (If Available)

If Claude Code has a CLI injection mechanism:

```bash
# Hypothetical
claude-code inject --message "fix the bug in unified_flow.py"
```

### Security Considerations

| Risk | Mitigation |
|------|------------|
| Unauthorized access | Allowlist specific phone numbers only |
| Message interception | Signal provides E2E encryption |
| Runaway commands | Claude Code's existing permission system applies |
| Accidental triggers | Require prefix like "claude:" for commands |

### Message Format Conventions

```
# Simple instruction
fix the import error in gateway/app.py

# With context
the test_intent_classification.py is failing, can you check why?

# Status check
/status

# Abort current task
/stop
```

### Response Formatting

Since Signal has no markdown rendering:

```python
def format_for_signal(text: str) -> str:
    """Format Claude's response for Signal."""
    # Remove markdown
    text = text.replace("**", "")
    text = text.replace("```python", "---")
    text = text.replace("```", "---")

    # Truncate very long responses
    if len(text) > 4000:
        text = text[:3950] + "\n\n[truncated - check VSCode for full output]"

    return text
```

### Cost

| Item | Cost |
|------|------|
| signal-cli | Free (open source) |
| Signal account | Free |
| Server resources | Already running your dev machine |
| **Total** | **$0/month** |

---

## Pattern 3: Event Hooks System

### The Problem

Extending Pandora requires modifying core code. No way to:
- Intercept dangerous tool calls
- Add custom logging
- Modify behavior without forking

### The Solution

Event-based hook system inspired by Clawdbot's extensions.

### Hook Events

| Event | When | Use Case |
|-------|------|----------|
| `phase_start` | Before each phase | Logging, metrics |
| `phase_end` | After each phase | Logging, modification |
| `tool_call` | Before tool execution | Safety gates, approval |
| `tool_result` | After tool returns | Result modification |
| `memory_write` | Before writing to memory | Filtering, validation |
| `response_ready` | Before sending to user | Final modifications |

### Implementation

```python
# apps/hooks/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Any
from enum import Enum

class HookEvent(Enum):
    PHASE_START = "phase_start"
    PHASE_END = "phase_end"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    MEMORY_WRITE = "memory_write"
    RESPONSE_READY = "response_ready"

@dataclass
class BlockResult:
    """Return this to block an action."""
    blocked: bool
    reason: str
    alternative: Optional[str] = None  # Suggest alternative action

@dataclass
class HookContext:
    """Context passed to all hooks."""
    turn_id: str
    user_id: str
    query: str
    phase: Optional[int] = None
    tool_name: Optional[str] = None
    context_md: Optional[str] = None

class PandaHook(ABC):
    """Base class for Pandora hooks."""

    name: str = "base_hook"
    priority: int = 100  # Lower = runs first

    async def on_phase_start(self, phase: int, ctx: HookContext) -> None:
        """Called before each phase runs."""
        pass

    async def on_phase_end(self, phase: int, ctx: HookContext, result: dict) -> dict:
        """Called after each phase. Can modify result."""
        return result

    async def on_tool_call(self, tool: str, params: dict, ctx: HookContext) -> Optional[BlockResult]:
        """Called before tool execution. Return BlockResult to block."""
        return None

    async def on_tool_result(self, tool: str, result: dict, ctx: HookContext) -> dict:
        """Called after tool returns. Can modify result."""
        return result

    async def on_memory_write(self, artifact: dict, ctx: HookContext) -> Optional[BlockResult]:
        """Called before writing to obsidian_memory. Can block or modify."""
        return None

    async def on_response_ready(self, response: str, ctx: HookContext) -> str:
        """Called before sending response to user. Can modify."""
        return response
```

### Hook Registry

```python
# apps/hooks/registry.py

from typing import List, Optional
from apps.hooks.base import PandaHook, HookEvent, HookContext, BlockResult
import importlib
import os

class HookRegistry:
    """Manages all registered hooks."""

    def __init__(self):
        self.hooks: List[PandaHook] = []

    def register(self, hook: PandaHook):
        """Register a hook."""
        self.hooks.append(hook)
        self.hooks.sort(key=lambda h: h.priority)

    def load_from_directory(self, path: str = "apps/hooks/enabled"):
        """Load all hooks from a directory."""
        for filename in os.listdir(path):
            if filename.endswith(".py") and not filename.startswith("_"):
                module_name = filename[:-3]
                module = importlib.import_module(f"apps.hooks.enabled.{module_name}")
                if hasattr(module, "hook"):
                    self.register(module.hook)

    async def emit_phase_start(self, phase: int, ctx: HookContext):
        """Emit phase_start to all hooks."""
        for hook in self.hooks:
            await hook.on_phase_start(phase, ctx)

    async def emit_tool_call(self, tool: str, params: dict, ctx: HookContext) -> Optional[BlockResult]:
        """Emit tool_call. Returns BlockResult if any hook blocks."""
        for hook in self.hooks:
            result = await hook.on_tool_call(tool, params, ctx)
            if result and result.blocked:
                return result
        return None

    # ... similar methods for other events

# Global registry
registry = HookRegistry()
```

### Example Hooks

#### Safety Hook

```python
# apps/hooks/enabled/safety.py

from apps.hooks.base import PandaHook, HookContext, BlockResult

class SafetyHook(PandaHook):
    """Block dangerous operations."""

    name = "safety"
    priority = 10  # Run early

    # Patterns that require extra scrutiny
    SENSITIVE_PATTERNS = [
        "checkout", "purchase", "buy now", "add to cart",
        "login", "signin", "password",
        "payment", "credit card", "billing"
    ]

    async def on_tool_call(self, tool: str, params: dict, ctx: HookContext) -> Optional[BlockResult]:
        # Block navigation to sensitive pages
        if tool == "browser.navigate":
            url = params.get("url", "").lower()
            for pattern in self.SENSITIVE_PATTERNS:
                if pattern in url:
                    return BlockResult(
                        blocked=True,
                        reason=f"Navigation to '{pattern}' pages requires explicit approval",
                        alternative="Ask user for permission before proceeding"
                    )

        # Block form submissions
        if tool == "browser.fill_form":
            return BlockResult(
                blocked=True,
                reason="Form submission requires explicit approval"
            )

        return None

hook = SafetyHook()
```

#### Logging Hook

```python
# apps/hooks/enabled/logging.py

from apps.hooks.base import PandaHook, HookContext
import logging
import time

logger = logging.getLogger("panda.hooks.logging")

class LoggingHook(PandaHook):
    """Log all phase transitions and tool calls."""

    name = "logging"
    priority = 1  # Run first

    def __init__(self):
        self.phase_start_times = {}

    async def on_phase_start(self, phase: int, ctx: HookContext):
        self.phase_start_times[ctx.turn_id] = time.time()
        logger.info(f"[{ctx.turn_id}] Phase {phase} starting")

    async def on_phase_end(self, phase: int, ctx: HookContext, result: dict) -> dict:
        elapsed = time.time() - self.phase_start_times.get(ctx.turn_id, time.time())
        logger.info(f"[{ctx.turn_id}] Phase {phase} completed in {elapsed:.2f}s")
        return result

    async def on_tool_call(self, tool: str, params: dict, ctx: HookContext):
        logger.info(f"[{ctx.turn_id}] Tool call: {tool}")
        return None

hook = LoggingHook()
```

#### Metrics Hook

```python
# apps/hooks/enabled/metrics.py

from apps.hooks.base import PandaHook, HookContext
from prometheus_client import Counter, Histogram

PHASE_DURATION = Histogram(
    'pandora_phase_duration_seconds',
    'Time spent in each phase',
    ['phase']
)

TOOL_CALLS = Counter(
    'pandora_tool_calls_total',
    'Total tool calls',
    ['tool', 'status']
)

class MetricsHook(PandaHook):
    """Export Prometheus metrics."""

    name = "metrics"
    priority = 5

    # ... implementation

hook = MetricsHook()
```

### Integration with unified_flow.py

```python
# In libs/gateway/unified_flow.py

from apps.hooks.registry import registry

async def run_phase(phase: int, context: ContextDoc, ...):
    ctx = HookContext(
        turn_id=context.turn_id,
        user_id=context.user_id,
        query=context.original_query,
        phase=phase
    )

    # Emit phase_start
    await registry.emit_phase_start(phase, ctx)

    # Run the phase
    result = await phase_executors[phase](context, ...)

    # Emit phase_end (hooks can modify result)
    result = await registry.emit_phase_end(phase, ctx, result)

    return result

async def call_tool(tool_name: str, params: dict, ctx: HookContext):
    # Check if any hook blocks this call
    block = await registry.emit_tool_call(tool_name, params, ctx)
    if block and block.blocked:
        return {
            "status": "blocked",
            "reason": block.reason,
            "alternative": block.alternative
        }

    # Execute the tool
    result = await tool_executor.execute(tool_name, params)

    # Let hooks modify the result
    result = await registry.emit_tool_result(tool_name, result, ctx)

    return result
```

---

## Pattern 4: Progressive Tool Disclosure

### The Problem

Pandora's Coordinator (Phase 5) currently receives full documentation for ALL tools in its system prompt. This:
- Wastes tokens on tools that won't be used
- Makes the prompt harder to parse
- Limits how many tools can be added

### The Solution

List tools compactly (name + one-line description). Coordinator reads full docs on-demand for tools it decides to use.

### Current vs Progressive

```
CURRENT (Phase 5 Coordinator System Prompt):

You have access to these tools:

## internet.research
Research products and information on the web.

### Parameters
- query (required): Search query
- mode: "commerce" | "informational" | "forum"
- budget: Optional price constraint
- ...

### Usage
Call this tool when user needs current information...

### Examples
...

[~500 tokens for this tool alone]

## memory.search
Search past research and user preferences.

### Parameters
...

[~300 tokens]

## browser.navigate
...

[~400 tokens]

Total: ~2000+ tokens just for tool documentation
```

```
PROGRESSIVE (Phase 5 Coordinator System Prompt):

You have access to these tools:

<tools>
  <tool name="internet.research">Research products/info on the web</tool>
  <tool name="memory.search">Search past research and preferences</tool>
  <tool name="browser.navigate">Navigate to a specific URL</tool>
  <tool name="browser.extract">Extract data from current page</tool>
  <tool name="file.read">Read a local file</tool>
  <tool name="file.write">Write to a local file</tool>
</tools>

To use a tool, first call `tools.get_spec(tool_name)` to get its full specification.
Then call the tool with the required parameters.

Total: ~200 tokens for tool list
```

### Implementation

#### Tool Spec Loader

```python
# apps/tools/spec_loader.py

from pathlib import Path
import yaml

TOOL_SPECS_DIR = Path("apps/tools/specs")

def get_tool_list() -> list[dict]:
    """Get compact list of all tools."""
    tools = []
    for spec_file in TOOL_SPECS_DIR.glob("*.yaml"):
        spec = yaml.safe_load(spec_file.read_text())
        tools.append({
            "name": spec["name"],
            "description": spec["short_description"]  # One line
        })
    return tools

def get_tool_spec(tool_name: str) -> str:
    """Get full specification for a tool."""
    spec_file = TOOL_SPECS_DIR / f"{tool_name}.yaml"
    if not spec_file.exists():
        return f"Unknown tool: {tool_name}"

    spec = yaml.safe_load(spec_file.read_text())
    return format_spec_as_markdown(spec)

def format_spec_as_markdown(spec: dict) -> str:
    """Format tool spec as readable markdown."""
    md = f"# {spec['name']}\n\n"
    md += f"{spec['description']}\n\n"
    md += "## Parameters\n\n"
    for param in spec.get('parameters', []):
        required = "(required)" if param.get('required') else "(optional)"
        md += f"- **{param['name']}** {required}: {param['description']}\n"
    if spec.get('examples'):
        md += "\n## Examples\n\n"
        for ex in spec['examples']:
            md += f"```json\n{ex}\n```\n\n"
    return md
```

#### Tool Spec Format

```yaml
# apps/tools/specs/internet.research.yaml

name: internet.research
short_description: Research products and information on the web
description: |
  Performs web research to find products, prices, reviews, and information.
  Uses Phase 1 (search + forum mining) and Phase 2 (vendor visits) internally.

parameters:
  - name: query
    type: string
    required: true
    description: The search query describing what to find

  - name: mode
    type: enum
    values: [commerce, informational, forum]
    default: commerce
    description: |
      - commerce: Product search with prices and availability
      - informational: General information gathering
      - forum: Focus on community discussions and recommendations

  - name: budget
    type: number
    required: false
    description: Maximum price constraint (only for commerce mode)

  - name: vendors
    type: array
    required: false
    description: Specific vendors to check (e.g., ["amazon.com", "bestbuy.com"])

returns:
  type: object
  fields:
    - name: products
      description: List of products found with prices
    - name: sources
      description: URLs of sources consulted
    - name: confidence
      description: Confidence score 0-1

examples:
  - |
    {
      "tool": "internet.research",
      "params": {
        "query": "RTX 4060 gaming laptop under $900",
        "mode": "commerce",
        "budget": 900
      }
    }
```

#### Updated Coordinator Flow

```python
# In Phase 5 Coordinator

async def coordinator_turn(context: ContextDoc, task: str):
    """Single turn of coordinator execution."""

    # Build prompt with compact tool list
    tool_list = get_tool_list()
    tool_xml = format_tools_as_xml(tool_list)

    prompt = f"""
    Task: {task}

    Available tools:
    {tool_xml}

    To use a tool:
    1. First, call tools.get_spec("tool_name") to see full documentation
    2. Then call the tool with appropriate parameters

    What tools do you need for this task?
    """

    # Coordinator decides which tools to use
    response = await llm_call(prompt)

    # If coordinator wants a spec, provide it
    if "tools.get_spec" in response:
        tool_name = extract_tool_name(response)
        spec = get_tool_spec(tool_name)

        # Continue with full spec in context
        response = await llm_call(f"""
        Here is the specification for {tool_name}:

        {spec}

        Now execute the tool call.
        """)

    # Execute the tool call
    ...
```

### Token Savings

| Scenario | Current | Progressive | Savings |
|----------|---------|-------------|---------|
| 6 tools, use 1 | ~2000 tokens | ~300 tokens | 85% |
| 6 tools, use 2 | ~2000 tokens | ~500 tokens | 75% |
| 10 tools, use 1 | ~3500 tokens | ~400 tokens | 89% |
| 10 tools, use 3 | ~3500 tokens | ~800 tokens | 77% |

Progressive disclosure becomes more valuable as tool count grows.

---

## Pattern 5: Planner Path Awareness

### The Problem

The Planner (Phase 3) has to figure out research strategies from scratch every time. It doesn't know what patterns have worked before or what common approaches exist for different query types.

### The Solution

Give the Planner a **pattern library** - a list of known research patterns with descriptions. The Planner doesn't execute these patterns automatically (no workflow engine), but it can reference them when deciding how to approach a query.

This is the useful part of Clawdbot's Lobster without the complexity of a separate execution engine.

### What the Planner Sees

```markdown
## Available Research Patterns

When planning your approach, consider these known patterns:

### Product Comparison
**When:** User wants to compare multiple products
**Approach:** Search broadly, filter by criteria, extract details from top candidates, normalize for comparison
**Typical tools:** internet.research → browser.extract (multiple) → synthesis
**Tips:** Limit to 3-5 products for meaningful comparison. Always include price, key specs, and pros/cons.

### Price Check
**When:** User asks about current price of a known product
**Approach:** Go directly to vendor pages, extract current price and availability
**Typical tools:** browser.navigate (direct URL) → browser.extract
**Tips:** Check 2-3 vendors for price comparison. Prices change frequently.

### Forum Deep-Dive
**When:** User wants community opinions or recommendations
**Approach:** Search forums specifically, extract consensus and dissenting views
**Typical tools:** internet.research (mode=forum) → browser.extract
**Tips:** Reddit, specialized forums often have better info than review sites. Look for recent posts.

### Single Product Research
**When:** User wants details on one specific product
**Approach:** Find product page, extract full specs, find reviews
**Typical tools:** internet.research → browser.navigate → browser.extract
**Tips:** Check both official specs and user reviews. Note common complaints.

### Vendor Survey
**When:** User wants to know where to buy something
**Approach:** Search for product availability across vendors, compare prices and shipping
**Typical tools:** internet.research → browser.extract (multiple vendors)
**Tips:** Include shipping costs and delivery times when relevant.
```

### How It Changes Planner Behavior

**Before (no pattern awareness):**
```
Planner thinks: "User wants to compare laptops. I need to... um...
search for laptops, then look at results, then maybe visit some pages,
then extract data, then... I'll figure it out as I go."

Output: {
  goal: "Compare gaming laptops under $1000",
  approach: "Search and analyze results",  // vague
  route: "coordinator"
}
```

**After (with pattern awareness):**
```
Planner thinks: "User wants to compare laptops. This matches the
'Product Comparison' pattern. I should search broadly, filter to top 5,
extract details from each, then normalize for comparison."

Output: {
  goal: "Compare gaming laptops under $1000",
  pattern: "product_comparison",  // references known pattern
  approach: "Search for gaming laptops under $1000, filter to top 5 candidates,
             extract specs and prices from each, compare by GPU, RAM, price",
  route: "coordinator"
}
```

The Coordinator (Phase 5) still executes step-by-step with LLM decisions, but it has a clearer plan to follow.

### Implementation

#### Pattern Library File

```yaml
# apps/prompts/planner/patterns.yaml

patterns:
  product_comparison:
    name: Product Comparison
    when: User wants to compare multiple products by features, price, or quality
    approach: |
      1. Search broadly for product category
      2. Filter results by user criteria (budget, features)
      3. Select top 3-5 candidates
      4. Extract detailed specs from each
      5. Normalize data for comparison
    typical_flow:
      - internet.research (broad search)
      - filter by criteria (in results)
      - browser.extract (per candidate)
      - synthesis (comparison table)
    tips:
      - Limit to 3-5 products for meaningful comparison
      - Always include price, key specs, pros/cons
      - Note which vendor has best price

  price_check:
    name: Price Check
    when: User asks about current price of a specific product
    approach: |
      1. Navigate directly to known vendor pages
      2. Extract current price and availability
      3. Compare across 2-3 vendors
    typical_flow:
      - browser.navigate (direct to product page)
      - browser.extract (price, availability)
    tips:
      - Prices change frequently - always get fresh data
      - Check major vendors: Amazon, Best Buy, Walmart
      - Note shipping costs if relevant

  forum_research:
    name: Forum Deep-Dive
    when: User wants community opinions, recommendations, or real-world experiences
    approach: |
      1. Search forums and discussion sites
      2. Find threads with relevant discussions
      3. Extract consensus views and notable dissent
      4. Synthesize community wisdom
    typical_flow:
      - internet.research (mode=forum)
      - browser.extract (thread content)
    tips:
      - Reddit and specialized forums often better than review sites
      - Look for recent posts (within 6 months)
      - Note if opinions are divided

  single_product:
    name: Single Product Research
    when: User wants detailed information about one specific product
    approach: |
      1. Find official product page
      2. Extract full specifications
      3. Find user reviews
      4. Summarize key features and concerns
    typical_flow:
      - internet.research (product name)
      - browser.navigate (product page)
      - browser.extract (specs, reviews)
    tips:
      - Check both official specs and user reviews
      - Note common complaints or praise
      - Compare to similar products if relevant

  vendor_survey:
    name: Vendor Survey
    when: User wants to know where to buy or find best deal
    approach: |
      1. Search for product across vendors
      2. Extract price and availability from each
      3. Compare total cost (including shipping)
    typical_flow:
      - internet.research
      - browser.extract (multiple vendors)
    tips:
      - Include shipping costs and delivery times
      - Note return policies if relevant
      - Check for active sales or coupons
```

#### Planner Prompt Integration

```markdown
# Phase 3: Planner Prompt

## Your Task
Create a plan to address the user's query.

## Context
{{context_md_sections_0_2}}

## Available Research Patterns

{{include patterns.yaml formatted}}

## Instructions

1. Identify what the user wants
2. Check if any research pattern fits
3. If a pattern fits, reference it and adapt to the specific query
4. If no pattern fits, create a custom approach
5. Output your plan

## Output Format

```json
{
  "goal": "What the user wants to achieve",
  "pattern": "pattern_name or null if custom",
  "approach": "Step-by-step approach (can adapt pattern or be fully custom)",
  "tools_likely_needed": ["internet.research", "browser.extract"],
  "route": "coordinator | synthesis | clarify"
}
```
```

### Benefits

| Benefit | Description |
|---------|-------------|
| **Better plans** | Planner has proven strategies to reference |
| **Consistency** | Similar queries get similar approaches |
| **Teachable** | Add new patterns as you discover what works |
| **No new infrastructure** | Just prompt changes, no workflow engine |
| **Still flexible** | Planner can ignore patterns or create custom approaches |

### Example: How Patterns Help

**Query:** "What's the best budget mechanical keyboard?"

**Without patterns:**
```
Planner might output a vague plan like:
- Search for keyboards
- Look at results
- Provide recommendation
```

**With patterns:**
```
Planner recognizes this as "forum_research" + "product_comparison":
- Search forums (Reddit r/MechanicalKeyboards) for budget recommendations
- Identify top 3-5 recommended models
- Extract specs and prices for each
- Compare by switch type, build quality, price
- Synthesize with community consensus
```

### Adding New Patterns

When you notice the system handling a query type well, extract it as a pattern:

1. Look at successful turns in transcripts
2. Identify the approach that worked
3. Add to `patterns.yaml`
4. Planner automatically learns it

This is **learning at the prompt level** - no code changes needed.

---

### What We're NOT Doing (Workflow Engine)

The full Lobster-style workflow engine would:
- Define workflows as YAML with steps
- Execute steps deterministically without LLM
- Have approval gates and resume tokens
- Replace the Coordinator for matching queries

**Why we're skipping it:**
- High implementation complexity
- Still runs same tools, just different orchestrator
- Marginal token savings don't justify the complexity
- Planner path awareness gets 80% of the benefit with 20% of the effort

The Coordinator (Phase 5) continues to make step-by-step decisions, but now it has a better plan to follow.

---

## Pattern 6: Dynamic Tool Discovery & Integration (Pandora)

### The Problem

Adding new tool integrations to Pandora is manual work. Someone has to:
1. Know the software exists
2. Figure out how to interface with it
3. Write an MCP adapter or tool definition
4. Test and debug it
5. Register it with the system

This doesn't scale. You have Blender, FreeCAD, PrusaSlicer, various CAM tools, email clients, social media, and dozens of other programs. Writing integrations for each is tedious.

**This pattern is for Pandora** - making the research/assistant system self-extending so it can integrate with any software on your system.

### The Solution

Make the system **self-extending**. When Claude encounters software it doesn't have a tool for, it:
1. Discovers what's installed
2. Figures out how to interface with it
3. Generates an adapter
4. Tests it
5. Registers it for future use

### How Clawdbot Does It (Manual)

Clawdbot uses **skills** - manually written markdown files:

```yaml
# SKILL.md for Blender
---
name: blender
description: 3D modeling and rendering
metadata: {"clawdbot":{"requires":{"bins":["blender"]}}}
---

# Blender Skill

To render a scene:
1. Call bash with: blender -b scene.blend -o //output -F PNG -f 1
...
```

**Limitations:**
- Someone has to write each skill manually
- No automatic discovery
- No interface detection
- No self-improvement

### What We Want (Automatic)

```
┌─────────────────────────────────────────────────────────────────┐
│           Dynamic Tool Discovery & Integration                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  User: "Slice this STL for my Prusa printer"                    │
│      │                                                           │
│      ▼                                                           │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Tool Registry Check                                      │    │
│  │                                                          │    │
│  │   Q: Do we have a slicer tool?                          │    │
│  │   A: No existing tool found                             │    │
│  │                                                          │    │
│  └─────────────────────────────────────────────────────────┘    │
│      │                                                           │
│      ▼                                                           │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Software Discovery                                       │    │
│  │                                                          │    │
│  │   Scan for slicer software:                             │    │
│  │   - which prusa-slicer ✓ /usr/bin/prusa-slicer         │    │
│  │   - which cura ✗                                        │    │
│  │   - which orca-slicer ✗                                 │    │
│  │                                                          │    │
│  │   Found: PrusaSlicer                                    │    │
│  │                                                          │    │
│  └─────────────────────────────────────────────────────────┘    │
│      │                                                           │
│      ▼                                                           │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Interface Detection                                      │    │
│  │                                                          │    │
│  │   prusa-slicer --help → CLI interface detected          │    │
│  │   Key flags:                                             │    │
│  │     --slice           Slice the model                   │    │
│  │     --load CONFIG     Load config file                  │    │
│  │     --output FILE     Output G-code path                │    │
│  │     --export-gcode    Export G-code                     │    │
│  │                                                          │    │
│  └─────────────────────────────────────────────────────────┘    │
│      │                                                           │
│      ▼                                                           │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Adapter Generation                                       │    │
│  │                                                          │    │
│  │   Generate MCP tool definition:                         │    │
│  │   - Tool name: slicer.prusa                             │    │
│  │   - Parameters: stl_path, config, output_path           │    │
│  │   - Execution: subprocess call to prusa-slicer          │    │
│  │                                                          │    │
│  └─────────────────────────────────────────────────────────┘    │
│      │                                                           │
│      ▼                                                           │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Test & Register                                          │    │
│  │                                                          │    │
│  │   1. Test with sample input                             │    │
│  │   2. Verify output is valid                             │    │
│  │   3. Save to apps/tools/generated/slicer_prusa.py      │    │
│  │   4. Register in tool catalog                           │    │
│  │                                                          │    │
│  └─────────────────────────────────────────────────────────┘    │
│      │                                                           │
│      ▼                                                           │
│  Execute task with newly generated tool                         │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Interface Detection Strategies

Different software exposes different interfaces. The system tries them in order:

| Priority | Interface Type | Detection Method | Example |
|----------|---------------|------------------|---------|
| 1 | CLI | `program --help`, `man program` | Blender, ffmpeg, PrusaSlicer |
| 2 | Python API | `import module; help(module)` | bpy (Blender), FreeCAD |
| 3 | REST API | Check for running server, docs | Octoprint, Home Assistant |
| 4 | D-Bus | `busctl list`, introspection | GNOME apps, system services |
| 5 | File-based | Watch input/output directories | Some CAM software |
| 6 | GUI Automation | As last resort | PyAutoGUI, xdotool |

### Software Categories

```yaml
# apps/tools/discovery/software_categories.yaml

categories:
  3d_modeling:
    description: 3D modeling and CAD software
    search_binaries:
      - blender
      - freecad
      - openscad
      - fusion360  # Wine/Proton
    search_python:
      - bpy
      - FreeCAD
    common_tasks:
      - model_open
      - model_export
      - render

  slicers:
    description: 3D printer slicing software
    search_binaries:
      - prusa-slicer
      - cura
      - orca-slicer
      - slic3r
    common_tasks:
      - slice_stl
      - load_config
      - export_gcode

  cam_software:
    description: CNC/CAM toolpath generation
    search_binaries:
      - pycam
      - camotics
      - freecad  # With Path workbench
    common_tasks:
      - generate_toolpath
      - simulate
      - export_gcode

  email:
    description: Email clients and APIs
    search_apis:
      - gmail_api
      - outlook_api
      - imap
    search_binaries:
      - thunderbird
      - mutt
      - neomutt
    common_tasks:
      - send_email
      - read_inbox
      - search_emails

  social_media:
    description: Social media platforms
    search_apis:
      - twitter_api
      - mastodon_api
      - reddit_api
      - discord_api
    common_tasks:
      - post_message
      - read_feed
      - send_dm
```

### Adapter Generation

When an interface is detected, generate an adapter:

```python
# apps/tools/discovery/adapter_generator.py

class AdapterGenerator:
    """Generate MCP tool adapters for discovered software."""

    async def generate_cli_adapter(
        self,
        program: str,
        help_text: str,
        category: str
    ) -> str:
        """Generate a Python MCP adapter from CLI help text."""

        prompt = f"""
        Generate a Python MCP tool adapter for this CLI program.

        Program: {program}
        Category: {category}
        Help text:
        ```
        {help_text}
        ```

        Requirements:
        1. Parse the most useful flags from the help text
        2. Create a tool class with appropriate parameters
        3. Include input validation
        4. Handle errors gracefully
        5. Return structured output

        Output format: Python code for apps/tools/generated/{program}.py
        """

        # LLM generates the adapter code
        code = await self.llm_call(prompt)

        # Validate the generated code
        if self.validate_syntax(code):
            return code
        else:
            # Retry with error feedback
            ...

    async def generate_python_api_adapter(
        self,
        module: str,
        api_docs: str,
        category: str
    ) -> str:
        """Generate adapter for Python API."""
        ...

    async def generate_rest_api_adapter(
        self,
        base_url: str,
        openapi_spec: dict,
        category: str
    ) -> str:
        """Generate adapter for REST API."""
        ...
```

### Generated Adapter Example

```python
# apps/tools/generated/slicer_prusa.py
# AUTO-GENERATED by Dynamic Tool Discovery
# Source: prusa-slicer CLI
# Generated: 2026-01-26

from dataclasses import dataclass
from typing import Optional
import subprocess
import os

@dataclass
class SlicerPrusaParams:
    stl_path: str              # Path to input STL file
    output_path: Optional[str] = None  # Output G-code path
    config: Optional[str] = None       # Printer config file
    layer_height: Optional[float] = None
    infill: Optional[int] = None       # Infill percentage (0-100)

class SlicerPrusaTool:
    """Slice STL files using PrusaSlicer."""

    name = "slicer.prusa"
    description = "Slice 3D models for Prusa 3D printers"

    def __init__(self):
        self.binary = "/usr/bin/prusa-slicer"

    async def execute(self, params: SlicerPrusaParams) -> dict:
        # Validate input
        if not os.path.exists(params.stl_path):
            return {"error": f"STL file not found: {params.stl_path}"}

        # Build command
        cmd = [self.binary, "--slice", params.stl_path]

        if params.output_path:
            cmd.extend(["--output", params.output_path])
        else:
            params.output_path = params.stl_path.replace(".stl", ".gcode")
            cmd.extend(["--output", params.output_path])

        if params.config:
            cmd.extend(["--load", params.config])

        if params.layer_height:
            cmd.extend(["--layer-height", str(params.layer_height)])

        if params.infill is not None:
            cmd.extend(["--fill-density", f"{params.infill}%"])

        # Execute
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300
            )

            if result.returncode == 0:
                return {
                    "success": True,
                    "output_path": params.output_path,
                    "stdout": result.stdout
                }
            else:
                return {
                    "success": False,
                    "error": result.stderr
                }

        except subprocess.TimeoutExpired:
            return {"error": "Slicing timed out after 5 minutes"}
        except Exception as e:
            return {"error": str(e)}
```

### Tool Catalog

Track all tools (built-in and generated):

```yaml
# apps/tools/catalog.yaml

tools:
  # Built-in tools
  internet.research:
    type: builtin
    source: apps/services/orchestrator/internet_research_mcp.py
    status: active

  browser.navigate:
    type: builtin
    source: apps/services/orchestrator/browser_mcp.py
    status: active

  # Generated tools
  slicer.prusa:
    type: generated
    source: apps/tools/generated/slicer_prusa.py
    generated_from: prusa-slicer CLI
    generated_at: 2026-01-26T10:30:00Z
    interface: cli
    status: active
    test_results:
      last_test: 2026-01-26T10:31:00Z
      passed: true

  blender.render:
    type: generated
    source: apps/tools/generated/blender_render.py
    generated_from: blender CLI + bpy API
    generated_at: 2026-01-25T14:00:00Z
    interface: cli+python
    status: active

  # Failed/pending tools
  fusion360.export:
    type: generated
    source: apps/tools/generated/fusion360_export.py
    generated_from: fusion360 (Wine)
    status: failed
    failure_reason: "Wine prefix not configured"
```

### Integration with Pandora Pipeline

This plugs into Pandora's existing architecture:

```
User Query: "Slice this STL for my Prusa"
    │
    ▼
Phase 3 (Planner): Needs slicing capability
    │
    ▼
Phase 4 (Coordinator): Requests slicer tool
    │
    ├── Tool exists? → Execute normally
    │
    └── Tool missing? → Trigger Discovery
            │
            ▼
        ┌─────────────────────────────┐
        │ Discovery Service           │
        │                             │
        │ 1. Find slicer software     │
        │ 2. Detect interface         │
        │ 3. Generate MCP adapter     │
        │ 4. Test adapter             │
        │ 5. Register in tool catalog │
        │                             │
        └─────────────────────────────┘
            │
            ▼
        Coordinator retries with new tool
            │
            ▼
Phase 5 (Synthesis): Report results
```

Generated tools become **MCP tools** in `apps/services/orchestrator/generated/` and are available to the Coordinator just like built-in tools.

### Discovery Triggers

When does discovery run?

| Trigger | Example |
|---------|---------|
| **Explicit request** | "Set up Blender integration" |
| **Task requires unknown tool** | "Slice this STL" (no slicer tool exists) |
| **Periodic scan** | Weekly scan for new software |
| **Manual registration** | User points to a program |
| **Phase 4 tool miss** | Coordinator requests tool that doesn't exist |

### Learning Loop

When a generated tool fails, learn from it:

```python
async def execute_with_learning(self, tool_name: str, params: dict):
    """Execute tool and learn from failures."""

    result = await self.execute_tool(tool_name, params)

    if result.get("error"):
        # Log failure
        self.log_failure(tool_name, params, result["error"])

        # Attempt self-repair
        tool_def = self.get_tool_definition(tool_name)

        repair_prompt = f"""
        This generated tool failed:

        Tool: {tool_name}
        Parameters: {params}
        Error: {result['error']}

        Current implementation:
        ```python
        {tool_def.source_code}
        ```

        Diagnose the issue and generate a fixed version.
        """

        fixed_code = await self.llm_call(repair_prompt)

        if self.validate_and_test(fixed_code):
            self.update_tool(tool_name, fixed_code)
            # Retry with fixed tool
            return await self.execute_tool(tool_name, params)

    return result
```

### Security Considerations

Auto-generating code that executes is risky:

| Risk | Mitigation |
|------|------------|
| Malicious code generation | Sandbox execution, code review prompts |
| Credential exposure | Never pass credentials to generated tools |
| System damage | Dry-run mode, confirmation for destructive ops |
| Runaway processes | Timeouts, resource limits |

```python
# All generated tools run in restricted mode
GENERATED_TOOL_RESTRICTIONS = {
    "max_execution_time": 300,      # 5 minutes
    "max_memory_mb": 1024,          # 1GB
    "allowed_paths": ["~/projects", "/tmp"],
    "network_access": False,         # Unless explicitly enabled
    "require_confirmation": ["delete", "overwrite", "send"]
}
```

### Implementation Phases

#### Phase 1: Manual Discovery Helper
- User says "I have PrusaSlicer installed"
- Claude reads `--help`, generates adapter
- User reviews and approves

#### Phase 2: Semi-Automatic Discovery
- Claude scans for known software categories
- Proposes integrations
- User approves each one

#### Phase 3: Fully Automatic
- Background service monitors for new software
- Auto-generates and tests adapters
- Notifies user of new capabilities

### Example Interaction (via Pandora Chat)

```
User: "Slice this STL file for my Prusa MK3S"

Pandora [Phase 3 - Planner]:
  Task requires 3D slicing capability.
  Checking tool catalog... no slicer tool found.
  Route: discovery → coordinator

Pandora [Discovery Service]:
  Scanning for slicer software...
  Found: PrusaSlicer at /usr/bin/prusa-slicer

  Analyzing CLI interface...
  Detected flags: --slice, --load, --output, --layer-height, --fill-density

  Generating MCP adapter...
  Created: apps/services/orchestrator/generated/slicer_prusa_mcp.py

  Testing with sample file...
  ✓ Test passed - generated valid G-code

  Registered: slicer.prusa in tool catalog

Pandora [Phase 4 - Coordinator]:
  Executing slicer.prusa tool...
  Input: user's STL file
  Config: Prusa MK3S profile

Pandora [Phase 5 - Synthesis]:
  Done! G-code saved to model.gcode
  - Estimated print time: 4h 23m
  - Filament usage: 47g
  - Layer height: 0.2mm

  The file is ready to transfer to your printer.
```

**Future queries reuse the generated tool:**
```
User: "Slice this other model with 15% infill"

Pandora [Phase 4 - Coordinator]:
  Using existing slicer.prusa tool...
  [No discovery needed - tool already exists]
```

### Comparison to Clawdbot

| Aspect | Clawdbot Skills | Dynamic Discovery |
|--------|-----------------|-------------------|
| Creation | Manual markdown files | Auto-generated Python |
| Discovery | None (gating only) | Active scanning |
| Interface detection | None | CLI, Python, REST, etc. |
| Self-repair | None | Learn from failures |
| User effort | Write each skill | Approve generated tools |

---

## Implementation Priority

| Priority | Pattern | Effort | Value |
|----------|---------|--------|-------|
| **1** | Signal CLI → Claude Code | Low | Very High |
| **2** | Memory Extraction (Phase 7) | Low | High |
| **3** | Planner Path Awareness | Low | High |
| **4** | Event Hooks | Medium | High |
| **5** | Progressive Tool Disclosure | Medium | Medium |
| **6** | Dynamic Tool Discovery (Phase 1) | Medium | Very High |
| *Future* | Dynamic Tool Discovery (Full) | High | Very High |
| *Future* | Signal CLI → Pandora | Low | High |

### Phase 1: Immediate (Signal Bridge)

1. **Signal CLI → Claude Code** - Mobile access to current dev workflow
   - Install signal-cli
   - Link to Signal account
   - Create bridge script
   - Test with VSCode

### Phase 2: Quick Wins (1-2 days each)

2. **Memory Extraction Pass** - Add to Phase 7
3. **Planner Path Awareness** - Add patterns.yaml, update Planner prompt
4. **Basic Hooks** - Logging and safety hooks

### Phase 3: Medium Effort (3-5 days each)

5. **Progressive Disclosure** - Refactor Coordinator tool loading
6. **Dynamic Tool Discovery (Phase 1)** - Manual discovery helper
   - User tells Claude about installed software
   - Claude reads --help, generates adapter
   - User reviews and approves
   - Register in tool catalog

### Future

7. **Dynamic Tool Discovery (Full)** - Semi/fully automatic discovery
   - Background scanning for installed software
   - Auto-generate and test adapters
   - Self-repair from failures

8. **Signal CLI → Pandora** - Same bridge pattern, target Pandora /chat instead of Claude Code

---

## Summary

These Clawdbot-inspired patterns enhance Pandora without fundamentally changing its architecture:

| Pattern | How It Fits |
|---------|-------------|
| Signal CLI → Claude Code | Mobile access to current dev workflow (immediate priority) |
| Memory Extraction | Extends Phase 7 Save |
| Event Hooks | Wraps existing phase execution |
| Progressive Disclosure | Refactors Coordinator prompting |
| Planner Path Awareness | Enhances Phase 3 Planner with pattern library |
| **Dynamic Tool Discovery** | **Self-extending system - auto-generates integrations for new software** |
| Signal CLI → Pandora | Future: Same pattern targeting Pandora /chat |

The 8-phase pipeline remains the backbone. These patterns make it more efficient, extensible, and accessible.

**Note on Dynamic Tool Discovery:** This goes beyond what Clawdbot does. Clawdbot requires manually written skills for each integration. Our approach is to make Pandora self-extending - it discovers software on your system, figures out how to interface with it, generates MCP adapters, and learns from failures. This integrates with Pandora's Phase 4 Coordinator - when it needs a tool that doesn't exist, it triggers discovery. This is ambitious but incredibly powerful for a maker/developer workflow with many specialized tools (CAD, CAM, slicers, rendering, email, social media, etc.).

# 06 - Browser System Integration

**Created:** 2026-01-07
**Status:** Ready for Implementation
**Priority:** HIGH

---

## Overview

This document details the integration of the unified `browser_system.py` into PandaAI v2's internet research tool. The new system replaces the fragmented browser management with a single, cohesive module that handles:

- Browser lifecycle (Firefox)
- Stealth injection (bot detection bypass)
- Session management (cookie persistence)
- Human-like behavior (typing delays, warmup)
- Multi-engine search (DuckDuckGo → Google → Brave)
- CAPTCHA intervention (local terminal prompt)

---

## Files to Modify

| File | Action | Description |
|------|--------|-------------|
| `browser_system.py` | CREATED | New unified browser system (already created) |
| `browser_manager.py` | DELETE | Replaced by browser_system.py |
| `search_client.py` | DELETE | Replaced by browser_system.py |
| `research_tool.py` | MODIFY | Update to use BrowserSystem |
| `internet_research_phase1_intelligence.py` | MODIFY | Update to use BrowserSystem |
| `page_extractor.py` | MODIFY | Update to use BrowserSystem |
| `tools.py` | MODIFY | Update internet.research integration |

---

## Step-by-Step Implementation

### Step 1: Install Dependencies

```bash
conda activate pandaaiv2
pip install playwright-stealth
```

This provides 100+ bot detection bypass vectors. If not installed, `browser_system.py` falls back to embedded scripts.

---

### Step 2: Update research_tool.py

**Current code:**
```python
from .browser_manager import BrowserManager
from .search_client import SearchClient

class InternetResearchTool:
    def __init__(self):
        self._browser_manager = BrowserManager()
        # ...
```

**New code:**
```python
from .browser_system import BrowserSystem, get_browser_system

class InternetResearchTool:
    def __init__(self):
        self._browser = None  # Lazy initialization
        # ...

    async def _get_browser(self) -> BrowserSystem:
        if self._browser is None:
            self._browser = get_browser_system()
            await self._browser._ensure_browser()
        return self._browser
```

---

### Step 3: Update internet_research_phase1_intelligence.py

**Current code:**
```python
from .search_client import SearchClient

class Phase1Intelligence:
    def __init__(self, browser_manager, llm_client):
        self.browser_manager = browser_manager
        # ...

    async def _execute_searches(self, queries):
        search_client = SearchClient(self.browser_manager)
        for query in queries:
            results = await search_client.search(query)
```

**New code:**
```python
from .browser_system import BrowserSystem

class Phase1Intelligence:
    def __init__(self, browser: BrowserSystem, llm_client):
        self.browser = browser
        # ...

    async def _execute_searches(self, queries):
        all_results = []
        for query in queries:
            results = await self.browser.search(query)
            all_results.extend(results)
            await asyncio.sleep(1.5)  # Delay between queries
        return all_results
```

---

### Step 4: Update page_extractor.py

**Current code:**
```python
class PageExtractor:
    def __init__(self, browser_manager):
        self.browser_manager = browser_manager

    async def extract_text(self, url: str) -> str:
        async with self.browser_manager.get_page() as page:
            await self.browser_manager.navigate(page, url)
            # ...
```

**New code:**
```python
from .browser_system import BrowserSystem

class PageExtractor:
    def __init__(self, browser: BrowserSystem):
        self.browser = browser

    async def extract_text(self, url: str) -> str:
        return await self.browser.extract_page_text(url)
```

---

### Step 5: Update tools.py (LocalToolExecutor)

**Current code:**
```python
async def _internet_research(self, args: dict) -> dict:
    from apps.mcp_tools.internet_research_mcp.research_tool import InternetResearchTool
    self._research_tool = InternetResearchTool()
    result = await self._research_tool.execute(query, context)
```

**New code:**
```python
async def _internet_research(self, args: dict) -> dict:
    from apps.mcp_tools.internet_research_mcp.research_tool import InternetResearchTool
    from apps.mcp_tools.internet_research_mcp.browser_system import get_browser_system

    if self._research_tool is None:
        self._research_tool = InternetResearchTool()

    result = await self._research_tool.execute(query, context)
    return result

async def close(self):
    """Cleanup resources."""
    from apps.mcp_tools.internet_research_mcp.browser_system import shutdown_browser_system
    await shutdown_browser_system()
```

---

### Step 6: Delete Old Files

After integration is complete and tested:

```bash
rm apps/mcp-tools/internet-research-mcp/browser_manager.py
rm apps/mcp-tools/internet-research-mcp/search_client.py
```

---

### Step 7: Create Session Storage Directory

```bash
mkdir -p panda-system-docs/shared_state/browser_sessions
```

This is where cookie/session data will be persisted.

---

## Configuration

Environment variables (optional):

| Variable | Default | Description |
|----------|---------|-------------|
| `BROWSER_ENGINE` | `firefox` | Browser type (firefox/chromium) |
| `SEARCH_ENGINE` | `duckduckgo` | Search engine (duckduckgo/google/brave) |
| `BROWSER_HEADLESS` | `false` | Run headless (true/false) |

These are set in `BrowserConfig` and can be overridden via environment.

To switch search engines, set in `.env` or export:
```bash
export SEARCH_ENGINE=google  # Use Google instead of DuckDuckGo
```

---

## Testing Plan

### Test 1: Basic Search
```python
from apps.mcp_tools.internet_research_mcp.browser_system import BrowserSystem

async def test_search():
    async with BrowserSystem() as browser:
        results = await browser.search("best gaming laptops 2024")
        print(f"Found {len(results)} results")
        for r in results[:3]:
            print(f"  - {r['title'][:50]}")
```

### Test 2: Session Persistence
```python
async def test_session():
    browser = BrowserSystem()
    await browser._ensure_browser()

    # First search (creates session)
    results1 = await browser.search("test query")

    # Close and reopen (should restore cookies)
    await browser.close()

    browser2 = BrowserSystem()
    await browser2._ensure_browser()
    results2 = await browser2.search("test query 2")

    # Check session was restored
    session_dir = Path("panda-system-docs/shared_state/browser_sessions")
    assert (session_dir / "default" / "duckduckgo_com" / "state.json").exists()
```

### Test 3: CAPTCHA Intervention
1. Run a search that triggers CAPTCHA
2. Verify terminal shows "INTERVENTION REQUIRED"
3. Solve CAPTCHA in browser window
4. Press Enter in terminal
5. Verify search continues

### Test 4: Full Pipeline
```bash
python -m apps.cli.local.main
> find me gaming laptops under $500
```

---

## Rollback Plan

If integration fails:

1. Git stash changes: `git stash`
2. Restore old files from git
3. Investigate and fix issues
4. Re-apply changes: `git stash pop`

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                      LocalToolExecutor                       │
│                         (tools.py)                           │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    InternetResearchTool                      │
│                     (research_tool.py)                       │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                      BrowserSystem                           │
│                    (browser_system.py)                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   Stealth   │  │   Session   │  │   Human Behavior    │  │
│  │  Injection  │  │  Manager    │  │  (warmup, typing)   │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│  ┌─────────────────────────────────────────────────────────┐│
│  │              Multi-Engine Search                        ││
│  │         DuckDuckGo → Google → Brave                     ││
│  └─────────────────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────────────────┐│
│  │           CAPTCHA Intervention (Terminal)               ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    Playwright Firefox                        │
│                  (visible, stealth-enabled)                  │
└─────────────────────────────────────────────────────────────┘
```

---

## Success Criteria

- [ ] Firefox browser launches and stays visible
- [ ] Stealth injection prevents bot detection
- [ ] Sessions persist across restarts (cookies saved)
- [ ] Human-like typing visible (50-150ms delays)
- [ ] Session warmup visible (scroll, mouse movement)
- [ ] Multi-engine fallback works (DDG → Google → Brave)
- [ ] CAPTCHA intervention prompts in terminal
- [ ] User can solve CAPTCHA and continue
- [ ] Full pipeline works end-to-end

---

## Notes

1. **Firefox Profile Compatibility**: We don't use the user's Firefox profile because Playwright's bundled Firefox version differs from the installed version. Sessions are managed separately.

2. **Headless Mode**: Default is `headless=False` (visible) because we need to see and solve CAPTCHAs. Can be changed via `BROWSER_HEADLESS=true` for automated testing.

3. **Memory Management**: Browser auto-restarts after 15 pages to prevent memory leaks. Sessions are saved before restart.

4. **No Remote Streaming**: The original source had WebSocket streaming for remote CAPTCHA solving. We removed this since we're running locally and can see the browser directly.

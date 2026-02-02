README.TXT

 Core Entry Point & Orchestration
  ┌────────────────────────────────────────────┬──────────────────────────────────────────────────────────────────┐
  │                    File                    │                             Purpose                              │
  ├────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────┤
  │ orchestrator/internet_research_mcp.py      │ Main MCP entry point for internet.research tool                  │
  ├────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────┤
  │ orchestrator/research_role.py              │ Core orchestration - routes between Phase 1/2, handles deep mode │
  ├────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────┤
  │ orchestrator/research_orchestrator.py      │ Executes Phase 1 (intelligence) & Phase 2 (vendor search)        │
  ├────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────┤
  │ orchestrator/research_strategy_selector.py │ LLM-powered phase selection                                      │
  └────────────────────────────────────────────┴──────────────────────────────────────────────────────────────────┘
  Web Navigation & Browser
  ┌─────────────────────────────────────────┬────────────────────────────────────────────────────────────┐
  │                  File                   │                          Purpose                           │
  ├─────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
  │ orchestrator/web_vision_mcp.py          │ Vision-guided browser automation (click, scroll, navigate) │
  ├─────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
  │ orchestrator/browser_agent.py           │ Multi-page browsing for forums, catalogs                   │
  ├─────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
  │ orchestrator/ui_vision_agent.py         │ DOM + OCR perception for web interaction                   │
  ├─────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
  │ orchestrator/goal_directed_navigator.py │ LLM-driven goal-based navigation                           │
  ├─────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
  │ orchestrator/human_web_navigator.py     │ URL visiting and content extraction (deprecated)           │
  └─────────────────────────────────────────┴────────────────────────────────────────────────────────────┘
  Extraction Pipeline
  ┌───────────────────────────────────────┬──────────────────────────────────┐
  │                 File                  │             Purpose              │
  ├───────────────────────────────────────┼──────────────────────────────────┤
  │ orchestrator/smart_extractor.py       │ Unified LLM-learned extraction   │
  ├───────────────────────────────────────┼──────────────────────────────────┤
  │ orchestrator/adaptive_extractor.py    │ Learns page structures           │
  ├───────────────────────────────────────┼──────────────────────────────────┤
  │ orchestrator/unified_web_extractor.py │ Unified extraction from any page │
  ├───────────────────────────────────────┼──────────────────────────────────┤
  │ orchestrator/product_viability.py     │ LLM-driven product filtering     │
  └───────────────────────────────────────┴──────────────────────────────────┘
  Search & SERP
  ┌─────────────────────────────────────────┬──────────────────────────────────────┐
  │                  File                   │               Purpose                │
  ├─────────────────────────────────────────┼──────────────────────────────────────┤
  │ orchestrator/human_search_engine.py     │ Human-like Google search with warmup │
  ├─────────────────────────────────────────┼──────────────────────────────────────┤
  │ orchestrator/llm_candidate_filter.py    │ Filters SERP results via LLM         │
  ├─────────────────────────────────────────┼──────────────────────────────────────┤
  │ orchestrator/search_result_evaluator.py │ Evaluates search result quality      │
  └─────────────────────────────────────────┴──────────────────────────────────────┘
  Knowledge & Caching (shared_state/)
  ┌───────────────────────────────────────────────────┬────────────────────────────────┐
  │                       File                        │            Purpose             │
  ├───────────────────────────────────────────────────┼────────────────────────────────┤
  │ orchestrator/shared_state/source_reliability.py   │ Tracks source quality scores   │
  ├───────────────────────────────────────────────────┼────────────────────────────────┤
  │ orchestrator/shared_state/topic_index.py          │ Cross-session topic tracking   │
  ├───────────────────────────────────────────────────┼────────────────────────────────┤
  │ orchestrator/shared_state/site_schema_registry.py │ Cached extraction schemas      │
  ├───────────────────────────────────────────────────┼────────────────────────────────┤
  │ orchestrator/knowledge_extractor.py               │ Stores knowledge from research │
  └───────────────────────────────────────────────────┴────────────────────────────────┘
  Gateway Integration
  ┌──────────────────────────────────┬──────────────────────────────────┐
  │               File               │             Purpose              │
  ├──────────────────────────────────┼──────────────────────────────────┤
  │ lib/gateway/research_document.py │ Schema for research.md documents │
  ├──────────────────────────────────┼──────────────────────────────────┤
  │ lib/gateway/research_index_db.py │ Indexes research for retrieval   │
  └──────────────────────────────────┴──────────────────────────────────┘

Browser Management Layer
  ┌──────────────────────────────────────────┬───────────────────────────────────────────────────────┐
  │                   File                   │                        Purpose                        │
  ├──────────────────────────────────────────┼───────────────────────────────────────────────────────┤
  │ orchestrator/shared/browser_factory.py   │ Centralized browser creation (Chromium/Firefox)       │
  ├──────────────────────────────────────────┼───────────────────────────────────────────────────────┤
  │ orchestrator/browser_session_registry.py │ Session tracking with CDP access for remote viewing   │
  ├──────────────────────────────────────────┼───────────────────────────────────────────────────────┤
  │ orchestrator/crawler_session_manager.py  │ Persistent contexts with cookies/storage preservation │
  ├──────────────────────────────────────────┼───────────────────────────────────────────────────────┤
  │ orchestrator/browser_recovery.py         │ Automatic recovery from connection failures           │
  └──────────────────────────────────────────┴───────────────────────────────────────────────────────┘
  Stealth & Anti-Detection
  ┌────────────────────────────────────────┬──────────────────────────────────────────────────────┐
  │                  File                  │                       Purpose                        │
  ├────────────────────────────────────────┼──────────────────────────────────────────────────────┤
  │ orchestrator/stealth_injector.py       │ 100+ detection vector bypass via playwright-stealth  │
  ├────────────────────────────────────────┼──────────────────────────────────────────────────────┤
  │ orchestrator/playwright_stealth_mcp.py │ Stealth fetching with bot challenge detection        │
  ├────────────────────────────────────────┼──────────────────────────────────────────────────────┤
  │ orchestrator/browser_fingerprint.py    │ Consistent viewport, timezone, user-agent generation │
  └────────────────────────────────────────┴──────────────────────────────────────────────────────┘
  Remote Control & Streaming
  ┌────────────────────────────────────────┬──────────────────────────────────────────────┐
  │                  File                  │                   Purpose                    │
  ├────────────────────────────────────────┼──────────────────────────────────────────────┤
  │ orchestrator/browser_cdp_proxy.py      │ WebSocket proxy for Chrome DevTools Protocol │
  ├────────────────────────────────────────┼──────────────────────────────────────────────┤
  │ orchestrator/browser_stream_manager.py │ Live browser streaming for CAPTCHA solving   │
  ├────────────────────────────────────────┼──────────────────────────────────────────────┤
  │ orchestrator/real_browser_connector.py │ Connect to user's actual Chrome/Firefox      │
  └────────────────────────────────────────┴──────────────────────────────────────────────┘
  Integration Flow

  research_orchestrator.py
      ↓
  web_vision_mcp.navigate(url)
      ↓
  crawler_session_manager.get_or_create_session()
      ↓
  browser_factory.launch_browser()
      ↓
  stealth_injector.inject_stealth()

  The web_vision_mcp.py is the main bridge - it exposes Playwright operations (navigate, click, scroll, capture_content) as MCP tools that the research system calls. browser_agent.py builds on top of this for multi-page browsing with pagination detection.
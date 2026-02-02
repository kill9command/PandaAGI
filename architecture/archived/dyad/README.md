# Dyad Reference

**Repository:** https://github.com/dyad-sh/dyad
**Type:** AI App Builder / Code Generation IDE
**License:** Apache 2.0 (open) + FSL 1.1 (pro features)

---

## What is Dyad?

Dyad is a **local, open-source AI application builder** - a self-hosted alternative to Lovable, v0, Bolt, and Replit Agent. It's an Electron desktop app where users describe what they want and AI builds it.

### Key Characteristics

- **Privacy-First**: Runs entirely on user machines, no cloud dependencies
- **Multi-Provider**: Bring your own API keys (OpenAI, Anthropic, Google, Ollama, LM Studio, etc.)
- **No Account Required**: Download and use immediately
- **Cross-Platform**: macOS and Windows

### Core Capabilities

| Capability | Description |
|------------|-------------|
| Code Generation | AI writes full applications from descriptions |
| Live Preview | See changes in real-time as AI codes |
| Project Management | Create, edit, deploy projects |
| MCP Integration | Extensible tool system via Model Context Protocol |
| Multi-Model | Switch between providers/models per project |

---

## Why This Reference?

Dyad's architecture offers patterns relevant to Pandora's code mode:

1. **XML-based tool execution** - Alternative to native function calling
2. **Context management** - Full codebase vs smart filtering strategies
3. **Mode switching** - Build/Ask/Agent modes for different workflows
4. **Cost-conscious design** - Single-pass generation philosophy

---

## Quick Links

- [Architecture Details](./ARCHITECTURE.md)
- [Integration Notes](./INTEGRATION.md)

---

## Comparison Summary

| Aspect | Dyad | Pandora |
|--------|------|---------|
| Purpose | Build apps from descriptions | Research & answer questions |
| User | Developers | End users |
| Philosophy | Token-efficient, single-pass | Quality-first, multi-phase |
| Output | Working code | Validated answers |

They solve different problems but could complement each other - Pandora's research feeding Dyad's code generation.

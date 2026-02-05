# Deprecated Prompts

This folder contains prompts that were created during earlier experimentation but are no longer used by the system.

## Files

### solver_system_chat.md
- **Created**: ~Nov 6, 2024
- **Purpose**: Lightweight prompt for simple chat interactions without full ticket/capsule workflow
- **Why deprecated**: The unified `solver_system.md` handles all query types efficiently. Strategic analysis adds minimal overhead (<1s) while providing valuable cache evaluation and intent detection even for simple queries.

### solver_system_code.md
- **Created**: ~Nov 6, 2024
- **Purpose**: Developer-focused prompt for code operations with diff/patch output
- **Why deprecated**: The unified `solver_system.md` with Fractal Decision Architecture provides better safety, auditability, and provenance tracking for code operations. The extra cycles are worthwhile for write operations.

## Why Not Use Mode-Specific Prompts?

The current unified architecture provides:
- ✅ Consistent behavior across all query types
- ✅ Strategic analysis prevents cache pollution universally
- ✅ Intent detection works for simple and complex queries
- ✅ Simpler codebase (no routing logic needed)
- ✅ Single well-tested prompt instead of 3-5 variants

Performance is excellent with the unified approach:
- Simple queries: 1-2 cycles
- Token overhead: ~2k (negligible for 200k context)
- Latency: <10 seconds end-to-end

## Current Active Prompts

- **solver_system.md** - Guide (user-facing planner) with Fractal Decision Architecture
- **thinking_system.md** - Coordinator (worker/operator) with intent-aware tool selection
- **context_manager.md** - Context Manager (reviewer/reducer) with quality assurance

## Migration Path

If you ever need lightweight prompts:
1. Review these files as starting points
2. Consider if the performance gain justifies added complexity
3. Implement query routing logic in Gateway
4. Test thoroughly against the unified approach

For now, these are kept for reference only.

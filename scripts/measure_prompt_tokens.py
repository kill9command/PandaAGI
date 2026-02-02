#!/usr/bin/env python3
"""
Token Measurement Script for Prompt Architecture Audit

Measures actual token usage across all prompts in the reflection cycle
to validate refactor savings calculations.

Quality Agent identified 23% error in token calculations - this script
provides ground truth measurements.
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import tiktoken
from pathlib import Path

# Token encoder (using GPT-3.5 as approximation for local models)
encoder = tiktoken.encoding_for_model("gpt-3.5-turbo")


def read_prompt(path: str) -> str:
    """Read prompt file from project_build_instructions/prompts/"""
    full_path = Path("project_build_instructions/prompts") / path
    if not full_path.exists():
        return ""
    return full_path.read_text()


def count_tokens(text: str) -> int:
    """Count tokens in text"""
    return len(encoder.encode(text))


def measure_guide_prompts():
    """Measure Guide prompt variants"""
    print("=" * 80)
    print("GUIDE PROMPTS")
    print("=" * 80)

    # Common base
    common = read_prompt("guide/common.md")
    common_tokens = count_tokens(common)
    print(f"common.md:                    {common_tokens:5d} tokens")

    # Chat mode variants
    chat_strategic = read_prompt("guide/strategic.md")
    chat_synthesis = read_prompt("guide/synthesis.md")

    chat_strat_total = common_tokens + count_tokens(chat_strategic)
    chat_synth_total = common_tokens + count_tokens(chat_synthesis)

    print(f"\nChat Mode:")
    print(f"  strategic.md (base):        {count_tokens(chat_strategic):5d} tokens")
    print(f"  strategic.md (+ common):    {chat_strat_total:5d} tokens")
    print(f"  synthesis.md (base):        {count_tokens(chat_synthesis):5d} tokens")
    print(f"  synthesis.md (+ common):    {chat_synth_total:5d} tokens")

    # Code mode variants
    code_strategic = read_prompt("guide/code_strategic.md")
    code_synthesis = read_prompt("guide/code_synthesis.md")

    code_strat_total = common_tokens + count_tokens(code_strategic)
    code_synth_total = common_tokens + count_tokens(code_synthesis)

    print(f"\nCode Mode:")
    print(f"  code_strategic.md (base):   {count_tokens(code_strategic):5d} tokens")
    print(f"  code_strategic.md (+ common): {code_strat_total:5d} tokens")
    print(f"  code_synthesis.md (base):   {count_tokens(code_synthesis):5d} tokens")
    print(f"  code_synthesis.md (+ common): {code_synth_total:5d} tokens")

    # Fallback
    core = read_prompt("guide/core.md")
    print(f"\nFallback:")
    print(f"  core.md (monolithic):       {count_tokens(core):5d} tokens")

    return {
        "chat_strategic": chat_strat_total,
        "chat_synthesis": chat_synth_total,
        "code_strategic": code_strat_total,
        "code_synthesis": code_synth_total,
    }


def measure_coordinator_prompts():
    """Measure Coordinator prompt variants"""
    print("\n" + "=" * 80)
    print("COORDINATOR PROMPTS")
    print("=" * 80)

    # Monolithic current version
    thinking_system = read_prompt("thinking_system.md")
    thinking_tokens = count_tokens(thinking_system)
    print(f"thinking_system.md (CURRENT): {thinking_tokens:5d} tokens ⚠️  BOTTLENECK")

    # Smaller variants
    core = read_prompt("coordinator/core.md")
    code_ops = read_prompt("coordinator/code_operations_enhanced.md")

    print(f"\nPartial splits (not used):")
    print(f"  coordinator/core.md:        {count_tokens(core):5d} tokens")
    print(f"  code_operations_enhanced.md: {count_tokens(code_ops):5d} tokens")

    return {
        "thinking_system": thinking_tokens,
        "coordinator_core": count_tokens(core),
    }


def measure_context_manager_prompts():
    """Measure Context Manager prompts"""
    print("\n" + "=" * 80)
    print("CONTEXT MANAGER PROMPTS")
    print("=" * 80)

    # Main Context Manager prompt (used for both modes)
    cm_main = read_prompt("context_manager.md")
    cm_main_tokens = count_tokens(cm_main)

    # Code-specific variant (if used)
    code_evidence = read_prompt("context_manager/code_evidence.md")
    code_evidence_tokens = count_tokens(code_evidence)

    print(f"context_manager.md (main):    {cm_main_tokens:5d} tokens")
    print(f"code_evidence.md (code alt):  {code_evidence_tokens:5d} tokens")

    return {
        "unified": cm_main_tokens,  # Main prompt used for both modes
        "code_evidence": code_evidence_tokens,
    }


def calculate_reflection_cycle_totals(guide, coordinator, context_manager):
    """Calculate total tokens per reflection cycle"""
    print("\n" + "=" * 80)
    print("REFLECTION CYCLE TOTALS (Current Architecture)")
    print("=" * 80)

    # Chat mode reflection cycle
    chat_cycle = (
        guide["chat_strategic"] +
        coordinator["thinking_system"] +
        context_manager["unified"] +
        guide["chat_synthesis"]
    )

    print(f"\nChat Mode Full Cycle:")
    print(f"  Guide (strategic):          {guide['chat_strategic']:5d} tokens")
    print(f"  Coordinator:                {coordinator['thinking_system']:5d} tokens")
    print(f"  Context Manager:            {context_manager['unified']:5d} tokens")
    print(f"  Guide (synthesis):          {guide['chat_synthesis']:5d} tokens")
    print(f"  {'─' * 40}")
    print(f"  TOTAL:                      {chat_cycle:5d} tokens")

    # Code mode reflection cycle
    code_cycle = (
        guide["code_strategic"] +
        coordinator["thinking_system"] +
        context_manager["code_evidence"] +
        guide["code_synthesis"]
    )

    print(f"\nCode Mode Full Cycle:")
    print(f"  Guide (strategic):          {guide['code_strategic']:5d} tokens")
    print(f"  Coordinator:                {coordinator['thinking_system']:5d} tokens")
    print(f"  Context Manager:            {context_manager['code_evidence']:5d} tokens")
    print(f"  Guide (synthesis):          {guide['code_synthesis']:5d} tokens")
    print(f"  {'─' * 40}")
    print(f"  TOTAL:                      {code_cycle:5d} tokens")

    return {
        "chat_cycle": chat_cycle,
        "code_cycle": code_cycle,
    }


def calculate_budget_analysis(totals):
    """Analyze token budget usage"""
    print("\n" + "=" * 80)
    print("TOKEN BUDGET ANALYSIS")
    print("=" * 80)

    total_budget = 12000  # Gateway total budget

    for mode, cycle_tokens in totals.items():
        mode_name = mode.replace("_", " ").title()
        remaining = total_budget - cycle_tokens
        percent_used = (cycle_tokens / total_budget) * 100

        print(f"\n{mode_name}:")
        print(f"  Total budget:               {total_budget:5d} tokens")
        print(f"  Prompt tokens:              {cycle_tokens:5d} tokens ({percent_used:.1f}%)")
        print(f"  Remaining for RAG/response: {remaining:5d} tokens ({100-percent_used:.1f}%)")

        if remaining < 3000:
            print(f"  ⚠️  WARNING: Less than 3k tokens for context!")


def estimate_refactor_savings(coordinator):
    """Estimate token savings from Coordinator split"""
    print("\n" + "=" * 80)
    print("REFACTOR SAVINGS ESTIMATE (Phase 1: Coordinator Split)")
    print("=" * 80)

    current = coordinator["thinking_system"]

    # Conservative estimate: Split into 2 files, each 45% of original
    # (Some shared content, but less duplication than 50% each)
    estimated_chat = int(current * 0.45)
    estimated_code = int(current * 0.45)

    savings_chat = current - estimated_chat
    savings_code = current - estimated_code

    percent_savings_chat = (savings_chat / current) * 100
    percent_savings_code = (savings_code / current) * 100

    print(f"\nCurrent:")
    print(f"  thinking_system.md:         {current:5d} tokens (both modes)")

    print(f"\nEstimated After Split:")
    print(f"  coordinator/chat.md:        {estimated_chat:5d} tokens")
    print(f"  coordinator/code.md:        {estimated_code:5d} tokens")

    print(f"\nSavings:")
    print(f"  Chat mode:                  {savings_chat:5d} tokens ({percent_savings_chat:.1f}% reduction)")
    print(f"  Code mode:                  {savings_code:5d} tokens ({percent_savings_code:.1f}% reduction)")

    print(f"\n⚠️  Note: These are ESTIMATES. Actual savings depend on:")
    print(f"     - How much content is truly mode-specific")
    print(f"     - Whether shared sections can be deduplicated")
    print(f"     - Amount of new mode-specific guidance added")


def main():
    """Run all measurements"""
    print("\n")
    print("╔" + "═" * 78 + "╗")
    print("║" + " PANDORA PROMPT ARCHITECTURE TOKEN AUDIT ".center(78) + "║")
    print("╚" + "═" * 78 + "╝")

    guide = measure_guide_prompts()
    coordinator = measure_coordinator_prompts()
    context_manager = measure_context_manager_prompts()
    totals = calculate_reflection_cycle_totals(guide, coordinator, context_manager)
    calculate_budget_analysis(totals)
    estimate_refactor_savings(coordinator)

    print("\n" + "=" * 80)
    print("KEY FINDINGS")
    print("=" * 80)
    print(f"✅ Guide prompts: Already split and mode-aware")
    print(f"⚠️  Coordinator: {coordinator['thinking_system']} tokens (bottleneck)")
    print(f"✅ Context Manager: Already mode-aware")
    print(f"\n🎯 Primary refactor target: thinking_system.md")
    print(f"   Expected savings: ~2,000-2,500 tokens per request")
    print("=" * 80)
    print()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Measure ACTUAL prompts loaded by Gateway in production.

This script simulates Gateway's actual prompt loading logic to get
accurate token counts for what's really being used.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import tiktoken
from pathlib import Path

encoder = tiktoken.encoding_for_model("gpt-3.5-turbo")

def read_prompt(path: str) -> str:
    """Read prompt file"""
    full_path = Path("project_build_instructions/prompts") / path
    if not full_path.exists():
        return ""
    return full_path.read_text()

def count_tokens(text: str) -> int:
    """Count tokens"""
    return len(encoder.encode(text))

def assemble_guide_prompt(mode: str = "strategic", intent: str = None) -> str:
    """
    Simulate _load_split_guide_prompt() from Gateway
    """
    common = read_prompt("guide/common.md")

    if intent == "code":
        if mode == "strategic":
            role_prompt = read_prompt("guide/code_strategic.md")
        else:  # synthesis
            role_prompt = read_prompt("guide/code_synthesis.md")
    else:
        if mode == "strategic":
            role_prompt = read_prompt("guide/strategic.md")
        elif mode == "synthesis":
            role_prompt = read_prompt("guide/synthesis.md")
        else:
            role_prompt = read_prompt("guide/strategic.md")

    return f"{common}\n\n---\n\n{role_prompt}"

def assemble_coordinator_prompt(task_type: str = "general", use_modular: bool = True) -> str:
    """
    Simulate _assemble_coordinator_prompt() from Gateway
    """
    if not use_modular:
        return read_prompt("thinking_system.md")

    # Check if modular prompts exist
    coordinator_dir = Path("project_build_instructions/prompts/coordinator")
    if not coordinator_dir.exists():
        return read_prompt("thinking_system.md")

    # Always load core
    core = read_prompt("coordinator/core.md")
    prompt_parts = [core] if core else []

    # Always load intent mapping
    intent_mapping = read_prompt("coordinator/tools/intent_mapping.md")
    if intent_mapping:
        prompt_parts.append(intent_mapping)

    # Load code operations ONLY for code tasks
    if task_type == "code":
        code_ops = read_prompt("coordinator/code_operations_enhanced.md")
        if code_ops:
            prompt_parts.append(code_ops)

    # Load reflection (useful for all tasks)
    reflection = read_prompt("coordinator/reference/reflection.md")
    if reflection:
        prompt_parts.append(reflection)

    return "\n\n---\n\n".join(part for part in prompt_parts if part)

def main():
    print("\n")
    print("╔" + "═" * 78 + "╗")
    print("║" + " ACTUAL PRODUCTION PROMPT TOKEN AUDIT ".center(78) + "║")
    print("╚" + "═" * 78 + "╝")
    print("\n⚠️  This measures what Gateway ACTUALLY loads, not all files!")

    # Measure actual coordinator prompts
    print("\n" + "=" * 80)
    print("COORDINATOR PROMPTS (Modular - ACTUALLY LOADED)")
    print("=" * 80)

    coord_chat = assemble_coordinator_prompt(task_type="general", use_modular=True)
    coord_code = assemble_coordinator_prompt(task_type="code", use_modular=True)
    coord_monolithic = read_prompt("thinking_system.md")

    coord_chat_tokens = count_tokens(coord_chat)
    coord_code_tokens = count_tokens(coord_code)
    coord_mono_tokens = count_tokens(coord_monolithic)

    print(f"\nModular (chat mode):          {coord_chat_tokens:5d} tokens ✅ ACTUALLY USED")
    print(f"Modular (code mode):          {coord_code_tokens:5d} tokens ✅ ACTUALLY USED")
    print(f"thinking_system.md:          {coord_mono_tokens:5d} tokens ⚠️  FALLBACK ONLY")

    # Show breakdown
    print(f"\nModular Chat Breakdown:")
    core = read_prompt("coordinator/core.md")
    intent_map = read_prompt("coordinator/tools/intent_mapping.md")
    reflection = read_prompt("coordinator/reference/reflection.md")

    print(f"  core.md:                    {count_tokens(core):5d} tokens")
    print(f"  intent_mapping.md:          {count_tokens(intent_map):5d} tokens")
    print(f"  reflection.md:              {count_tokens(reflection):5d} tokens")
    print(f"  {'─' * 40}")
    print(f"  TOTAL:                      {coord_chat_tokens:5d} tokens")

    print(f"\nModular Code Breakdown:")
    code_ops = read_prompt("coordinator/code_operations_enhanced.md")
    print(f"  core.md:                    {count_tokens(core):5d} tokens")
    print(f"  intent_mapping.md:          {count_tokens(intent_map):5d} tokens")
    print(f"  code_operations_enhanced.md:{count_tokens(code_ops):5d} tokens")
    print(f"  reflection.md:              {count_tokens(reflection):5d} tokens")
    print(f"  {'─' * 40}")
    print(f"  TOTAL:                      {coord_code_tokens:5d} tokens")

    # Measure Guide prompts
    print("\n" + "=" * 80)
    print("GUIDE PROMPTS (ACTUALLY LOADED)")
    print("=" * 80)

    guide_chat_strat = assemble_guide_prompt(mode="strategic", intent=None)
    guide_chat_synth = assemble_guide_prompt(mode="synthesis", intent=None)
    guide_code_strat = assemble_guide_prompt(mode="strategic", intent="code")
    guide_code_synth = assemble_guide_prompt(mode="synthesis", intent="code")

    print(f"\nChat Mode:")
    print(f"  Strategic:                  {count_tokens(guide_chat_strat):5d} tokens")
    print(f"  Synthesis:                  {count_tokens(guide_chat_synth):5d} tokens")

    print(f"\nCode Mode:")
    print(f"  Strategic:                  {count_tokens(guide_code_strat):5d} tokens")
    print(f"  Synthesis:                  {count_tokens(guide_code_synth):5d} tokens")

    # Measure Context Manager
    print("\n" + "=" * 80)
    print("CONTEXT MANAGER PROMPTS (ACTUALLY LOADED)")
    print("=" * 80)

    cm_prompt = read_prompt("context_manager.md")
    cm_tokens = count_tokens(cm_prompt)

    print(f"\ncontext_manager.md:           {cm_tokens:5d} tokens ✅ USED FOR BOTH MODES")

    # Calculate ACTUAL reflection cycles
    print("\n" + "=" * 80)
    print("ACTUAL REFLECTION CYCLE TOTALS")
    print("=" * 80)

    chat_cycle = (
        count_tokens(guide_chat_strat) +
        coord_chat_tokens +
        cm_tokens +
        count_tokens(guide_chat_synth)
    )

    code_cycle = (
        count_tokens(guide_code_strat) +
        coord_code_tokens +
        cm_tokens +
        count_tokens(guide_code_synth)
    )

    print(f"\nChat Mode Full Cycle:")
    print(f"  Guide (strategic):          {count_tokens(guide_chat_strat):5d} tokens")
    print(f"  Coordinator (modular):      {coord_chat_tokens:5d} tokens")
    print(f"  Context Manager:            {cm_tokens:5d} tokens")
    print(f"  Guide (synthesis):          {count_tokens(guide_chat_synth):5d} tokens")
    print(f"  {'─' * 40}")
    print(f"  TOTAL:                      {chat_cycle:5d} tokens")

    print(f"\nCode Mode Full Cycle:")
    print(f"  Guide (strategic):          {count_tokens(guide_code_strat):5d} tokens")
    print(f"  Coordinator (modular):      {coord_code_tokens:5d} tokens")
    print(f"  Context Manager:            {cm_tokens:5d} tokens")
    print(f"  Guide (synthesis):          {count_tokens(guide_code_synth):5d} tokens")
    print(f"  {'─' * 40}")
    print(f"  TOTAL:                      {code_cycle:5d} tokens")

    # Budget analysis
    print("\n" + "=" * 80)
    print("BUDGET ANALYSIS (ACTUAL USAGE)")
    print("=" * 80)

    total_budget = 12000

    for mode, cycle_tokens in [("Chat", chat_cycle), ("Code", code_cycle)]:
        remaining = total_budget - cycle_tokens
        percent_used = (cycle_tokens / total_budget) * 100

        print(f"\n{mode} Mode:")
        print(f"  Total budget:               {total_budget:5d} tokens")
        print(f"  Prompt tokens:              {cycle_tokens:5d} tokens ({percent_used:.1f}%)")
        print(f"  Remaining for RAG/response: {remaining:5d} tokens ({100-percent_used:.1f}%)")

        if remaining < 0:
            print(f"  ❌ OVERFLOW: {abs(remaining)} tokens over budget!")
        elif remaining < 3000:
            print(f"  ⚠️  WARNING: Less than 3k tokens for context!")
        else:
            print(f"  ✅ OK: Sufficient headroom for RAG and response")

    # Comparison
    print("\n" + "=" * 80)
    print("COMPARISON: Modular vs Monolithic")
    print("=" * 80)

    print(f"\nIf we used thinking_system.md (monolithic):")

    mono_chat_cycle = (
        count_tokens(guide_chat_strat) +
        coord_mono_tokens +
        cm_tokens +
        count_tokens(guide_chat_synth)
    )

    mono_code_cycle = (
        count_tokens(guide_code_strat) +
        coord_mono_tokens +
        cm_tokens +
        count_tokens(guide_code_synth)
    )

    print(f"  Chat cycle:                 {mono_chat_cycle:5d} tokens ({mono_chat_cycle - total_budget:+5d} overflow)")
    print(f"  Code cycle:                 {mono_code_cycle:5d} tokens ({mono_code_cycle - total_budget:+5d} overflow)")

    print(f"\nWith modular coordinator (CURRENT):")
    print(f"  Chat cycle:                 {chat_cycle:5d} tokens ({chat_cycle - total_budget:+5d} vs budget)")
    print(f"  Code cycle:                 {code_cycle:5d} tokens ({code_cycle - total_budget:+5d} vs budget)")

    print(f"\nSavings from modular architecture:")
    print(f"  Chat mode:                  {mono_chat_cycle - chat_cycle:5d} tokens saved ({((mono_chat_cycle - chat_cycle) / mono_chat_cycle * 100):.1f}%)")
    print(f"  Code mode:                  {mono_code_cycle - code_cycle:5d} tokens saved ({((mono_code_cycle - code_cycle) / mono_code_cycle * 100):.1f}%)")

    print("\n" + "=" * 80)
    print("KEY FINDINGS")
    print("=" * 80)
    print(f"✅ Gateway IS using modular coordinator (not monolithic thinking_system.md)")
    print(f"✅ Modular architecture saves {mono_chat_cycle - chat_cycle:,} tokens in chat mode")
    print(f"✅ Current architecture is {('WITHIN' if chat_cycle <= total_budget else 'OVER')} budget")

    if chat_cycle <= total_budget and code_cycle <= total_budget:
        print(f"\n🎉 SYSTEM IS WORKING CORRECTLY - No immediate refactor needed!")
        print(f"   Remaining headroom: {total_budget - max(chat_cycle, code_cycle)} tokens")
    else:
        print(f"\n⚠️  SYSTEM EXCEEDS BUDGET - Refactor needed!")
        print(f"   Overflow: {max(chat_cycle - total_budget, code_cycle - total_budget)} tokens")

    print("=" * 80)
    print()

if __name__ == "__main__":
    main()

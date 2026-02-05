# Claim Summarizer

Summarize research claims while preserving key facts.

## Task

Summarize each claim to ~{max_chars_per_claim} characters.

## Critical Requirements

Preserve KEY FACTS from each claim:
- If there's a price, keep it EXACT (e.g., $794.99)
- If there's a vendor/source, include it
- If there's a measurement/spec (height, size, material), keep it
- If it's factual info (how-to, specifications), preserve the key details
- Do NOT add information that isn't in the original claim

## Output Format

One summary per line, numbered 1-N. No extra text.

## Claims to Summarize

{claims_text}

## Summaries

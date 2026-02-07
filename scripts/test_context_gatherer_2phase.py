#!/usr/bin/env python3
"""
Test script for 2-phase Context Gatherer implementation.

Runs the 2-phase Context Gatherer on test queries and measures:
- Token usage (estimated)
- Latency
- Output quality (section structure, content)
- Follow-up handling (N-1 inclusion)

Usage:
    python scripts/test_context_gatherer_2phase.py [--query "your query"]

Requirements:
    - vLLM server running on port 8000
    - Existing turn history in panda_system_docs/turns/
"""

import asyncio
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from libs.gateway.context.context_gatherer_2phase import ContextGatherer2Phase

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


class MockLLMClient:
    """Mock LLM client that tracks calls and tokens."""

    def __init__(self, real_client: Optional[Any] = None):
        self.real_client = real_client
        self.calls = []
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    async def call(
        self,
        prompt: str,
        role: str = "default",
        max_tokens: int = 500,
        temperature: float = 0.1
    ) -> str:
        """Track call and forward to real client if available."""
        input_tokens = len(prompt) // 4  # Rough estimate

        call_record = {
            "timestamp": datetime.now().isoformat(),
            "role": role,
            "input_tokens": input_tokens,
            "max_tokens": max_tokens,
            "prompt_preview": prompt[:200] + "..." if len(prompt) > 200 else prompt
        }

        if self.real_client:
            start = time.time()
            response = await self.real_client.call(
                prompt=prompt,
                role=role,
                max_tokens=max_tokens,
                temperature=temperature
            )
            latency = time.time() - start

            output_tokens = len(response) // 4
            call_record["output_tokens"] = output_tokens
            call_record["latency_ms"] = int(latency * 1000)
            call_record["response_preview"] = response[:200] + "..." if len(response) > 200 else response

            self.total_output_tokens += output_tokens
        else:
            # Return mock response
            response = json.dumps({
                "turns": [],
                "links_to_follow": [],
                "sufficient": True,
                "reasoning": "Mock response"
            })
            output_tokens = len(response) // 4
            call_record["output_tokens"] = output_tokens
            call_record["latency_ms"] = 0

        self.calls.append(call_record)
        self.total_input_tokens += input_tokens

        return response

    def get_stats(self) -> Dict[str, Any]:
        """Get call statistics."""
        return {
            "total_calls": len(self.calls),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "avg_latency_ms": sum(c.get("latency_ms", 0) for c in self.calls) / len(self.calls) if self.calls else 0,
            "calls": self.calls
        }

    def reset(self):
        """Reset statistics."""
        self.calls = []
        self.total_input_tokens = 0
        self.total_output_tokens = 0


class RealLLMClient:
    """Real LLM client for actual testing."""

    def __init__(self):
        import aiohttp
        self.url = os.getenv("SOLVER_URL", "http://127.0.0.1:8000/v1/chat/completions")
        self.model = os.getenv("SOLVER_MODEL_ID", "qwen3-coder")
        self.api_key = os.getenv("SOLVER_API_KEY", "qwen-local")

    async def call(
        self,
        prompt: str,
        role: str = "default",
        max_tokens: int = 500,
        temperature: float = 0.1
    ) -> str:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "response_format": {"type": "json_object"}
                },
                timeout=aiohttp.ClientTimeout(total=60)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data["choices"][0]["message"]["content"]
                else:
                    error = await response.text()
                    raise RuntimeError(f"LLM error {response.status}: {error[:200]}")


async def test_2phase(query: str, turn_number: int, session_id: str, mock_client: MockLLMClient) -> Dict[str, Any]:
    """Run 2-phase context gatherer and collect metrics."""
    logger.info("=" * 60)
    logger.info("Testing 2-PHASE Context Gatherer")
    logger.info("=" * 60)

    mock_client.reset()
    start_time = time.time()

    gatherer = ContextGatherer2Phase(
        session_id=session_id,
        llm_client=mock_client,
        turns_dir=Path("panda_system_docs/turns"),
        sessions_dir=Path("panda_system_docs/sessions")
    )

    try:
        context_doc = await gatherer.gather(query=query, turn_number=turn_number)
        success = True
        error = None
        output = context_doc.get_markdown()
    except Exception as e:
        success = False
        error = str(e)
        output = None
        logger.error(f"2-phase failed: {e}")

    elapsed = time.time() - start_time
    stats = mock_client.get_stats()

    return {
        "implementation": "2-phase",
        "success": success,
        "error": error,
        "elapsed_seconds": elapsed,
        "llm_calls": stats["total_calls"],
        "input_tokens": stats["total_input_tokens"],
        "output_tokens": stats["total_output_tokens"],
        "total_tokens": stats["total_tokens"],
        "avg_latency_ms": stats["avg_latency_ms"],
        "output_length": len(output) if output else 0,
        "call_details": stats["calls"]
    }


def print_results(results: Dict):
    """Print test results."""
    print("\n" + "=" * 80)
    print("2-Phase Context Gatherer Test Results")
    print("=" * 80)

    metrics = [
        ("Success", results["success"]),
        ("LLM Calls", results["llm_calls"]),
        ("Input Tokens", results["input_tokens"]),
        ("Output Tokens", results["output_tokens"]),
        ("Total Tokens", results["total_tokens"]),
        ("Elapsed (s)", f"{results['elapsed_seconds']:.2f}"),
        ("Avg Latency (ms)", f"{results['avg_latency_ms']:.0f}"),
        ("Output Length", results["output_length"]),
    ]

    print(f"\n{'Metric':<20} {'Value':<15}")
    print("-" * 35)

    for name, val in metrics:
        print(f"{name:<20} {str(val):<15}")

    print("=" * 80)


async def run_test_suite(use_real_llm: bool = False):
    """Run test suite with multiple query types."""

    # Test queries covering different scenarios
    test_queries = [
        {
            "name": "New Query (no context)",
            "query": "What are the best gaming laptops under $1500?",
            "is_followup": False
        },
        {
            "name": "Follow-up (pronoun reference)",
            "query": "Can you find some of those with RTX 4070?",
            "is_followup": True
        },
        {
            "name": "Direct question",
            "query": "What was the price range from earlier?",
            "is_followup": True
        },
        {
            "name": "Topic switch",
            "query": "Where can I buy a hamster?",
            "is_followup": False
        }
    ]

    # Find latest turn number
    turns_dir = Path("panda_system_docs/turns")
    existing_turns = sorted(turns_dir.glob("turn_*"))
    if existing_turns:
        latest_turn = int(existing_turns[-1].name.split("_")[1])
    else:
        latest_turn = 0

    session_id = "test_2phase_session"

    # Create LLM client
    if use_real_llm:
        logger.info("Using REAL LLM client (vLLM)")
        try:
            real_client = RealLLMClient()
            # Quick connectivity test
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(real_client.url.replace("/v1/chat/completions", "/health")) as resp:
                    if resp.status != 200:
                        logger.warning("vLLM health check failed, falling back to mock")
                        real_client = None
        except Exception as e:
            logger.warning(f"Failed to connect to vLLM: {e}, using mock client")
            real_client = None
    else:
        logger.info("Using MOCK LLM client (no actual LLM calls)")
        real_client = None

    mock_client = MockLLMClient(real_client=real_client)

    all_results = []

    for i, test in enumerate(test_queries):
        print(f"\n{'#' * 80}")
        print(f"TEST {i+1}: {test['name']}")
        print(f"Query: {test['query']}")
        print(f"Is Follow-up: {test['is_followup']}")
        print(f"{'#' * 80}")

        turn_number = latest_turn + i + 10  # Use high turn numbers to avoid conflicts

        # Test 2-phase
        results = await test_2phase(test["query"], turn_number, session_id, mock_client)

        # Print results
        print_results(results)

        all_results.append({
            "test": test,
            "turn_number": turn_number,
            "results": results
        })

    # Overall summary
    print("\n" + "=" * 80)
    print("OVERALL SUMMARY")
    print("=" * 80)

    total_tokens = sum(r["results"]["total_tokens"] for r in all_results)
    total_calls = sum(r["results"]["llm_calls"] for r in all_results)

    print(f"\nAcross {len(all_results)} tests:")
    print(f"  Total: {total_tokens} tokens, {total_calls} LLM calls")

    # Save results
    results_file = Path("panda_system_docs/test_results_context_gatherer_2phase.json")
    with open(results_file, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "use_real_llm": use_real_llm,
            "tests": all_results,
            "summary": {
                "total_tokens": total_tokens,
                "total_calls": total_calls
            }
        }, f, indent=2, default=str)

    print(f"\nResults saved to: {results_file}")

    return all_results


async def run_single_test(query: str, use_real_llm: bool = False):
    """Run a single test with specified query."""
    turns_dir = Path("panda_system_docs/turns")
    existing_turns = sorted(turns_dir.glob("turn_*"))
    if existing_turns:
        turn_number = int(existing_turns[-1].name.split("_")[1]) + 1
    else:
        turn_number = 1

    session_id = "test_single_query"

    if use_real_llm:
        try:
            real_client = RealLLMClient()
        except Exception as e:
            logger.warning(f"Failed to create real client: {e}")
            real_client = None
    else:
        real_client = None

    mock_client = MockLLMClient(real_client=real_client)

    print(f"\nQuery: {query}")
    print(f"Turn Number: {turn_number}")
    print(f"Using Real LLM: {use_real_llm}")

    # Test 2-phase
    results = await test_2phase(query, turn_number, session_id, mock_client)

    print_results(results)


def main():
    parser = argparse.ArgumentParser(description="Test 2-phase Context Gatherer")
    parser.add_argument("--query", "-q", type=str, help="Single query to test")
    parser.add_argument("--real", "-r", action="store_true", help="Use real LLM (requires vLLM running)")
    parser.add_argument("--suite", "-s", action="store_true", help="Run full test suite")

    args = parser.parse_args()

    if args.query:
        asyncio.run(run_single_test(args.query, use_real_llm=args.real))
    elif args.suite:
        asyncio.run(run_test_suite(use_real_llm=args.real))
    else:
        # Default: run suite with mock
        asyncio.run(run_test_suite(use_real_llm=args.real))


if __name__ == "__main__":
    main()

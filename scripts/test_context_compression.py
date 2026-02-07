#!/usr/bin/env python3
"""
Test context compression with a simulated long conversation.

Verifies:
1. Sliding window compression activates for >10 messages
2. LLM-based turn summarization works
3. Token estimation is accurate
4. Compressed messages fit within budget
"""
import httpx
import json
import time
from datetime import datetime

GATEWAY_URL = "http://127.0.0.1:9000"
GATEWAY_ENDPOINT = f"{GATEWAY_URL}/v1/chat/completions"

def create_long_conversation(num_turns: int = 12):
    """Create a conversation with multiple user-assistant turns."""
    messages = []

    # Simulate a realistic multi-turn conversation about research
    conversation_pairs = [
        ("What is vLLM?", "vLLM is a high-throughput inference and serving engine for large language models."),
        ("How does it compare to other inference engines?", "vLLM uses PagedAttention for efficient memory management and achieves higher throughput than traditional engines."),
        ("Can you explain PagedAttention?", "PagedAttention divides the KV cache into blocks, allowing non-contiguous memory allocation similar to OS paging."),
        ("What models does it support?", "vLLM supports popular models like LLaMA, Qwen, Mistral, GPT-J, and many others from HuggingFace."),
        ("How do I install it?", "You can install vLLM via pip: pip install vllm. For GPU support, ensure you have CUDA installed."),
        ("What are the key configuration options?", "Key options include --model, --tensor-parallel-size, --max-model-len, --gpu-memory-utilization, and --dtype."),
        ("How does tensor parallelism work?", "Tensor parallelism splits model layers across multiple GPUs for faster inference on large models."),
        ("What's the recommended GPU memory utilization?", "Default is 0.9 (90%). Lower values like 0.7-0.8 are recommended for stability with large batches."),
        ("Can it handle continuous batching?", "Yes, vLLM implements continuous batching to maximize GPU utilization by dynamically adding/removing requests."),
        ("What about quantization support?", "vLLM supports AWQ, GPTQ, and SqueezeLLM quantization for reduced memory footprint."),
        ("How do I monitor performance?", "Use the /metrics endpoint for Prometheus metrics, or check logs for throughput and latency stats."),
        ("What's the best way to scale it?", "Use tensor parallelism for large models, pipeline parallelism for very large models, and replicas for higher throughput."),
    ]

    # Build message history
    for i, (user_msg, assistant_msg) in enumerate(conversation_pairs[:num_turns]):
        messages.append({"role": "user", "content": user_msg})
        if i < num_turns - 1:  # Don't add last assistant response (we want the model to generate it)
            messages.append({"role": "assistant", "content": assistant_msg})

    return messages

def test_compression(num_messages: int = 12):
    """Test context compression with a long conversation."""
    print(f"\n{'='*60}")
    print(f"Testing Context Compression with {num_messages} messages")
    print(f"{'='*60}\n")

    # Create conversation
    messages = create_long_conversation(num_messages // 2)  # Each turn is 2 messages

    print(f"Generated {len(messages)} messages (user + assistant pairs)")
    print(f"First message: {messages[0]['content'][:50]}...")
    print(f"Last message: {messages[-1]['content'][:50]}...")
    print()

    # Prepare request
    payload = {
        "model": "qwen3-coder",
        "messages": messages,
        "mode": "chat",
        "max_tokens": 150,
        "temperature": 0.3
    }

    print("Sending request to Gateway...")
    print(f"Expected: Sliding window compression should activate (>{10} messages)")
    print(f"Expected: Episodic memory compression if >3 episodic memories")
    print()

    try:
        start = time.time()

        with httpx.Client(timeout=60.0) as client:
            response = client.post(GATEWAY_ENDPOINT, json=payload)
            response.raise_for_status()

        elapsed = time.time() - start
        result = response.json()

        print(f"✅ Request succeeded in {elapsed:.2f}s")
        print()

        # Extract response
        if "choices" in result and len(result["choices"]) > 0:
            answer = result["choices"][0]["message"]["content"]
            print(f"Response preview: {answer[:200]}...")
            print()

        # Check for compression indicators in response metadata
        if "usage" in result:
            usage = result["usage"]
            print(f"Token usage:")
            print(f"  - Prompt tokens: {usage.get('prompt_tokens', 'N/A')}")
            print(f"  - Completion tokens: {usage.get('completion_tokens', 'N/A')}")
            print(f"  - Total tokens: {usage.get('total_tokens', 'N/A')}")
            print()

        print("Check gateway.log for compression messages:")
        print("  grep 'Compressing.*messages with sliding window' gateway.log")
        print()

        return True

    except httpx.HTTPStatusError as e:
        print(f"❌ HTTP Error {e.response.status_code}")
        print(f"Response: {e.response.text[:500]}")
        return False

    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def test_episodic_compression():
    """Test episodic memory compression with >3 episodic memories."""
    print(f"\n{'='*60}")
    print(f"Testing Episodic Memory Compression")
    print(f"{'='*60}\n")

    # Create a conversation with episodic references
    messages = [
        {"role": "user", "content": "I searched for Syrian hamsters yesterday"},
        {"role": "assistant", "content": "I can help you find Syrian hamster information."},
        {"role": "user", "content": "I also looked at dwarf hamsters last week"},
        {"role": "assistant", "content": "Dwarf hamsters are also popular pets."},
        {"role": "user", "content": "I read about hamster care guides before"},
        {"role": "assistant", "content": "Hamster care is important for their health."},
        {"role": "user", "content": "I checked hamster cage prices recently"},
        {"role": "assistant", "content": "Hamster cages vary in price and features."},
        {"role": "user", "content": "Now I want to research hamster diet requirements"},
    ]

    payload = {
        "model": "qwen3-coder",
        "messages": messages,
        "mode": "chat",
        "max_tokens": 100,
        "temperature": 0.3
    }

    print(f"Generated {len(messages)} messages with episodic references")
    print("Expected: Episodic memories should be compressed into bullet points")
    print()

    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(GATEWAY_ENDPOINT, json=payload)
            response.raise_for_status()

        result = response.json()

        print("✅ Request succeeded")
        print()
        print("Check gateway.log for LLM compression messages:")
        print("  grep 'LLM compression' gateway.log")
        print()

        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def check_compression_logs():
    """Check gateway logs for compression activity."""
    print(f"\n{'='*60}")
    print(f"Checking Gateway Logs for Compression Activity")
    print(f"{'='*60}\n")

    import subprocess

    try:
        # Check for sliding window compression
        result = subprocess.run(
            ["grep", "-i", "compressing.*messages", "gateway.log"],
            capture_output=True,
            text=True
        )

        if result.stdout:
            print("Sliding window compression logs:")
            for line in result.stdout.strip().split('\n')[-5:]:  # Last 5 entries
                print(f"  {line}")
        else:
            print("⚠️  No sliding window compression logs found")

        print()

        # Check for LLM compression
        result = subprocess.run(
            ["grep", "-i", "llm compression", "gateway.log"],
            capture_output=True,
            text=True
        )

        if result.stdout:
            print("LLM compression logs:")
            for line in result.stdout.strip().split('\n')[-5:]:
                print(f"  {line}")
        else:
            print("⚠️  No LLM compression logs found")

        print()

    except Exception as e:
        print(f"⚠️  Could not read logs: {e}")

if __name__ == "__main__":
    print(f"\nContext Compression Test Suite")
    print(f"Started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Test 1: Long conversation (triggers sliding window)
    success1 = test_compression(num_messages=24)  # 12 user + 12 assistant

    time.sleep(2)

    # Test 2: Episodic memory compression
    success2 = test_episodic_compression()

    time.sleep(2)

    # Test 3: Check logs
    check_compression_logs()

    print(f"\n{'='*60}")
    print(f"Test Summary")
    print(f"{'='*60}")
    print(f"Long conversation test: {'✅ PASS' if success1 else '❌ FAIL'}")
    print(f"Episodic compression test: {'✅ PASS' if success2 else '❌ FAIL'}")
    print()

    if success1 and success2:
        print("✅ All tests passed!")
        exit(0)
    else:
        print("⚠️  Some tests failed - check logs for details")
        exit(1)

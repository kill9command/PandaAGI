#!/usr/bin/env python3
"""
Signal Bridge for Claude Code / Pandora

Listens for Signal messages and can forward them to:
- Claude Code (via file-based injection)
- Pandora Gateway (via HTTP API)

Usage:
    python bridge.py --mode echo      # Test mode: echo messages back
    python bridge.py --mode claude    # Forward to Claude Code
    python bridge.py --mode pandora   # Forward to Pandora Gateway
"""

import subprocess
import json
import argparse
import time
import sys
import os
from pathlib import Path
from typing import Optional
import signal as sig

# Configuration
SIGNAL_CLI = Path.home() / ".local/bin/signal-cli"
ACCOUNT = "+19857207420"  # Your linked Signal number
ALLOWED_SENDERS = ["+19857207420"]  # Only accept from these numbers

# Claude Code integration paths
CLAUDE_INPUT = Path.home() / ".claude/signal_input.txt"
CLAUDE_OUTPUT = Path.home() / ".claude/signal_output.txt"

# Pandora Gateway
PANDORA_URL = "http://127.0.0.1:9000/chat"


def send_signal(recipient: str, message: str) -> bool:
    """Send a Signal message."""
    # Truncate long messages
    if len(message) > 4000:
        message = message[:3950] + "\n\n[truncated]"

    try:
        result = subprocess.run(
            [str(SIGNAL_CLI), "-a", ACCOUNT, "send", "-m", message, recipient],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0
    except Exception as e:
        print(f"Error sending message: {e}")
        return False


def receive_messages() -> list[dict]:
    """Receive pending Signal messages."""
    try:
        result = subprocess.run(
            [str(SIGNAL_CLI), "-a", ACCOUNT, "-o", "json", "receive", "-t", "1"],
            capture_output=True,
            text=True,
            timeout=30
        )

        messages = []
        for line in result.stdout.strip().split('\n'):
            if line:
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return messages
    except Exception as e:
        print(f"Error receiving messages: {e}")
        return []


def extract_message_text(msg: dict) -> Optional[tuple[str, str]]:
    """Extract sender and text from a Signal message."""
    envelope = msg.get("envelope", {})
    source = envelope.get("source") or envelope.get("sourceNumber")

    # Check for regular message
    data_message = envelope.get("dataMessage", {})
    text = data_message.get("message")

    # Check for sync message (sent from another device)
    if not text:
        sync = envelope.get("syncMessage", {})
        sent = sync.get("sentMessage", {})
        text = sent.get("message")
        # For sync messages, the destination is who we sent to
        if text:
            source = sent.get("destination") or sent.get("destinationNumber")

    if text and source:
        return source, text
    return None


def handle_echo(sender: str, text: str):
    """Echo mode: just send the message back."""
    response = f"Echo: {text}"
    send_signal(sender, response)
    print(f"  Echoed back to {sender}")


def handle_claude(sender: str, text: str):
    """Forward to Claude Code via file injection."""
    # This is a placeholder - actual Claude Code integration
    # would require hooks or a different mechanism
    print(f"  Would forward to Claude Code: {text[:50]}...")

    # For now, acknowledge receipt
    send_signal(sender, f"Received for Claude: {text[:50]}...")

    # TODO: Implement actual Claude Code injection
    # Options:
    # 1. Write to a file that a VSCode extension watches
    # 2. Use Claude Code's stdin if running interactively
    # 3. Use an API if Claude Code exposes one


def handle_pandora(sender: str, text: str):
    """Forward to Pandora Gateway."""
    import httpx

    send_signal(sender, f"Processing: {text[:50]}...")

    try:
        with httpx.Client(timeout=120.0) as client:
            response = client.post(
                PANDORA_URL,
                json={
                    "query": text,
                    "user_id": sender,
                    "channel": "signal"
                }
            )
            result = response.json()

        reply = result.get("response", "No response from Pandora")
        send_signal(sender, reply)
        print(f"  Pandora responded with {len(reply)} chars")

    except Exception as e:
        error_msg = f"Error calling Pandora: {e}"
        send_signal(sender, error_msg)
        print(f"  {error_msg}")


def main():
    parser = argparse.ArgumentParser(description="Signal Bridge")
    parser.add_argument(
        "--mode",
        choices=["echo", "claude", "pandora"],
        default="echo",
        help="Operation mode"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process messages once and exit (don't loop)"
    )
    args = parser.parse_args()

    handlers = {
        "echo": handle_echo,
        "claude": handle_claude,
        "pandora": handle_pandora,
    }
    handler = handlers[args.mode]

    print(f"Signal Bridge started in {args.mode} mode")
    print(f"Account: {ACCOUNT}")
    print(f"Allowed senders: {ALLOWED_SENDERS}")
    print("Listening for messages... (Ctrl+C to stop)")
    print()

    # Handle Ctrl+C gracefully
    def signal_handler(signum, frame):
        print("\nShutting down...")
        sys.exit(0)

    sig.signal(sig.SIGINT, signal_handler)
    sig.signal(sig.SIGTERM, signal_handler)

    while True:
        messages = receive_messages()

        for msg in messages:
            extracted = extract_message_text(msg)
            if not extracted:
                continue

            sender, text = extracted

            # Security: only accept from allowed senders
            if sender not in ALLOWED_SENDERS:
                print(f"Ignoring message from {sender} (not in allowed list)")
                continue

            print(f"[{time.strftime('%H:%M:%S')}] From {sender}: {text[:100]}")
            handler(sender, text)

        if args.once:
            break

        # Poll every 2 seconds
        time.sleep(2)


if __name__ == "__main__":
    main()

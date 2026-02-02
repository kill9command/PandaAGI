#!/usr/bin/env python3
"""
Email Bridge for Claude Code / Pandora

Monitors an email inbox and forwards messages to Claude Code or Pandora.
Sends responses back as email replies.

Setup for Gmail:
1. Go to Google Account → Security → 2-Step Verification (enable if not already)
2. Go to Google Account → Security → App passwords
3. Generate an app password for "Mail"
4. Use that password in EMAIL_PASSWORD below

Usage:
    python email_bridge.py --mode echo      # Test mode: echo emails back
    python email_bridge.py --mode claude    # Forward to Claude Code
    python email_bridge.py --mode pandora   # Forward to Pandora Gateway
"""

import imaplib
import smtplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
import argparse
import time
import sys
import os
import re
import signal as sig
from typing import Optional
from dataclasses import dataclass

# ============================================================================
# CONFIGURATION - Update these values
# ============================================================================

# Email account to monitor
EMAIL_ADDRESS = os.getenv("CLAUDE_EMAIL", "")  # e.g., "your.email@gmail.com"
EMAIL_PASSWORD = os.getenv("CLAUDE_EMAIL_PASSWORD", "")  # App password, not regular password

# IMAP settings (Gmail defaults)
IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.gmail.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))

# SMTP settings (Gmail defaults)
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

# Security: Only process emails from these addresses
ALLOWED_SENDERS = os.getenv("ALLOWED_EMAIL_SENDERS", "").split(",")

# Folder to monitor
INBOX_FOLDER = "INBOX"

# Subject prefix to identify Claude commands (optional filter)
COMMAND_PREFIX = os.getenv("EMAIL_COMMAND_PREFIX", "")  # e.g., "[claude]" or leave empty for all

# Pandora Gateway
PANDORA_URL = "http://127.0.0.1:9000/chat"

# ============================================================================


@dataclass
class EmailMessage:
    """Parsed email message."""
    message_id: str
    from_addr: str
    subject: str
    body: str
    date: str


def connect_imap() -> imaplib.IMAP4_SSL:
    """Connect to IMAP server."""
    mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    mail.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
    return mail


def send_email(to_addr: str, subject: str, body: str, in_reply_to: str = None):
    """Send an email reply."""
    msg = MIMEMultipart()
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = to_addr
    msg["Subject"] = f"Re: {subject}" if not subject.startswith("Re:") else subject

    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to

    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False


def decode_mime_header(header: str) -> str:
    """Decode MIME encoded header."""
    if not header:
        return ""
    decoded_parts = decode_header(header)
    result = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(part)
    return "".join(result)


def extract_email_body(msg: email.message.Message) -> str:
    """Extract plain text body from email."""
    body = ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))

            if content_type == "text/plain" and "attachment" not in content_disposition:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    body = payload.decode(charset, errors="replace")
                    break
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            body = payload.decode(charset, errors="replace")

    # Clean up the body - remove quoted replies
    lines = body.split("\n")
    cleaned_lines = []
    for line in lines:
        # Stop at quoted reply markers
        if line.startswith(">") or line.startswith("On ") and " wrote:" in line:
            break
        cleaned_lines.append(line)

    return "\n".join(cleaned_lines).strip()


def get_sender_email(from_header: str) -> str:
    """Extract email address from From header."""
    # Handle "Name <email@example.com>" format
    match = re.search(r'<([^>]+)>', from_header)
    if match:
        return match.group(1).lower()
    return from_header.lower().strip()


def fetch_unread_emails(mail: imaplib.IMAP4_SSL) -> list[EmailMessage]:
    """Fetch unread emails from inbox."""
    mail.select(INBOX_FOLDER)

    # Search for unread emails
    status, messages = mail.search(None, "UNSEEN")
    if status != "OK":
        return []

    email_ids = messages[0].split()
    emails = []

    for email_id in email_ids:
        status, msg_data = mail.fetch(email_id, "(RFC822)")
        if status != "OK":
            continue

        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        from_addr = get_sender_email(decode_mime_header(msg.get("From", "")))
        subject = decode_mime_header(msg.get("Subject", ""))
        message_id = msg.get("Message-ID", "")
        date = msg.get("Date", "")
        body = extract_email_body(msg)

        # Apply command prefix filter if set
        if COMMAND_PREFIX and not subject.lower().startswith(COMMAND_PREFIX.lower()):
            # Mark as read but skip processing
            mail.store(email_id, "+FLAGS", "\\Seen")
            continue

        emails.append(EmailMessage(
            message_id=message_id,
            from_addr=from_addr,
            subject=subject,
            body=body,
            date=date
        ))

    return emails


def handle_echo(msg: EmailMessage) -> str:
    """Echo mode: return the email content."""
    return f"Echo received!\n\nSubject: {msg.subject}\n\nBody:\n{msg.body}"


def handle_claude(msg: EmailMessage) -> str:
    """Forward to Claude Code."""
    # Placeholder - actual implementation depends on Claude Code integration
    return f"[Claude Mode - Not yet implemented]\n\nWould process: {msg.body[:200]}..."


def handle_pandora(msg: EmailMessage) -> str:
    """Forward to Pandora Gateway."""
    try:
        import httpx

        with httpx.Client(timeout=180.0) as client:
            response = client.post(
                PANDORA_URL,
                json={
                    "query": msg.body,
                    "user_id": msg.from_addr,
                    "channel": "email"
                }
            )
            result = response.json()

        return result.get("response", "No response from Pandora")

    except Exception as e:
        return f"Error calling Pandora: {e}"


def main():
    parser = argparse.ArgumentParser(description="Email Bridge for Claude/Pandora")
    parser.add_argument(
        "--mode",
        choices=["echo", "claude", "pandora"],
        default="echo",
        help="Operation mode"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process emails once and exit"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=10,
        help="Polling interval in seconds (default: 10)"
    )
    args = parser.parse_args()

    # Validate configuration
    if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
        print("ERROR: Email credentials not configured!")
        print()
        print("Set environment variables:")
        print("  export CLAUDE_EMAIL='your.email@gmail.com'")
        print("  export CLAUDE_EMAIL_PASSWORD='your-app-password'")
        print()
        print("For Gmail, generate an App Password at:")
        print("  https://myaccount.google.com/apppasswords")
        sys.exit(1)

    handlers = {
        "echo": handle_echo,
        "claude": handle_claude,
        "pandora": handle_pandora,
    }
    handler = handlers[args.mode]

    print(f"Email Bridge started in {args.mode} mode")
    print(f"Monitoring: {EMAIL_ADDRESS}")
    print(f"Allowed senders: {ALLOWED_SENDERS if ALLOWED_SENDERS[0] else 'ALL (not recommended)'}")
    if COMMAND_PREFIX:
        print(f"Command prefix: {COMMAND_PREFIX}")
    print(f"Polling interval: {args.interval}s")
    print("Listening for emails... (Ctrl+C to stop)")
    print()

    # Handle Ctrl+C
    def signal_handler(signum, frame):
        print("\nShutting down...")
        sys.exit(0)

    sig.signal(sig.SIGINT, signal_handler)
    sig.signal(sig.SIGTERM, signal_handler)

    while True:
        try:
            mail = connect_imap()
            emails = fetch_unread_emails(mail)

            for msg in emails:
                # Security check
                if ALLOWED_SENDERS[0] and msg.from_addr not in ALLOWED_SENDERS:
                    print(f"Ignoring email from {msg.from_addr} (not in allowed list)")
                    continue

                print(f"[{time.strftime('%H:%M:%S')}] From: {msg.from_addr}")
                print(f"  Subject: {msg.subject}")
                print(f"  Body: {msg.body[:100]}...")

                # Process and respond
                response = handler(msg)

                if send_email(msg.from_addr, msg.subject, response, msg.message_id):
                    print(f"  Replied with {len(response)} chars")
                else:
                    print(f"  Failed to send reply")

            mail.logout()

        except Exception as e:
            print(f"Error: {e}")

        if args.once:
            break

        time.sleep(args.interval)


if __name__ == "__main__":
    main()

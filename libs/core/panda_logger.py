"""PandaAI Centralized Logger - Captures everything for debugging.

This logger captures all system activity including:
- All 8 phases of the pipeline (1, 2.1, 2.2, 3, 4, 5, 6, 7, 8)
- LLM calls (prompts, responses, tokens)
- Tool executions
- Internet research (broad search, deep dive)
- Browser activity
- Final responses
- Errors and warnings

Usage:
    from libs.core.panda_logger import plog

    plog.phase_start(0, "query_analyzer", query)
    plog.llm_call("mind", prompt, response, tokens)
    plog.phase_end(0, result)
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


class PandaLogger:
    """Centralized logger for all PandaAI activity."""

    _instance: Optional["PandaLogger"] = None

    def __init__(self):
        self.log_dir = Path("logs/panda")
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Create log file with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = self.log_dir / f"panda_{timestamp}.log"
        self.latest_file = self.log_dir / "latest.log"

        # Track current turn/session
        self.current_turn: Optional[int] = None
        self.current_query: Optional[str] = None
        self.current_user: Optional[str] = None
        self.turn_start_time: Optional[datetime] = None

        # Stats for summary
        self.stats = {
            "llm_calls": 0,
            "llm_tokens": 0,
            "tool_calls": 0,
            "errors": 0,
            "phases_completed": [],
        }

        self._write_header()

    @classmethod
    def get(cls) -> "PandaLogger":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = PandaLogger()
        return cls._instance

    @classmethod
    def reset(cls):
        """Reset for new session."""
        if cls._instance:
            cls._instance._write_summary()
        cls._instance = None

    def _write_header(self):
        """Write log header."""
        with open(self.log_file, "w") as f:
            f.write("=" * 100 + "\n")
            f.write(f"PANDAAI SYSTEM LOG - {datetime.now().isoformat()}\n")
            f.write("=" * 100 + "\n\n")
        self._update_latest()

    def _update_latest(self):
        """Update latest.log symlink."""
        try:
            import shutil
            shutil.copy(self.log_file, self.latest_file)
        except Exception:
            pass

    def _write(self, text: str, also_print: bool = True):
        """Write to log file."""
        with open(self.log_file, "a") as f:
            f.write(text)
        self._update_latest()
        if also_print:
            # Print to console (strip some formatting for readability)
            print(text.rstrip())

    def _log(self, level: str, component: str, message: str, data: Any = None, print_console: bool = True):
        """Core logging method."""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        # Build log entry
        entry = f"[{timestamp}] [{level:5}] [{component:20}] {message}\n"

        if data is not None:
            if isinstance(data, (dict, list)):
                try:
                    data_str = json.dumps(data, indent=2, default=str)
                    # Indent data
                    data_str = "\n".join("    " + line for line in data_str.split("\n"))
                    entry += data_str + "\n"
                except Exception:
                    entry += f"    {data}\n"
            else:
                entry += f"    {data}\n"

        self._write(entry, also_print=print_console)

    # === Basic logging methods ===

    def info(self, component: str, message: str, data: Any = None):
        self._log("INFO", component, message, data)

    def debug(self, component: str, message: str, data: Any = None):
        self._log("DEBUG", component, message, data, print_console=False)

    def warn(self, component: str, message: str, data: Any = None):
        self._log("WARN", component, message, data)

    def error(self, component: str, message: str, data: Any = None):
        self.stats["errors"] += 1
        self._log("ERROR", component, message, data)

    # === Turn/Session tracking ===

    def turn_start(self, turn_number: int, query: str, user: str = "default"):
        """Log start of a new turn."""
        self.current_turn = turn_number
        self.current_query = query
        self.current_user = user
        self.turn_start_time = datetime.now()
        self.stats = {
            "llm_calls": 0,
            "llm_tokens": 0,
            "tool_calls": 0,
            "errors": 0,
            "phases_completed": [],
        }

        self._write("\n" + "=" * 100 + "\n")
        self._write(f"TURN {turn_number} START - User: {user}\n")
        self._write(f"Query: {query}\n")
        self._write(f"Time: {self.turn_start_time.isoformat()}\n")
        self._write("=" * 100 + "\n\n")

    def turn_end(self, success: bool, response: str = None):
        """Log end of turn."""
        elapsed = (datetime.now() - self.turn_start_time).total_seconds() if self.turn_start_time else 0

        self._write("\n" + "-" * 100 + "\n")
        self._write(f"TURN {self.current_turn} END - {'SUCCESS' if success else 'FAILED'}\n")
        self._write(f"Elapsed: {elapsed:.2f}s\n")
        self._write(f"LLM Calls: {self.stats['llm_calls']} ({self.stats['llm_tokens']} tokens)\n")
        self._write(f"Tool Calls: {self.stats['tool_calls']}\n")
        self._write(f"Phases: {self.stats['phases_completed']}\n")
        self._write(f"Errors: {self.stats['errors']}\n")

        if response:
            self._write("\n--- FINAL RESPONSE ---\n")
            self._write(response[:2000] + ("..." if len(response) > 2000 else "") + "\n")
            self._write("--- END RESPONSE ---\n")

        self._write("-" * 100 + "\n\n")

    # === Phase tracking ===

    def phase_start(self, phase_num: int, phase_name: str, input_data: Any = None):
        """Log phase start."""
        self._write(f"\n{'─' * 80}\n")
        self._log("INFO", f"Phase{phase_num}:{phase_name}", f"STARTING")
        if input_data:
            self._log("DEBUG", f"Phase{phase_num}", "Input:", input_data)

    def phase_end(self, phase_num: int, phase_name: str, output_data: Any = None, elapsed_ms: float = None):
        """Log phase end."""
        self.stats["phases_completed"].append(phase_name)
        elapsed_str = f" ({elapsed_ms:.0f}ms)" if elapsed_ms else ""
        self._log("INFO", f"Phase{phase_num}:{phase_name}", f"COMPLETED{elapsed_str}")
        if output_data:
            self._log("DEBUG", f"Phase{phase_num}", "Output:", output_data)
        self._write(f"{'─' * 80}\n")

    def phase_error(self, phase_num: int, phase_name: str, error: str):
        """Log phase error."""
        self.error(f"Phase{phase_num}:{phase_name}", f"FAILED: {error}")

    # === LLM tracking ===

    def llm_call(self, role: str, prompt: str, response: str = None,
                 tokens_in: int = 0, tokens_out: int = 0, elapsed_ms: float = None):
        """Log an LLM call."""
        self.stats["llm_calls"] += 1
        self.stats["llm_tokens"] += tokens_in + tokens_out

        elapsed_str = f" ({elapsed_ms:.0f}ms)" if elapsed_ms else ""
        tokens_str = f" [{tokens_in}→{tokens_out} tokens]" if tokens_in or tokens_out else ""

        self._log("INFO", f"LLM:{role}", f"Call{elapsed_str}{tokens_str}")

        # Log prompt (truncated)
        prompt_preview = prompt[:500] + "..." if len(prompt) > 500 else prompt
        self._log("DEBUG", f"LLM:{role}", f"Prompt: {prompt_preview}")

        # Log response (truncated)
        if response:
            response_preview = response[:500] + "..." if len(response) > 500 else response
            self._log("DEBUG", f"LLM:{role}", f"Response: {response_preview}")

    # === Tool tracking ===

    def tool_call(self, tool_name: str, params: dict = None):
        """Log tool call start."""
        self.stats["tool_calls"] += 1
        self._log("INFO", f"Tool:{tool_name}", "Calling", params)

    def tool_result(self, tool_name: str, result: Any = None, error: str = None):
        """Log tool result."""
        if error:
            self.error(f"Tool:{tool_name}", f"Failed: {error}")
        else:
            self._log("INFO", f"Tool:{tool_name}", "Completed", result)

    # === Research tracking ===

    def research_start(self, query: str):
        """Log research start."""
        self._write(f"\n{'═' * 80}\n")
        self._write("INTERNET RESEARCH\n")
        self._write(f"{'═' * 80}\n")
        self._log("INFO", "Research", f"Starting: {query}")

    def research_phase1(self, action: str, data: Any = None):
        """Log Phase 1 research activity."""
        self._log("INFO", "Research:Phase1", action, data)

    def research_phase2(self, action: str, data: Any = None):
        """Log Phase 2 research activity."""
        self._log("INFO", "Research:Phase2", action, data)

    def research_end(self, success: bool, summary: dict = None):
        """Log research end."""
        status = "SUCCESS" if success else "FAILED"
        self._log("INFO", "Research", f"Completed: {status}", summary)
        self._write(f"{'═' * 80}\n\n")

    # === Browser tracking ===

    def browser(self, action: str, data: Any = None):
        """Log browser activity."""
        self._log("INFO", "Browser", action, data)

    def browser_navigate(self, url: str):
        """Log navigation."""
        self._log("DEBUG", "Browser", f"Navigate: {url[:80]}")

    def browser_search(self, engine: str, query: str, results_count: int = 0):
        """Log search."""
        self._log("INFO", "Browser", f"Search [{engine}]: {query} → {results_count} results")

    # === Summary ===

    def _write_summary(self):
        """Write session summary."""
        self._write("\n" + "=" * 100 + "\n")
        self._write("SESSION SUMMARY\n")
        self._write(f"Total LLM Calls: {self.stats['llm_calls']}\n")
        self._write(f"Total Tokens: {self.stats['llm_tokens']}\n")
        self._write(f"Total Tool Calls: {self.stats['tool_calls']}\n")
        self._write(f"Total Errors: {self.stats['errors']}\n")
        self._write("=" * 100 + "\n")


# Global singleton accessor
def get_panda_logger() -> PandaLogger:
    """Get the PandaAI logger instance."""
    return PandaLogger.get()


# Convenience alias
plog = get_panda_logger()

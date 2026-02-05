# conftest.py
# Ensure the repository root is on sys.path so pytest can import both
# top-level packages (e.g. orchestrator) and package-style imports
# (e.g. apps.services.gateway) consistently.
#
# This file is intentionally minimal and safe for test environments.

import os
import sys
from pathlib import Path

# conftest is at: apps/tests/conftest.py
# Walk up two levels to reach the repository root.
ROOT = Path(__file__).resolve().parents[2]
ROOT_STR = str(ROOT)

if ROOT_STR not in sys.path:
    # Insert at front so repo root takes precedence during imports
    sys.path.insert(0, ROOT_STR)

#!/usr/bin/env python3
"""Utility script to download historical season data (alias for download_historical.py)."""

import sys
from pathlib import Path

# Ensure scripts and src directories are in sys.path when executed directly
SCRIPTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPTS_DIR.parent
SRC_DIR = PROJECT_ROOT / "src"

for d in (str(SCRIPTS_DIR), str(SRC_DIR)):
    if d not in sys.path:
        sys.path.insert(0, d)

from download_historical import main

if __name__ == "__main__":
    main()

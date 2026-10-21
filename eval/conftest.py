"""Expose only the canonical first-party source root for pytest discovery."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "python"))

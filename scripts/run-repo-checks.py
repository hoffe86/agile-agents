#!/usr/bin/env python3
"""Compose this repository's offline test-bar commands without shell chaining.

Run from the repository root with the Python environment containing
eval/deepeval/requirements.lock.txt installed with --require-hashes (see its README).
Every child uses that same interpreter; CPython 3.11 developer checks remain valid.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def commands_for(check: str) -> list[list[str]]:
    python = sys.executable
    if check == "lint":
        return [
            [python, "scripts/check-skill-frontmatter.py"],
            [python, "scripts/check-skill-frontmatter.py", "--self-test"],
            ["pwsh", "-NoProfile", "-File", "scripts/audit-references.ps1"],
            [python, "scripts/check-instructions-drift.py"],
            [python, "scripts/check-instructions-drift.py", "--self-test"],
            ["pwsh", "-NoProfile", "-File", "scripts/check-plugin-versions.ps1"],
        ]
    if check == "unit":
        return [
            [python, "-m", "pip", "check"],
            [python, "eval/deepeval/check_environment.py"],
            [python, "-m", "unittest", "discover", "-s", "eval/pipeline/tests",
             "-p", "test_dependency_environment.py", "-v"],
            [python, "-m", "unittest", "discover", "-s", "scripts/tests",
             "-p", "test_*.py", "-v"],
            [python, "-m", "unittest", "discover", "-s", "eval/pipeline/tests",
             "-p", "test_eval_pipeline_workflow.py", "-v"],
            [python, "-m", "unittest", "discover", "-s", "eval/pipeline/tests",
             "-p", "test_authorization.py", "-v"],
            [python, "-m", "unittest", "discover", "-s", "eval/pipeline/trajectory",
             "-p", "test_check_trajectory.py", "-v"],
            [python, "-m", "pytest", "-q", "eval/pipeline/custom-eval/tests",
             "eval/deepeval/tests"],
        ]
    raise ValueError(f"unknown check: {check}")


def run_commands(commands: list[list[str]]) -> int:
    for command in commands:
        print("+ " + subprocess.list2cmdline(command), flush=True)
        try:
            result = subprocess.run(command, cwd=ROOT, check=False)
        except OSError as exc:
            print(f"error: could not execute {command[0]!r}: {exc}", file=sys.stderr)
            return 1
        if result.returncode:
            print(f"error: command failed (exit {result.returncode})", file=sys.stderr)
            return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("check", choices=("lint", "unit"))
    args = parser.parse_args()
    return run_commands(commands_for(args.check))


if __name__ == "__main__":
    raise SystemExit(main())

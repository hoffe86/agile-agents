"""Report skill invocation across Copilot CLI run logs.

Answers the question ADR 0015 was written to make measurable: when a task required a
skill, did the agent actually invoke it, or did it work from priors?

    python eval/deepeval/report_skill_usage.py eval/pipeline/runs

Runs offline with no credentials -- the measurement is derived from the logs alone.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _console import use_utf8_stdio  # noqa: E402
from adapters.copilot_trace import parse_log, verify_schema  # noqa: E402

use_utf8_stdio()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", nargs="?", default="eval/pipeline/runs",
                    help="directory of run logs, or a single .log file")
    ap.add_argument("--expect-skill", action="append", default=[],
                    help="skill that should have been invoked; repeatable")
    args = ap.parse_args()

    root = Path(args.path)
    if root.is_file():
        logs = [root]
    else:
        # The isolated config root lives under the run directory and keeps its own CLI
        # process logs. Those are not session transcripts, and scanning them raises a
        # spurious schema-drift alarm that masks the real result.
        logs = sorted(
            p for p in root.rglob("*.log")
            if ".copilot-home" not in p.parts and ".copilot" not in p.parts
        )
    if not logs:
        print(f"no logs found under {root}")
        return 1

    drifted = False
    bypassed = False

    for log in logs:
        trace = parse_log(log)
        problems = verify_schema(trace)

        print(f"\n{log.parent.name}/{log.name}")
        print(f"  events={trace.events_parsed}  turns={trace.turns}  tools={len(trace.tools)}")
        print(f"  skills offered: {len(trace.skills_offered)}")
        print(f"  skills invoked: {', '.join(trace.skills_invoked) or '(none)'}")

        if problems:
            drifted = True
            for p in problems:
                print(f"  SCHEMA: {p}")

        for expected in args.expect_skill:
            hit = expected in trace.skills_invoked
            print(f"  expected '{expected}': {'INVOKED' if hit else 'BYPASSED'}")
            if not hit:
                bypassed = True

    # A schema problem is a harness fault and must not read as an agent result.
    if drifted:
        print("\nSCHEMA DRIFT DETECTED - results above understate tool use; fix the adapter first.")
        return 2
    if bypassed:
        print("\nAt least one expected skill was bypassed.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Grade a produced workspace against a task's acceptance criteria.

A drop-in replacement for `score-judge.{sh,ps1}` with the same exit-code contract, so it
can be A/B'd against them before anything is cut over:

    0  resolved      2  partial      1  failed

    python eval/deepeval/score_workspace.py <workspace> <acceptance.md> [--isolated-home DIR]
    python eval/deepeval/score_workspace.py --self-test

`--self-test` runs the verdict parser against the same cases the shell twins self-test,
with no CLI call and no network, so the contract can be checked on a bare machine.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _console import use_utf8_stdio  # noqa: E402

use_utf8_stdio()

from metrics.acceptance import (  # noqa: E402
    VERDICT_EXIT,
    discover_plugin_dirs,
    parse_verdict,
    run_judge,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# Identical to score-judge.sh --self-test, so a divergence shows up here rather than as a
# quietly different score after a migration.
SELF_TEST_CASES = [
    (0, "1. PASS - ok\nVERDICT: RESOLVED"),
    (2, "VERDICT: PARTIAL\n"),
    (1, "VERDICT: FAILED"),
    (1, "no verdict here"),
    (1, "VERDICT: RESOLVED\nVERDICT: FAILED"),
    (0, "verdict: resolved"),
]


def self_test() -> int:
    ok = True
    for want, text in SELF_TEST_CASES:
        got = VERDICT_EXIT[parse_verdict(text)]
        if got != want:
            print(f"FAIL: want {want} got {got} for: {text!r}")
            ok = False
    print("score_workspace self-test: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("workspace", nargs="?")
    ap.add_argument("acceptance", nargs="?")
    ap.add_argument("--isolated-home", default=None,
                    help="Redirect HOME/USERPROFILE so plugins resolve only from --plugin-dir.")
    ap.add_argument("--model", default=os.environ.get("JUDGE_MODEL"),
                    help="Judge model. Should differ from the model that produced the work.")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if not args.workspace or not args.acceptance:
        ap.error("workspace and acceptance are required (or use --self-test)")

    acceptance = Path(args.acceptance)
    if not acceptance.is_file():
        print(f"[judge] missing acceptance: {acceptance}")
        return 1

    plugin_dirs = discover_plugin_dirs(REPO_ROOT)
    if not plugin_dirs:
        # Without these the judge cannot load acceptance-grading and would grade from its
        # own priors — a silent quality collapse that still emits a plausible verdict.
        print("[judge] no plugin dirs found — the judge cannot load acceptance-grading.")
        return 1

    result = run_judge(
        args.workspace, acceptance,
        plugin_dirs=plugin_dirs,
        model=args.model,
        isolated_home=args.isolated_home,
    )

    print(f"[judge] model: {args.model or '(cli default)'}")
    print("[judge] ----- response -----")
    print(result.response)
    print("[judge] ----------------------")

    if result.unverified:
        print(
            "[judge] WARNING: at least one criterion was UNVERIFIED. That is the harness "
            "failing to show the judge evidence, not an agent result — this score "
            "understates the agent.",
            file=sys.stderr,
        )

    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())

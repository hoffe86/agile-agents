"""Return fail-closed offline grading status for a produced workspace.

No judge is invoked and no workspace content is executed until OS isolation exists.
The shared exit-code contract remains:

    0 resolved / 1 failed / 2 partial / 3 unverified / 4 setup or judge error

    python eval/deepeval/score_workspace.py <workspace> <acceptance.md>
    python eval/deepeval/score_workspace.py --self-test

`--self-test` runs the shared verdict parser,
with no CLI call and no network, so the contract can be checked on a bare machine.
"""

from __future__ import annotations

import os
import sys

from pathlib import Path

from agile_eval.grading import (
    GradingArgumentParser, held_workspace_result, self_test,
)
from agile_eval.provenance import write_result

def main() -> int:
    ap = GradingArgumentParser(description=__doc__)
    ap.add_argument("workspace", nargs="?")
    ap.add_argument("acceptance", nargs="?")
    ap.add_argument("--isolated-home", default=None,
                    help="Redirect HOME/USERPROFILE so plugins resolve only from --plugin-dir.")
    ap.add_argument("--model", default=os.environ.get("JUDGE_MODEL"),
                    help="Judge model. Should differ from the model that produced the work.")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--result-json", help="Structured claimed/normalized verdict and verification.")
    ap.add_argument("--baseline-dir", help="Trusted immutable snapshot outside the workspace.")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--prompt-template", help="Historical option; held preflight renders no prompt.")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if not args.workspace or not args.acceptance:
        ap.error("workspace and acceptance are required (or use --self-test)")

    acceptance = Path(args.acceptance)
    result = held_workspace_result(args.workspace, acceptance, baseline_dir=args.baseline_dir)

    print(f"[judge] status: {result.verdict.value}")
    try:
        write_result(result, args.result_json, workspace=Path(args.workspace),
                     acceptance=acceptance, scorer="deepeval", judge_model=args.model)
    except (OSError, ValueError, KeyError, TypeError):
        print("provenance retention failed; result is unattributed", file=sys.stderr)
        return 4
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())

"""Return fail-closed offline grading status for a produced workspace.

No judge is invoked and no workspace content is executed until OS isolation exists.
The shared exit-code contract remains:

    0 resolved / 1 failed / 2 partial / 3 unverified / 4 setup or judge error

    python eval/deepeval/score_workspace.py <workspace> <acceptance.md>
    python eval/deepeval/score_workspace.py --self-test

`--self-test` runs the verdict parser against the same cases the shell twins self-test,
with no CLI call and no network, so the contract can be checked on a bare machine.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _console import use_utf8_stdio  # noqa: E402

use_utf8_stdio()

from metrics.acceptance import (  # noqa: E402
    discover_plugin_dirs,
    run_judge,
)
from grading import GradingArgumentParser, environment_error, self_test, write_result  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]

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
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if not args.workspace or not args.acceptance:
        ap.error("workspace and acceptance are required (or use --self-test)")

    acceptance = Path(args.acceptance)
    plugin_dirs = discover_plugin_dirs(REPO_ROOT)
    if not plugin_dirs:
        # Without these the judge cannot load acceptance-grading and would grade from its
        # own priors — a silent quality collapse that still emits a plausible verdict.
        result = environment_error("no plugin dirs found; cannot load acceptance-grading", "setup")
    else:
        result = run_judge(
            args.workspace, acceptance,
            plugin_dirs=plugin_dirs,
            model=args.model,
            isolated_home=args.isolated_home,
            baseline_dir=args.baseline_dir,
            timeout=args.timeout,
        )

    print(f"[judge] status: {result.verdict.value}")
    write_result(result, args.result_json)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())

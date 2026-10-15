"""Fail-closed outcome scorer for both native shell entry points (no DeepEval import).

Live evaluation is disabled until the caller can enforce credential-free,
network-disabled OS isolation. This entry point invokes no model or host tools.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from grading import (  # noqa: E402
    GradingArgumentParser, acceptance_count, build_grading_prompt, environment_error, immutable_inputs,
    self_test, verification_disabled, write_result,
)


def build_judge_prompt(
    acceptance_text: str, artifacts: str, originals: str = "", *,
    plugin_dirs: list[str | Path] | None = None,
    prompt_template: Path | None = None,
) -> str:
    """Offline composition only; the live CLI below remains fail-closed."""
    return build_grading_prompt(
        acceptance_text, artifacts, originals,
        plugin_dirs=plugin_dirs, prompt_template=prompt_template,
    )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    ap = GradingArgumentParser(description=__doc__)
    ap.add_argument("workspace", nargs="?", type=Path)
    ap.add_argument("acceptance", nargs="?", type=Path)
    ap.add_argument("--prompt-template", type=Path,
                    default=Path(__file__).parent / "references/judge-prompt.md")
    ap.add_argument("--model", default=os.environ.get("JUDGE_MODEL", "gpt-5.6-sol"))
    ap.add_argument("--baseline-dir", type=Path)
    ap.add_argument("--result-json", type=Path)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not args.workspace or not args.acceptance:
        ap.error("workspace and acceptance are required")
    try:
        if not args.workspace.is_dir():
            raise ValueError("workspace does not exist")
        acceptance = args.acceptance.read_text(encoding="utf-8")
        expected = acceptance_count(acceptance)
        immutable_inputs(args.workspace, args.baseline_dir)
        result = verification_disabled(expected)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result = environment_error("evaluation inputs failed trusted-origin validation", "setup")
    try:
        write_result(result, args.result_json, workspace=args.workspace,
                     acceptance=args.acceptance, scorer="shell", judge_model=args.model)
    except (OSError, ValueError, KeyError, TypeError):
        print("provenance retention failed; result is unattributed", file=sys.stderr)
        return 4
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())

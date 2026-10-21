"""Shared offline prompt composition, held preflight, and grading CLI."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from agile_eval import grading_contract, provenance, workspace_inputs


def load_grading_doctrine(plugin_dirs: list[str | Path] | None = None) -> str:
    """Read the authoritative skill from explicit plugin roots, never ambient installs."""
    roots = plugin_dirs if plugin_dirs is not None else [
        Path(__file__).resolve().parents[3] / "plugins/agile-agents-core"
    ]
    skills = [
        Path(root) / "skills/acceptance-grading/SKILL.md" for root in roots
        if (Path(root) / "skills/acceptance-grading/SKILL.md").is_file()
    ]
    if len(skills) != 1:
        raise ValueError("exactly one acceptance-grading skill is required")
    return skills[0].read_text(encoding="utf-8")


def build_grading_prompt(
    acceptance_text: str, artifacts: str, originals: str = "", *,
    plugin_dirs: list[str | Path] | None = None,
    prompt_template: Path | None = None,
) -> str:
    """Compose both offline prompt paths; this does not authorize live execution.

    Include doctrine rather than assuming a Markdown path will be auto-loaded.
    Substitute once so placeholders in untrusted evidence are not interpreted.
    """
    template_path = prompt_template or (
        Path(__file__).resolve().parents[2] / "pipeline/references/judge-prompt.md"
    )
    template = template_path.read_text(encoding="utf-8")
    values = {
        "GRADING_DOCTRINE": load_grading_doctrine(plugin_dirs),
        "ACCEPTANCE": acceptance_text,
        "ARTIFACTS": artifacts,
        "ORIGINALS": originals or "(no declared immutable inputs)",
    }
    placeholders = re.findall(r"\{\{([A-Z_]+)\}\}", template)
    if sorted(placeholders) != sorted(values):
        raise ValueError("judge prompt requires doctrine and each evidence placeholder exactly once")
    return re.sub(r"\{\{([A-Z_]+)\}\}", lambda match: values[match[1]], template)


def held_workspace_result(
    workspace: str | Path, acceptance_path: str | Path, *,
    baseline_dir: str | Path | None = None, **_unused,
) -> grading_contract.JudgeResult:
    """One trusted-input preflight for CLI and native metrics; never invokes a judge."""
    try:
        workspace_path = Path(workspace)
        if not workspace_path.is_dir():
            raise ValueError("workspace does not exist")
        expected = grading_contract.acceptance_count(Path(acceptance_path).read_text(encoding="utf-8"))
        workspace_inputs.immutable_inputs(workspace_path, baseline_dir)
    except (OSError, ValueError, KeyError, TypeError):
        return grading_contract.environment_error("evaluation inputs failed trusted-origin validation", "setup")
    return grading_contract.verification_disabled(expected)


SELF_TEST_CASES = [
    (0, "1. PASS - ok\nVERDICT: RESOLVED"),
    (2, "1. PASS - ok\n2. FAIL - missing\nVERDICT: PARTIAL"),
    (1, "1. FAIL - broken\nVERDICT: FAILED"),
    (4, "no verdict here"),
    (4, "1. PASS - ok\nVERDICT: RESOLVED\nVERDICT: FAILED"),
    (0, "1. pass - ok\nverdict: resolved"),
    (3, "1. UNVERIFIED - tool missing\nVERDICT: RESOLVED"),
]


def self_test() -> int:
    for want, text in SELF_TEST_CASES:
        result = grading_contract.parse_result(text, 2 if text.startswith("1. PASS - ok\n2.") else 1)
        assert result.exit_code == want, (want, result.to_dict())
    print("grading contract self-test: PASS")
    return 0


class GradingArgumentParser(argparse.ArgumentParser):
    """Bad scorer arguments are setup errors, never legacy PARTIAL exit 2."""

    def error(self, message: str) -> None:
        result = grading_contract.environment_error(message, "setup")
        provenance.write_result(result, None)
        self.exit(result.exit_code, f"{self.prog}: {message}\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--result-status", type=Path)
    ap.add_argument("--exit-code", type=int, default=4)
    ap.add_argument("--acceptance", type=Path)
    ap.add_argument("--run-dir", type=Path)
    ap.add_argument("--expected-context")
    ap.add_argument("--task-id", default="")
    ap.add_argument("--retained-result", type=Path)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        raise SystemExit(self_test())
    if args.result_status:
        try:
            context = provenance.load_expected(args.run_dir, args.expected_context) if args.run_dir else None
            print(provenance.credited_status(args.result_status, args.exit_code, args.acceptance,
                                            context, args.task_id))
        except (OSError, ValueError, KeyError, TypeError):
            print("setup_error")
    if args.retained_result:
        try:
            context = provenance.load_expected(args.run_dir, args.expected_context)
            print(json.dumps(provenance.retained_result(args.retained_result, context, args.task_id,
                                                       args.acceptance)))
        except (OSError, ValueError, KeyError, TypeError):
            print("null")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

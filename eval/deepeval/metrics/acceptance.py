"""Offline outcome contract as a DeepEval metric.

The outcome contract is shared with the shell twins in eval/grading.py. Live
grading is disabled until real OS isolation exists; measurements return UNVERIFIED.

Two things differ from the shell judge, both deliberate:

**Orientation is an index instead of an inlined dump.** Both prompt paths use the shared
offline renderer, which includes the authoritative `acceptance-grading` skill. Listings
are orientation only; neither truncation nor absence from a listing proves absence.

**Doctrine lives in the skill, not in this file.** `acceptance-grading` defines
verify-don't-infer, the verified OS-worker prerequisite (never execute on the host or
repair what you grade), convention ownership, and PASS / FAIL / UNVERIFIED. This module
only wires it up. Live grading remains disabled.
"""

from __future__ import annotations

from importlib.util import find_spec
import subprocess
import sys
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from grading import (  # noqa: E402
    VERDICT_EXIT, VERDICT_SCORE, JudgeResult, Verdict, acceptance_count,
    build_grading_prompt, environment_error, gradable_files, has_unverified, immutable_inputs,
    parse_result, parse_verdict, verification_disabled,
)

from .local_model import configure_offline

configure_offline()


def workspace_index(workspace: str | Path, max_entries: int = 200) -> str:
    """A file listing for orientation — deliberately not file contents.

    Kept for offline orientation tests; it is not passed to a live judge.
    """
    root = Path(workspace)
    if not root.is_dir():
        return "(workspace does not exist)"

    entries: list[str] = []
    truncated = False
    for path in gradable_files(root):
        rel_parts = path.relative_to(root).parts
        if len(entries) >= max_entries:
            truncated = True
            break
        entries.append("/".join(rel_parts))

    if not entries:
        return "(no gradable files)"
    listing = "\n".join(f"- {e}" for e in entries)
    if truncated:
        listing += f"\n- …listing capped at {max_entries}; the workspace has more"
    return listing


def build_judge_prompt(
    acceptance_text: str, index: str, originals: str = "", *,
    plugin_dirs: list[str | Path] | None = None,
) -> str:
    """Offline prompt shim; doctrine is included from the selected core plugin."""
    return build_grading_prompt(
        acceptance_text, index, originals, plugin_dirs=plugin_dirs,
    )


def discover_plugin_dirs(repo_root: str | Path) -> list[str]:
    """Plugin folders to hand the judge.

    Without these the judge cannot load `acceptance-grading`, nor the skills that own this
    repo's conventions — and would fall back to whatever the acceptance wording happens to
    restate. That is how a task came to be graded against a definition of MADR that
    upstream MADR does not use.
    """
    plugins = Path(repo_root) / "plugins"
    if not plugins.is_dir():
        return []
    return [str(p) for p in sorted(plugins.glob("agile-agents*")) if p.is_dir()]


def run_judge(
    workspace: str | Path,
    acceptance_path: str | Path,
    *,
    plugin_dirs: Sequence[str] = (),
    model: str | None = None,
    isolated_home: str | Path | None = None,
    timeout: int = 900,
    baseline_dir: str | Path | None = None,
) -> JudgeResult:
    """Fail closed until live grading has a credential-free OS sandbox.

    Acceptance text, workspace content, baselines, and model responses stay local.
    """
    try:
        workspace_path = Path(workspace)
        if not workspace_path.is_dir():
            raise ValueError("workspace does not exist")
        acceptance_text = Path(acceptance_path).read_text(encoding="utf-8")
        expected = acceptance_count(acceptance_text)
        immutable_inputs(workspace_path, baseline_dir)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return environment_error("evaluation inputs failed trusted-origin validation", "setup")
    return verification_disabled(expected)


def _metric_base():
    """DeepEval's `BaseMetric` when available, else `object`.

    Resolved at import so the parsing half of this module stays importable and testable
    without DeepEval installed — that half carries the schema and parity risk and deserves
    to be exercisable on its own. DeepEval type-checks metrics with `isinstance`, so this
    must be a real base class rather than duck typing.
    """
    spec = find_spec("deepeval")
    if spec is None:
        return object
    # Importing grading exposes eval/ on sys.path. Without the dependency,
    # eval/deepeval/ then appears as an implicit namespace, not the installed root.
    if spec.origin is None and {
        Path(location).resolve() for location in (spec.submodule_search_locations or ())
    } == {Path(__file__).resolve().parents[1]}:
        return object

    # An installed but broken package is not a dependency-free environment.
    # Propagate all import/initialization failures, including missing transitive modules.
    from deepeval.metrics import BaseMetric

    return BaseMetric


class AcceptanceMetric(_metric_base()):
    """DeepEval metric: does the produced workspace meet the acceptance criteria?

    `test_case.actual_output` is the workspace path.
    """

    def __init__(
        self,
        acceptance_path: str | Path,
        *,
        plugin_dirs: Sequence[str] = (),
        model: str | None = None,
        isolated_home: str | Path | None = None,
        threshold: float = 1.0,
        timeout: int = 900,
        baseline_dir: str | Path | None = None,
    ):
        self.acceptance_path = acceptance_path
        self.plugin_dirs = list(plugin_dirs)
        self.model = model
        self.isolated_home = isolated_home
        self.threshold = threshold
        self.timeout = timeout
        self.baseline_dir = baseline_dir
        self.include_reason = True
        self.score: float | None = None
        self.reason: str | None = None
        self.success: bool | None = None
        self.result: JudgeResult | None = None

    @property
    def __name__(self) -> str:  # noqa: A003 - DeepEval reads this for reporting
        return "Acceptance"

    def measure(self, test_case) -> float:
        result = run_judge(
            test_case.actual_output,
            self.acceptance_path,
            plugin_dirs=self.plugin_dirs,
            model=self.model,
            isolated_home=self.isolated_home,
            timeout=self.timeout,
            baseline_dir=self.baseline_dir,
        )
        self.result = result
        self.score = result.score
        self.success = (
            result.complete and not result.unverified
            and result.verdict in {Verdict.RESOLVED, Verdict.PARTIAL}
            and result.score >= self.threshold
        )
        self.reason = f"verdict={result.verdict.value}"
        if result.unverified:
            self.reason += " (UNVERIFIED — no resolved credit)"
        self.reason += (
            f"; claimed={result.claimed_verdict}; "
            f"reasons={result.to_dict()['reasons']}"
        )
        return self.score

    async def a_measure(self, test_case) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return bool(self.success)

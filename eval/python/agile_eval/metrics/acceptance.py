"""Native DeepEval adapter for the shared held workspace-grading contract.

Use the dependency-free score_workspace entrypoint for held preflight alone.
This module requires real DeepEval; it never substitutes a fake metric base.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from agile_eval.grading_contract import JudgeResult, Verdict
from agile_eval.grading import build_grading_prompt, held_workspace_result as run_judge
from agile_eval.workspace_inputs import gradable_files

from agile_eval.metrics.local_model import configure_offline

configure_offline()

try:
    from deepeval.metrics import BaseMetric
except (ImportError, RuntimeError) as exc:
    raise ImportError(
        "Native acceptance metrics require DeepEval 4.1.8 and its locked dependencies; "
        "use eval/deepeval/requirements.lock.txt. No fallback backend is available."
    ) from exc


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


class AcceptanceMetric(BaseMetric):
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

    def measure(self, test_case, *args, **kwargs) -> float:
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

    async def a_measure(self, test_case, *args, **kwargs) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return bool(self.success)

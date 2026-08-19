"""Outcome grading as a DeepEval metric.

Replaces the `score-judge.{sh,ps1}` twin pair with a single implementation. The verdict
contract is unchanged, so scores stay comparable: RESOLVED / PARTIAL / FAILED, last
verdict wins, anything unparseable is FAILED so an unclear judge never inflates a score.

Two things differ from the shell judge, both deliberate:

**The judge verifies instead of reading a dump.** The old prompt inlined file contents and
told the grader to decide "strictly from those artifacts", which turned a truncated listing
into evidence of absence — a task was once failed for missing tests that existed and passed.
Here the judge runs *in* the workspace with tools and is pointed at the
`acceptance-grading` skill, which owns that doctrine. The file listing is passed as an
orientation index only, explicitly labelled as not the workspace.

**Doctrine lives in the skill, not in this file.** `acceptance-grading` defines
verify-don't-infer, the sandbox rule (run the project's own build and test commands, never
repair what you grade), conventions being owned by whichever skill defines them, and the
PASS / FAIL / UNVERIFIED contract. This module only wires it up.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Sequence

from .local_model import configure_offline

configure_offline()


class Verdict(str, Enum):
    RESOLVED = "RESOLVED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


# Kept identical to the shell twins so a migration does not silently move scores.
VERDICT_SCORE: dict[Verdict, float] = {
    Verdict.RESOLVED: 1.0,
    Verdict.PARTIAL: 0.5,
    Verdict.FAILED: 0.0,
}

# The exit codes the pipeline harness expects from a scorer.
VERDICT_EXIT: dict[Verdict, int] = {
    Verdict.RESOLVED: 0,
    Verdict.PARTIAL: 2,
    Verdict.FAILED: 1,
}

_VERDICT_RE = re.compile(r"VERDICT:\s*(RESOLVED|PARTIAL|FAILED)", re.IGNORECASE)

# Directories that are build output or vendored code. A real run once put 29 of 34 files
# through the judge as bin/obj, blowing the size budget before it reached tests/.
PRUNED_DIRS = {
    ".git", ".github", "bin", "obj", "node_modules", ".venv", "venv",
    "__pycache__", "dist", "build", "target", ".pytest_cache", ".copilot-home",
}
SKIP_FILES = {"solution-profile.yaml"}
BINARY_SUFFIXES = {
    ".dll", ".exe", ".pdb", ".so", ".dylib", ".zip", ".tar", ".gz", ".png",
    ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".woff", ".woff2", ".nupkg",
}


def parse_verdict(text: str) -> Verdict:
    """Map a judge response to a verdict.

    The last verdict wins (a judge that reconsiders should be taken at its final word),
    matching is case-insensitive, and anything unparseable is FAILED — an unclear judge
    must never inflate a score.
    """
    matches = _VERDICT_RE.findall(text or "")
    if not matches:
        return Verdict.FAILED
    return Verdict(matches[-1].upper())


def has_unverified(text: str) -> bool:
    """Whether the judge could not check something.

    UNVERIFIED means the harness failed to show the judge the evidence — a harness
    limitation, not an agent result. It must be surfaced rather than settling into a score.
    """
    return bool(re.search(r"\bUNVERIFIED\b", text or "", re.IGNORECASE))


def workspace_index(workspace: str | Path, max_entries: int = 200) -> str:
    """A file listing for orientation — deliberately not file contents.

    The judge has the workspace and tools; giving it a truncated dump is what caused
    absence-of-evidence to be read as evidence-of-absence.
    """
    root = Path(workspace)
    if not root.is_dir():
        return "(workspace does not exist)"

    entries: list[str] = []
    truncated = False
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in PRUNED_DIRS for part in rel_parts[:-1]):
            continue
        if path.name in SKIP_FILES or path.suffix.lower() in BINARY_SUFFIXES:
            continue
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


def build_judge_prompt(acceptance_text: str, index: str) -> str:
    """A thin shim. The grading contract lives in the `acceptance-grading` skill."""
    return f"""Load the **`acceptance-grading`** skill and follow it. It owns how this grading
works — verify rather than infer, the sandbox rule that lets you run the project's own build
and test commands but never repair what you are grading, conventions being owned by whichever
skill defines them, and the PASS / FAIL / UNVERIFIED + VERDICT output contract.

You are running inside the workspace under grade and you have tools.

## Acceptance criteria

{acceptance_text}

## Workspace index (orientation only — capped, and not the workspace)

{index}
"""


@dataclass
class JudgeResult:
    verdict: Verdict
    response: str
    unverified: bool

    @property
    def score(self) -> float:
        return VERDICT_SCORE[self.verdict]

    @property
    def exit_code(self) -> int:
        return VERDICT_EXIT[self.verdict]


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
) -> JudgeResult:
    """Invoke the CLI as judge and return its verdict.

    `isolated_home` redirects HOME/USERPROFILE so the judge resolves plugins from
    `plugin_dirs` only. Without it an installed plugin of the same name shadows them and
    the judge grades against a different version than the agent ran with.
    """
    acceptance_text = Path(acceptance_path).read_text(encoding="utf-8")
    prompt = build_judge_prompt(acceptance_text, workspace_index(workspace))

    argv: list[str] = ["copilot", "-p", prompt, "--no-ask-user", "--allow-all-tools"]
    if model:
        argv += ["--model", model]
    for d in plugin_dirs:
        argv += ["--plugin-dir", d]
    argv += ["-C", str(workspace)]

    env = os.environ.copy()
    if isolated_home:
        env["HOME"] = str(isolated_home)
        env["USERPROFILE"] = str(isolated_home)

    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, env=env,
            encoding="utf-8", errors="replace",
        )
        response = (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        # A judge that never answered is not a failing agent. Say so in the response so
        # the reason survives into the report rather than becoming a bare 0.0.
        response = f"judge timed out after {timeout}s\nVERDICT: FAILED"
    except FileNotFoundError:
        response = "copilot not on PATH — cannot score\nVERDICT: FAILED"

    return JudgeResult(
        verdict=parse_verdict(response),
        response=response,
        unverified=has_unverified(response),
    )


def _metric_base():
    """DeepEval's `BaseMetric` when available, else `object`.

    Resolved at import so the parsing half of this module stays importable and testable
    without DeepEval installed — that half carries the schema and parity risk and deserves
    to be exercisable on its own. DeepEval type-checks metrics with `isinstance`, so this
    must be a real base class rather than duck typing.
    """
    try:
        from deepeval.metrics import BaseMetric

        return BaseMetric
    except Exception:  # pragma: no cover - only without DeepEval installed
        return object


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
    ):
        self.acceptance_path = acceptance_path
        self.plugin_dirs = list(plugin_dirs)
        self.model = model
        self.isolated_home = isolated_home
        self.threshold = threshold
        self.timeout = timeout
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
        )
        self.result = result
        self.score = result.score
        self.success = result.score >= self.threshold
        self.reason = f"verdict={result.verdict.value}"
        if result.unverified:
            # Not folded into the score: an UNVERIFIED criterion means the harness could
            # not show the judge the evidence, which understates the agent.
            self.reason += " (contains UNVERIFIED — harness limit, not an agent result)"
        return self.score

    async def a_measure(self, test_case) -> float:
        return self.measure(test_case)

    def is_successful(self) -> bool:
        return bool(self.success)

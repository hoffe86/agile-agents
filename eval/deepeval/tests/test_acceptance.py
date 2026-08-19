"""Tests for outcome grading.

The parity tests matter most: this metric is meant to replace `score-judge.{sh,ps1}`, so
its verdict parser must agree with theirs on every case those twins self-test, or a
migration silently moves scores.

Run:  python -m pytest eval/deepeval/tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from metrics.acceptance import (  # noqa: E402
    VERDICT_EXIT,
    VERDICT_SCORE,
    AcceptanceMetric,
    JudgeResult,
    Verdict,
    build_judge_prompt,
    discover_plugin_dirs,
    has_unverified,
    parse_verdict,
    workspace_index,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


# --- Parity with the shell judges -------------------------------------------------
# Lifted verbatim from score-judge.sh --self-test (and its .ps1 twin). Exit codes are
# the contract run-eval reads: 0 resolved, 2 partial, 1 failed.

SHELL_SELF_TEST_CASES = [
    (0, "1. PASS - ok\nVERDICT: RESOLVED"),
    (2, "VERDICT: PARTIAL\n"),
    (1, "VERDICT: FAILED"),
    (1, "no verdict here"),
    (1, "VERDICT: RESOLVED\nVERDICT: FAILED"),   # last wins
    (0, "verdict: resolved"),                     # case-insensitive
]


@pytest.mark.parametrize("want_exit,text", SHELL_SELF_TEST_CASES)
def test_parity_with_shell_judge_self_test(want_exit, text):
    assert VERDICT_EXIT[parse_verdict(text)] == want_exit


def test_unparseable_is_failed_not_an_error():
    """An unclear judge must never inflate a score, and must not crash the run."""
    for text in ["", "   ", "the agent did well", "VERDICT: MAYBE"]:
        assert parse_verdict(text) is Verdict.FAILED


def test_score_mapping_is_stable():
    assert VERDICT_SCORE[Verdict.RESOLVED] == 1.0
    assert VERDICT_SCORE[Verdict.PARTIAL] == 0.5
    assert VERDICT_SCORE[Verdict.FAILED] == 0.0


def test_verdict_embedded_in_prose_is_found():
    text = "1. PASS - built fine\n2. FAIL - missing test\n\nVERDICT: PARTIAL\n"
    assert parse_verdict(text) is Verdict.PARTIAL


# --- UNVERIFIED ------------------------------------------------------------------


def test_unverified_is_detected_and_does_not_change_the_score():
    text = "1. UNVERIFIED - no dotnet on PATH\n2. PASS - file exists\nVERDICT: PARTIAL"
    assert has_unverified(text)
    # It is a harness limitation, so it is reported but must not silently alter the score.
    assert parse_verdict(text) is Verdict.PARTIAL


def test_unverified_absent_when_not_mentioned():
    assert not has_unverified("1. PASS - ok\nVERDICT: RESOLVED")


# --- Workspace index -------------------------------------------------------------


def test_index_prunes_build_output(tmp_path):
    """A real run put 29 of 34 files through the judge as bin/obj."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Program.cs").write_text("class P {}")
    (tmp_path / "bin" / "Debug").mkdir(parents=True)
    (tmp_path / "bin" / "Debug" / "app.dll").write_text("binary")
    (tmp_path / "obj").mkdir()
    (tmp_path / "obj" / "project.assets.json").write_text("{}")

    index = workspace_index(tmp_path)
    assert "src/Program.cs" in index
    assert "bin" not in index
    assert "obj" not in index


def test_index_skips_the_seeded_profile(tmp_path):
    """The profile is harness input, not something the agent produced."""
    (tmp_path / "solution-profile.yaml").write_text("x: 1")
    (tmp_path / "README.md").write_text("hi")
    index = workspace_index(tmp_path)
    assert "README.md" in index
    assert "solution-profile.yaml" not in index


def test_index_reports_when_capped(tmp_path):
    for i in range(12):
        (tmp_path / f"f{i}.md").write_text("x")
    index = workspace_index(tmp_path, max_entries=5)
    assert "capped at 5" in index


def test_index_on_missing_workspace_says_so(tmp_path):
    assert "does not exist" in workspace_index(tmp_path / "nope")


def test_index_on_empty_workspace_says_so(tmp_path):
    assert "no gradable files" in workspace_index(tmp_path)


# --- Prompt ----------------------------------------------------------------------


def test_prompt_delegates_doctrine_to_the_skill():
    """Doctrine belongs in the skill; restating it here would fork and drift."""
    prompt = build_judge_prompt("1. File exists.", "- a.md")
    assert "acceptance-grading" in prompt
    assert "1. File exists." in prompt
    assert "- a.md" in prompt


def test_prompt_labels_the_index_as_not_the_workspace():
    """The old prompt's dump was read as the whole truth; this one must not be."""
    prompt = build_judge_prompt("crit", "- a.md")
    assert "orientation only" in prompt
    assert "not the workspace" in prompt


def test_prompt_has_no_unfilled_placeholders():
    prompt = build_judge_prompt("crit", "- a.md")
    assert "{{" not in prompt and "}}" not in prompt


# --- Plugin discovery ------------------------------------------------------------


def test_discovers_this_repos_plugins():
    dirs = discover_plugin_dirs(REPO_ROOT)
    assert dirs, "no agile-agents plugin folders found"
    assert any(d.endswith("agile-agents-core") for d in dirs)


def test_the_grading_skill_is_reachable_through_a_discovered_dir():
    """If this breaks, the judge silently falls back to its own priors."""
    dirs = discover_plugin_dirs(REPO_ROOT)
    assert any((Path(d) / "skills" / "acceptance-grading" / "SKILL.md").is_file() for d in dirs)


# --- Metric wiring ---------------------------------------------------------------


def test_metric_reports_score_and_reason_without_calling_a_model(tmp_path, monkeypatch):
    acceptance = tmp_path / "acceptance.md"
    acceptance.write_text("1. Something.")

    import metrics.acceptance as mod

    monkeypatch.setattr(
        mod, "run_judge",
        lambda *a, **k: JudgeResult(Verdict.PARTIAL, "VERDICT: PARTIAL", False),
    )

    metric = mod.AcceptanceMetric(acceptance)

    class Case:
        actual_output = str(tmp_path)

    assert metric.measure(Case()) == 0.5
    assert metric.is_successful() is False       # threshold 1.0 — only RESOLVED passes
    assert "PARTIAL" in metric.reason


def test_metric_surfaces_unverified_in_the_reason(tmp_path, monkeypatch):
    acceptance = tmp_path / "acceptance.md"
    acceptance.write_text("1. Something.")

    import metrics.acceptance as mod

    monkeypatch.setattr(
        mod, "run_judge",
        lambda *a, **k: JudgeResult(Verdict.RESOLVED, "1. UNVERIFIED - x\nVERDICT: RESOLVED", True),
    )
    metric = mod.AcceptanceMetric(acceptance)

    class Case:
        actual_output = str(tmp_path)

    assert metric.measure(Case()) == 1.0
    assert "UNVERIFIED" in metric.reason


def test_missing_copilot_fails_closed(tmp_path, monkeypatch):
    """No judge means no grade — it must not read as a passing agent."""
    import metrics.acceptance as mod

    acceptance = tmp_path / "acceptance.md"
    acceptance.write_text("1. Something.")

    def boom(*a, **k):
        raise FileNotFoundError("copilot")

    monkeypatch.setattr(mod.subprocess, "run", boom)
    result = mod.run_judge(tmp_path, acceptance)
    assert result.verdict is Verdict.FAILED
    assert "not on PATH" in result.response


def test_judge_timeout_is_failed_with_a_stated_reason(tmp_path, monkeypatch):
    import metrics.acceptance as mod

    acceptance = tmp_path / "acceptance.md"
    acceptance.write_text("1. Something.")

    def timeout(*a, **k):
        raise mod.subprocess.TimeoutExpired(cmd="copilot", timeout=1)

    monkeypatch.setattr(mod.subprocess, "run", timeout)
    result = mod.run_judge(tmp_path, acceptance, timeout=1)
    assert result.verdict is Verdict.FAILED
    assert "timed out" in result.response


def test_isolated_home_is_passed_to_the_child(tmp_path, monkeypatch):
    """Without isolation the judge grades against a different plugin version."""
    import metrics.acceptance as mod

    acceptance = tmp_path / "acceptance.md"
    acceptance.write_text("1. Something.")
    seen = {}

    class Proc:
        stdout = "VERDICT: RESOLVED"
        stderr = ""

    def capture(argv, **kwargs):
        seen["env"] = kwargs.get("env") or {}
        seen["argv"] = argv
        return Proc()

    monkeypatch.setattr(mod.subprocess, "run", capture)
    mod.run_judge(
        tmp_path, acceptance,
        plugin_dirs=["/p/one"], model="gpt-5.6-sol", isolated_home="/iso",
    )

    assert seen["env"].get("HOME") == "/iso"
    assert seen["env"].get("USERPROFILE") == "/iso"
    assert "--plugin-dir" in seen["argv"] and "/p/one" in seen["argv"]
    assert "--model" in seen["argv"] and "gpt-5.6-sol" in seen["argv"]


def test_metric_is_a_real_deepeval_metric_when_available():
    """DeepEval type-checks with isinstance, so duck typing is not enough."""
    deepeval = pytest.importorskip("deepeval", reason="DeepEval not installed")
    from deepeval.metrics import BaseMetric

    assert issubclass(AcceptanceMetric, BaseMetric)

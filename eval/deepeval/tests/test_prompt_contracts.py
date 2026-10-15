"""Both offline judge prompt paths include one authority, without executing artifacts."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "eval/pipeline"))
sys.path.insert(0, str(ROOT / "eval/deepeval"))

from grading import load_grading_doctrine  # noqa: E402
from metrics.acceptance import build_judge_prompt as metric_prompt  # noqa: E402
from metrics.acceptance import discover_plugin_dirs  # noqa: E402
from shell_judge import build_judge_prompt as shell_prompt  # noqa: E402

TEMPLATE = ROOT / "eval/pipeline/references/judge-prompt.md"
CORE = ROOT / "plugins/agile-agents-core"
SKILL = Path("skills/acceptance-grading/SKILL.md")


def assert_prompt_safety(prompt):
    assert "Live judging remains disabled" in prompt
    assert "Do not run build, test, lint, render, or other workspace-provided commands on the host" in prompt
    assert "manifest hashes independently match the canonical fixture" in prompt
    assert "workspace metadata are not trust roots" in prompt
    assert "mark that criterion `UNVERIFIED`" in prompt
    assert "no-Ingress baseline" in prompt
    assert "exactly one anchored status line" in prompt
    assert "in the disposable workspace" not in prompt


def test_both_prompt_paths_include_the_exact_authoritative_doctrine():
    plugins = discover_plugin_dirs(ROOT)
    doctrine = load_grading_doctrine(plugins)
    shell = shell_prompt("1. criterion", "- evidence", "originals", plugin_dirs=plugins)
    metric = metric_prompt("1. criterion", "- evidence", "originals", plugin_dirs=plugins)
    assert shell == metric
    assert doctrine == (CORE / SKILL).read_text(encoding="utf-8")
    assert shell.count(doctrine) == 1
    assert_prompt_safety(shell)
    # A thin template must not restate the lifecycle, sandbox or verdict doctrine.
    assert TEMPLATE.read_text(encoding="utf-8").count("{{GRADING_DOCTRINE}}") == 1
    assert "VERDICT:" not in TEMPLATE.read_text(encoding="utf-8")


@pytest.mark.parametrize("builder", [shell_prompt, metric_prompt])
def test_prompt_reads_doctrine_relative_to_selected_installed_plugin_not_cwd(tmp_path, monkeypatch, builder):
    installed = tmp_path / "installed/core"
    (installed / SKILL).parent.mkdir(parents=True)
    shutil.copyfile(CORE / SKILL, installed / SKILL)
    with (installed / SKILL).open("a", encoding="utf-8") as stream:
        stream.write("\nSelected-plugin sentinel.\n")
    monkeypatch.chdir(tmp_path)
    prompt = builder("1. criterion", "- evidence", plugin_dirs=[installed])
    assert "Selected-plugin sentinel." in prompt
    assert_prompt_safety(prompt)


@pytest.mark.parametrize("builder", [shell_prompt, metric_prompt])
def test_missing_doctrine_fails_closed_without_ambient_plugin_fallback(tmp_path, builder):
    with pytest.raises(ValueError, match="exactly one acceptance-grading"):
        builder("1. criterion", "- evidence", plugin_dirs=[tmp_path])


def test_ambiguous_doctrine_roots_are_not_silently_selected(tmp_path):
    other = tmp_path / "core"
    (other / SKILL).parent.mkdir(parents=True)
    shutil.copyfile(CORE / SKILL, other / SKILL)
    with pytest.raises(ValueError, match="exactly one acceptance-grading"):
        shell_prompt("1. criterion", "- evidence", plugin_dirs=[CORE, other])


@pytest.mark.parametrize("replacement", ["", "{{GRADING_DOCTRINE}}\n{{GRADING_DOCTRINE}}"])
def test_removing_or_duplicating_required_doctrine_reference_is_rejected(tmp_path, replacement):
    mutated = tmp_path / "prompt.md"
    mutated.write_text(TEMPLATE.read_text(encoding="utf-8").replace(
        "{{GRADING_DOCTRINE}}", replacement,
    ), encoding="utf-8")
    with pytest.raises(ValueError, match="doctrine and each evidence placeholder exactly once"):
        shell_prompt("1. criterion", "- evidence", prompt_template=mutated)


def test_disposable_directory_as_execution_permission_mutation_is_detected():
    prompt = shell_prompt("1. criterion", "- evidence")
    mutated = prompt.replace(
        "Do not run build, test, lint, render, or other workspace-provided commands on the host.",
        "Verify builds/tests/render equivalence using native commands in the disposable workspace.",
    )
    with pytest.raises(AssertionError):
        assert_prompt_safety(mutated)


@pytest.mark.parametrize("builder", [shell_prompt, metric_prompt])
def test_evidence_placeholders_are_literal_not_recursive_instructions(builder):
    prompt = builder("1. Keep {{ARTIFACTS}} literal", "{{ORIGINALS}}", "{{GRADING_DOCTRINE}}")
    assert "1. Keep {{ARTIFACTS}} literal" in prompt
    assert "\n{{ORIGINALS}}\n" in prompt
    assert prompt.endswith("{{GRADING_DOCTRINE}}\n")

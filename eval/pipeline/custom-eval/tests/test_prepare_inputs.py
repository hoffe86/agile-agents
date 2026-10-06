from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

CUSTOM_EVAL = Path(__file__).resolve().parents[1]
TASKS = CUSTOM_EVAL / "tasks"
sys.path.insert(0, str(CUSTOM_EVAL))

from prepare_inputs import SetupError, prepare, prepare_many, validate_profile  # noqa: E402


@pytest.fixture
def scratch(tmp_path):
    task = tmp_path / "task"
    task.mkdir()
    (task / "baseline").mkdir()
    (task / "baseline" / "source.txt").write_text("original\n", encoding="utf-8")
    (task / "solution-profile.yaml").write_text(
        """
identity:
  project_name: fixture
  lifecycle_stage: poc
documentation:
  platform: in-repo
  location: docs/
backlog:
  platform: none
  create_tasks: false
tech_stack:
  primary_languages: [python]
  test_discipline: test-after
infrastructure:
  deploy_verify: "off"
quality_gates:
  test_bar:
    enabled: true
    lint:
      command: [python, -m, compileall, -q, .]
    typecheck:
      enabled: false
    unit_test:
      command: [python, -m, pytest, -q]
""",
        encoding="utf-8",
    )
    (task / "inputs.json").write_text(
        json.dumps({
            "version": 1,
            "provenance": "synthetic test fixture",
            "inputs": [{
                "source": "baseline/source.txt",
                "destination": "src/source.txt",
                "required": True,
            }],
        }),
        encoding="utf-8",
    )
    return task


def test_all_shipped_profiles_have_required_context_and_real_check_blocks():
    expected_checks = {
        "task-01-csharp-minimal-api-endpoint": {"lint", "typecheck", "unit_test"},
        "task-02-python-di-refactor": {"lint", "typecheck", "unit_test"},
        "task-03-bicep-storage-waf": {"lint", "typecheck"},
        "task-04-adr-library-tradeoff": set(),
        "task-05-pr-description": set(),
        "task-06-gha-oidc-deploy": {"lint", "typecheck", "unit_test"},
        "task-07-test-coverage-uplift": {
            "lint", "typecheck", "unit_test", "integration_test", "coverage"
        },
        "task-08-threat-model-api": set(),
        "task-09-polly-resilience": {"lint", "typecheck", "unit_test"},
        "task-10-helm-to-kustomize": {"lint", "typecheck", "integration_test"},
    }
    profiles = sorted(TASKS.glob("*/solution-profile.yaml"))
    assert len(profiles) == 10
    for profile_path in profiles:
        _, checks = validate_profile(profile_path)
        assert {item["check"] for item in checks} == expected_checks[profile_path.parent.name]
        assert all(isinstance(item["argv"], list) and item["argv"] for item in checks)


def test_each_task_declares_only_its_intended_baseline_inputs():
    expected = {
        "task-01-csharp-minimal-api-endpoint": True,
        "task-02-python-di-refactor": True,
        "task-03-bicep-storage-waf": False,
        "task-04-adr-library-tradeoff": True,
        "task-05-pr-description": True,
        "task-06-gha-oidc-deploy": True,
        "task-07-test-coverage-uplift": True,
        "task-08-threat-model-api": False,
        "task-09-polly-resilience": True,
        "task-10-helm-to-kustomize": True,
    }
    for task_id, has_inputs in expected.items():
        declaration = json.loads((TASKS / task_id / "inputs.json").read_text(encoding="utf-8"))
        assert declaration["version"] == 1
        assert bool(declaration["inputs"]) is has_inputs


def test_prepare_keeps_manifest_outside_workspace_and_does_not_claim_os_isolation(scratch, tmp_path):
    workspace = tmp_path / "run" / "ws" / "task"
    baseline = tmp_path / "run" / "baseline" / "task"
    result = prepare(scratch, workspace, baseline)

    assert result["status"] == "prepared"
    assert (workspace / "src" / "source.txt").read_text(encoding="utf-8") == "original\n"
    assert (workspace / "solution-profile.yaml").read_bytes() == (
        workspace / ".github" / "solution-profile.yaml"
    ).read_bytes()
    baseline_input = baseline / "src" / "source.txt"
    assert baseline_input.read_text(encoding="utf-8") == "original\n"
    manifest = json.loads((baseline / "baseline-manifest.json").read_text())
    assert manifest["version"] == 2 and "read_only" not in manifest
    assert not (workspace / ".github" / "eval-inputs.json").exists()
    assert baseline not in workspace.parents and workspace not in baseline.parents
    assert result["baseline_integrity"].startswith("verified against canonical")
    assert len(result["resolved_checks"]) == 2


def test_missing_required_input_returns_structured_setup_error_before_workspace_creation(
    scratch, tmp_path
):
    declaration = json.loads((scratch / "inputs.json").read_text())
    declaration["inputs"][0]["source"] = "baseline/missing.txt"
    (scratch / "inputs.json").write_text(json.dumps(declaration), encoding="utf-8")
    workspace = tmp_path / "workspace"
    baseline = tmp_path / "baseline"
    result = subprocess.run(
        [
            sys.executable,
            str(CUSTOM_EVAL / "prepare_inputs.py"),
            "--task-dir",
            str(scratch),
            "--workspace",
            str(workspace),
            "--baseline-dir",
            str(baseline),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert json.loads(result.stdout)["status"] == "setup_error"
    assert not workspace.exists()
    assert not baseline.exists()


def test_batch_preflight_checks_every_task_before_staging_any_workspace(scratch, tmp_path):
    suite = tmp_path / "suite"
    tasks = suite / "tasks"
    tasks.mkdir(parents=True)
    shutil.copytree(scratch, tasks / "task-good")
    shutil.copytree(scratch, tasks / "task-bad")
    broken_declaration = json.loads((tasks / "task-bad" / "inputs.json").read_text())
    broken_declaration["inputs"][0]["source"] = "baseline/missing.txt"
    (tasks / "task-bad" / "inputs.json").write_text(
        json.dumps(broken_declaration), encoding="utf-8"
    )

    result = prepare_many(suite, tmp_path / "run", ["task-good", "task-bad"])

    assert result["status"] == "setup_error"
    assert [task["status"] for task in result["tasks"]] == ["not_prepared", "setup_error"]
    assert not (tmp_path / "run" / "ws").exists()
    assert not (tmp_path / "run" / "baseline").exists()


@pytest.mark.parametrize("unsafe_path", ["../outside.txt", "/absolute.txt", "C:/outside.txt"])
def test_input_destination_rejects_traversal_and_absolute_paths(scratch, unsafe_path):
    declaration = json.loads((scratch / "inputs.json").read_text())
    declaration["inputs"][0]["destination"] = unsafe_path
    (scratch / "inputs.json").write_text(json.dumps(declaration), encoding="utf-8")
    with pytest.raises(SetupError, match="safe relative path|drive-qualified"):
        prepare(scratch, scratch.parent / "workspace", scratch.parent / "baseline")


def test_input_cannot_overwrite_canonical_profile(scratch):
    declaration = json.loads((scratch / "inputs.json").read_text())
    declaration["inputs"][0]["destination"] = "solution-profile.yaml"
    (scratch / "inputs.json").write_text(json.dumps(declaration), encoding="utf-8")
    with pytest.raises(SetupError, match="reserved"):
        prepare(scratch, scratch.parent / "workspace", scratch.parent / "baseline")


def test_disabled_test_bar_requires_explanation(scratch):
    profile_path = scratch / "solution-profile.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["quality_gates"]["test_bar"] = {"enabled": False}
    profile_path.write_text(yaml.safe_dump(profile), encoding="utf-8")
    with pytest.raises(SetupError, match="skip_reason"):
        validate_profile(profile_path)


def test_enabled_check_requires_an_explicit_resolvable_argv(scratch):
    profile_path = scratch / "solution-profile.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["quality_gates"]["test_bar"]["unit_test"] = {"enabled": True}
    profile_path.write_text(yaml.safe_dump(profile), encoding="utf-8")
    with pytest.raises(SetupError, match="requires a non-empty argv"):
        validate_profile(profile_path)

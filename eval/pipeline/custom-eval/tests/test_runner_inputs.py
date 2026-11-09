"""Normal input staging and native runtime isolation; no guidance resolver."""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from agile_eval.custom_eval import runner
from agile_eval.custom_eval.expectations import load

TASKS = runner.default_tasks_root()
CORE = runner.repo_root() / "plugins/agile-agents-core"
LOCAL = {
    "01": {"csharp-implementation", "csharp-testing"},
    "02": {"python-implementation", "python-testing"},
    "03": {"bicep-implementation"}, "04": set(), "05": set(),
    "06": {"cicd-pipeline-implementation"}, "07": {"csharp-testing"},
    "08": {"threat-model-analyst"},
    "09": {"csharp-implementation", "csharp-testing"},
    "10": {"helm-kustomize-implementation"},
}


def task(number):
    return runner.resolve_task(TASKS, f"task-{number}")


def fixture(tmp_path):
    source = tmp_path / "task"
    source.mkdir()
    (source / "file.txt").write_text("explicit input", encoding="utf-8")
    (source / "solution-profile.yaml").write_text("identity: {project_name: test}\n")
    return source, {"version": 1, "inputs": [
        {"source": "file.txt", "destination": "file.txt", "required": True}]}


def stage(source, manifest, tmp_path):
    (source / "inputs.json").write_text(json.dumps(manifest), encoding="utf-8")
    paths = runner.Paths(tmp_path / "run")
    runner.stage(source, paths)
    return paths


@pytest.mark.parametrize("number", LOCAL)
def test_scenarios_stage_explicit_inputs_byte_for_byte(tmp_path, number):
    source = task(number)
    paths = runner.Paths(tmp_path / "run")
    runner.stage(source, paths)
    manifest = json.loads((source / "inputs.json").read_text())
    assert set(manifest) == {"version", "provenance", "inputs"}
    for item in manifest["inputs"]:
        original = source / item["source"]
        files = [original] if original.is_file() else original.rglob("*")
        for path in files:
            if path.is_file():
                relative = Path() if original.is_file() else path.relative_to(original)
                assert (paths.workspace / item["destination"] / relative).read_bytes() == path.read_bytes()
    assert (paths.workspace / ".github/solution-profile.yaml").read_bytes() == (
        source / "solution-profile.yaml").read_bytes()
    local = {p.parent.name for p in (paths.workspace / ".github/skills").glob("*/SKILL.md")}
    assert local == LOCAL[number]
    required = {name for names in load(source).skills.values() for name in names}
    core_names = {p.parent.name for p in (CORE / "skills").glob("*/SKILL.md")}
    assert required - core_names == local
    assert not (paths.run / "guidance.json").exists()
    assert not (paths.workspace / "plugins").exists()
    assert not (paths.workspace / ".github/agents").exists()


def test_core_selection_rejects_sibling_fallback(tmp_path):
    shutil.copytree(CORE / ".github", tmp_path / "plugins/agile-agents-core/.github")
    shutil.copytree(CORE / ".github", tmp_path / "plugins/unrelated/.github")
    assert runner.plugin_dirs(tmp_path) == [tmp_path / "plugins/agile-agents-core"]
    shutil.rmtree(tmp_path / "plugins/agile-agents-core")
    with pytest.raises(runner.SetupError, match="core plugin missing"):
        runner.plugin_dirs(tmp_path)


@pytest.mark.parametrize("manifest", [
    [], {"version": True, "inputs": []}, {"version": 2, "inputs": []},
    {"version": 1, "inputs": [], "guidance": []},
    {"version": 1, "inputs": {}},
    {"version": 1, "inputs": [{"source": "file.txt"}]},
    {"version": 1, "inputs": [{"source": "file.txt", "destination": "file.txt", "owner": "solution"}]},
])
def test_invalid_or_retired_manifest_contract_fails_setup(tmp_path, manifest):
    source, _ = fixture(tmp_path)
    with pytest.raises(runner.SetupError):
        stage(source, manifest, tmp_path)


@pytest.mark.parametrize("destination", [
    "../escape", "/absolute", ".git/config", ".copilot/config.json",
    ".claude/settings.json", "plugins/injected/file", ".github/agents/injected.md",
    ".github/solution-profile.yaml",
])
def test_input_cannot_escape_or_replace_runtime_configuration(tmp_path, destination):
    source, manifest = fixture(tmp_path)
    manifest["inputs"][0]["destination"] = destination
    with pytest.raises(runner.SetupError):
        stage(source, manifest, tmp_path)


def test_directory_input_cannot_hide_runtime_configuration(tmp_path):
    source, manifest = fixture(tmp_path)
    hidden = source / "directory/.copilot/config.json"
    hidden.parent.mkdir(parents=True)
    hidden.write_text("{}")
    manifest["inputs"][0].update(source="directory", destination="src")
    with pytest.raises(runner.SetupError, match="cannot inject"):
        stage(source, manifest, tmp_path)


def test_symlink_input_cannot_read_ambient_file(tmp_path):
    source, manifest = fixture(tmp_path)
    (tmp_path / "ambient.txt").write_text("not a task input")
    (source / "file.txt").unlink()
    (source / "file.txt").symlink_to(tmp_path / "ambient.txt")
    with pytest.raises(runner.SetupError, match="escapes"):
        stage(source, manifest, tmp_path)
    assert not (tmp_path / "run/workspace/file.txt").exists()


def test_in_task_symlink_input_is_rejected_without_copying_target(tmp_path):
    source, manifest = fixture(tmp_path)
    (source / "target.txt").write_text("in-task target must not be copied")
    (source / "file.txt").unlink()
    (source / "file.txt").symlink_to(source / "target.txt")
    with pytest.raises(runner.SetupError, match="^input symlinks are not allowed$"):
        stage(source, manifest, tmp_path)
    assert not (tmp_path / "run/workspace/file.txt").exists()
    assert not (tmp_path / "run/workspace/target.txt").exists()


def test_directory_input_with_nested_symlink_is_rejected_before_copy(tmp_path):
    source, manifest = fixture(tmp_path)
    nested = source / "directory/nested"
    nested.mkdir(parents=True)
    (source / "directory/ordinary.txt").write_text("ordinary input")
    (nested / "link.txt").symlink_to(source / "file.txt")
    manifest["inputs"][0].update(source="directory", destination="src")
    with pytest.raises(runner.SetupError, match="^input symlinks are not allowed$"):
        stage(source, manifest, tmp_path)
    assert not (tmp_path / "run/workspace/src").exists()


def test_duplicate_destination_fails_without_overwriting(tmp_path):
    source, manifest = fixture(tmp_path)
    manifest["inputs"].append(manifest["inputs"][0])
    with pytest.raises(runner.SetupError, match="duplicate input destination"):
        stage(source, manifest, tmp_path)
    assert (tmp_path / "run/workspace/file.txt").read_text() == "explicit input"


def test_missing_required_input_never_uses_ambient_copy(tmp_path, monkeypatch):
    source, manifest = fixture(tmp_path)
    (source / "file.txt").unlink()
    (tmp_path / "file.txt").write_text("ambient")
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(runner.SetupError, match="required input missing"):
        stage(source, manifest, tmp_path)


def test_runtime_isolates_native_roots_and_disables_history_sync(tmp_path, monkeypatch):
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "synthetic-not-a-credential")
    for name in ("HOME", "COPILOT_HOME", "COPILOT_CUSTOM_INSTRUCTIONS_DIRS", "COPILOT_MODEL"):
        monkeypatch.setenv(name, "ambient")
    paths = runner.Paths(tmp_path / "run")
    paths.workspace.mkdir(parents=True)
    calls = []

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, stdout="--sync-session --secret-env-vars")

    monkeypatch.setattr(runner.subprocess, "run", run)
    cmd = runner.copilot_command("copilot", "synthetic", "session", 30, [CORE])
    assert runner.run_phase(cmd, paths, 1, 240) == 0
    live, kwargs = calls[1]
    assert "--sync-session=off" in live
    assert "--no-remote" not in live
    assert live.count("--plugin-dir") == 1
    assert "--secret-env-vars" in live
    assert kwargs["timeout"] == 240
    env = kwargs["env"]
    assert env["HOME"] == env["USERPROFILE"] == str(paths.home)
    assert env["COPILOT_HOME"] == str(paths.copilot_home)
    assert env["XDG_CONFIG_HOME"] == str(paths.home / ".config")
    assert env["XDG_CACHE_HOME"] == str(paths.home / ".cache")
    assert env["XDG_STATE_HOME"] == str(paths.home / ".state")
    assert paths.home.is_relative_to(paths.copilot_home)
    assert "COPILOT_CUSTOM_INSTRUCTIONS_DIRS" not in env
    assert "COPILOT_MODEL" not in env
    assert paths.log(1).is_file()


@pytest.mark.parametrize("help_text", [
    "--no-remote --no-remote-export --secret-env-vars",
    "--sync-session-status --secret-env-vars", "--sync-session",
])
def test_missing_current_privacy_controls_stops_before_agent(tmp_path, monkeypatch, help_text):
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "synthetic-not-a-credential")
    paths = runner.Paths(tmp_path / "run")
    paths.workspace.mkdir(parents=True)
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=help_text)

    monkeypatch.setattr(runner.subprocess, "run", run)
    with pytest.raises(runner.SetupError, match="CLI must support"):
        runner.run_phase(["copilot"], paths, 1, 240)
    assert len(calls) == 1
    assert not paths.log(1).exists()


def test_runtime_timeout_keeps_failure_not_success(tmp_path, monkeypatch):
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "synthetic-not-a-credential")
    paths = runner.Paths(tmp_path / "run")
    paths.workspace.mkdir(parents=True)

    def run(cmd, **kwargs):
        if "--help" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="--sync-session --secret-env-vars")
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(runner.subprocess, "run", run)
    cmd = runner.copilot_command("copilot", "synthetic", "session", 30, [CORE])
    assert runner.run_phase(cmd, paths, 1, 1) == -1

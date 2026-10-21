"""Real thin launchers and Python runner, offline and without any CLI/model."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv

import pytest

ROOT = Path(__file__).resolve().parents[3]
PIPELINE = ROOT / "eval/pipeline"
PWSH = shutil.which("pwsh")
BASH = (str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) /
            "Git/usr/bin/bash.exe") if os.name == "nt" else shutil.which("bash"))
NATIVES = ["python", "powershell", "bash"]


def execute(argv, env, cwd=None):
    return subprocess.run([str(a) for a in argv], env=env, cwd=cwd, text=True,
                          capture_output=True, encoding="utf-8", errors="replace", timeout=90)


@pytest.fixture(scope="session")
def shell_commands(tmp_path_factory):
    """No host executable directory on PATH, even in the missing-Python cases."""
    tools = tmp_path_factory.mktemp("thin-launcher-utilities")
    if BASH and Path(BASH).is_file():
        source = (Path(BASH).parent / "dirname.exe" if os.name == "nt"
                  else Path(shutil.which("dirname")))
        shutil.copy2(source, tools / source.name)
        if os.name == "nt":
            for library in source.parent.glob("*.dll"):
                shutil.copy2(library, tools / library.name)
    return tools


@pytest.fixture
def offline_env(tmp_path, shell_commands):
    home = tmp_path / "empty-home"
    home.mkdir()
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"}}
    env.update(PATH=os.pathsep.join([str(Path(sys.executable).parent), str(shell_commands)]),
               HOME=str(home), USERPROFILE=str(home), TEMP=str(home), TMP=str(home),
               XDG_CONFIG_HOME=str(home), APPDATA=str(home), LOCALAPPDATA=str(home),
               DEEPEVAL_TELEMETRY_OPT_OUT="1")
    assert shutil.which("copilot", path=env["PATH"]) is None
    return env


def runner(native, output, *options, pipeline=PIPELINE):
    if native == "python":
        return [sys.executable, "-I", "-S", "-B", "-X", "utf8", pipeline / "run_eval.py",
                "--suite", "custom-eval", "--output-root", output, *options]
    if native == "bash":
        if not BASH or not Path(BASH).is_file():
            pytest.skip("Bash is not installed")
        return [BASH, "--noprofile", "--norc", (pipeline / "run-eval.sh").as_posix(),
                "--suite", "custom-eval", "--output-root", output, *options]
    if not PWSH:
        pytest.skip("PowerShell is not installed")
    names = {"--task-filter": "-TaskFilter", "--dry-run": "-DryRun",
             "--pass-threshold": "-PassThreshold", "--scorer": "-Scorer",
             "--no-isolation": "-NoIsolation", "--agent-model": "-AgentModel",
             "--judge-model": "-JudgeModel"}
    return [PWSH, "-NoProfile", "-NonInteractive", "-File", pipeline / "run-eval.ps1",
            "-Suite", "custom-eval", "-OutputRoot", output,
            *(names.get(str(option), option) for option in options)]


def read_summary(output):
    path, = output.glob("*/summary.json")
    return path, json.loads(path.read_text("utf-8"))


def assert_inventory(summary, count, status):
    assert summary["total"] == len(summary["tasks"]) == count
    assert {task["status"] for task in summary["tasks"]} == {status}
    assert sum(summary[k] for k in (
        "resolved", "partial", "failed", "unverified", "setup_error_count",
        "blocked_approval_count", "skipped",
    )) == count
    assert summary["resolved"] == summary["partial"] == summary["failed"] == 0
    for key in ("resolved_pct", "partial_pct", "failed_pct"):
        assert key in summary, f"missing required percentage: {key}"
        assert summary[key] is None
    assert "scorer_comparison" not in summary


@pytest.mark.parametrize("key", ["resolved_pct", "partial_pct", "failed_pct"])
def test_inventory_requires_explicit_null_percentages(tmp_path, key):
    from agile_eval.provenance import failed_start

    run = tmp_path / "failed-run"
    run.mkdir()
    failed_start(run, run.name, ["task-a"], "custom-eval")
    summary = json.loads((run / "summary.json").read_text("utf-8"))
    assert_inventory(summary, 1, "setup_error")
    # The old .get() assertion admitted absence; a nullable field is required.
    del summary[key]
    with pytest.raises(AssertionError, match=key):
        assert_inventory(summary, 1, "setup_error")
    summary[key] = 0
    with pytest.raises(AssertionError):
        assert_inventory(summary, 1, "setup_error")


@pytest.mark.parametrize("native", NATIVES)
def test_full_native_runner_dry_run_stages_all_tasks_without_model_calls(
        native, tmp_path, offline_env):
    from agile_eval.workspace_inputs import immutable_inputs
    from agile_eval.provenance import binding
    from agile_eval.file_io import identity, read_json

    output = tmp_path / "output with spaces"
    proc = execute(runner(native, output, "--dry-run"), offline_env, cwd=tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OS sandbox unavailable" in proc.stdout
    path, summary = read_summary(output)
    assert_inventory(summary, 10, "skipped")
    assert summary["dry_run"] is True
    assert summary["scorer"] == "deepeval"
    assert "unavailable OS sandbox" in summary["live_run_status"]
    manifest = read_json(path.parent / "run-provenance.json")
    context = manifest["context"]
    assert context["run_id"] == summary["run_id"]
    assert context["selected_task_ids"] == sorted(task["id"] for task in summary["tasks"])
    assert manifest["schema_version"] == 1
    assert manifest["context_sha256"] == identity(context)
    assert manifest["result_bindings"] == [binding(path, context, None)]
    assert context["toolchain"]["native"] == "python"
    assert context["toolchain"]["native_version"]
    assert context["toolchain"]["copilot_cli"] is None
    assert context["models"]["observed"] == {}
    assert context["execution"]["execution_ready"] is False
    for task in summary["tasks"]:
        assert context["tasks"][task["id"]]["input_status"] == "captured"
        immutable_inputs(path.parent / "ws" / task["id"], path.parent / "baseline" / task["id"])
        assert task["grading"] == {"deepeval": None}


@pytest.mark.parametrize("native", NATIVES)
def test_live_runner_fails_closed_before_staging_or_startup_injection(native, tmp_path, offline_env):
    marker = tmp_path / "injected"
    (tmp_path / "sitecustomize.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n", encoding="utf-8")
    env = dict(offline_env, PYTHONPATH=str(tmp_path), PYTHONSTARTUP=str(tmp_path / "sitecustomize.py"),
               GH_TOKEN="synthetic-not-real", EVAL_EXECUTION_READY="true")
    control = execute([sys.executable, "-c", "pass"], env)
    assert control.returncode == 0 and marker.exists()
    marker.unlink()
    output = tmp_path / "must not stage"
    proc = execute(runner(native, output, "--no-isolation"), env, cwd=tmp_path)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert '"execution_ready":false' in proc.stdout
    assert "live evaluation is disabled" in proc.stderr
    assert "untrusted artifact workers" in proc.stderr
    assert "not execution-readiness certification" in proc.stderr
    assert not output.exists()
    assert not marker.exists()


@pytest.mark.parametrize("native", ["powershell", "bash"])
@pytest.mark.parametrize("dry", [False, True])
def test_missing_python_exits_two_with_actionable_diagnostic_and_no_artifacts(
        native, dry, tmp_path, offline_env, shell_commands):
    env = dict(offline_env, PATH=str(shell_commands))
    assert shutil.which("python", path=env["PATH"]) is None
    assert shutil.which("python3", path=env["PATH"]) is None
    output = tmp_path / "not-created"
    proc = execute(runner(native, output, *(["--dry-run"] if dry else [])), env)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "Python is required" in proc.stderr and "PATH" in proc.stderr
    assert not output.exists()


@pytest.mark.parametrize("native", NATIVES)
@pytest.mark.parametrize("options", [
    ["--task-filter"], ["--scorer"], ["--unsupported-flag"],
    ["--task-filter", "["], ["--task-filter", "^nonexistent$"],
    ["--pass-threshold", "-1"], ["--pass-threshold", "101"],
    ["--pass-threshold", "1.5"], ["--pass-threshold", "75; echo injected"],
    ["--scorer", "shell"], ["--scorer", "both"], ["--scorer", "unknown"],
    ["--agent-model", "same", "--judge-model", "same"],
])
def test_invalid_arguments_never_create_attempt_artifacts(native, options, tmp_path, offline_env):
    output = tmp_path / "not-created"
    proc = execute(runner(native, output, "--dry-run", *options), offline_env)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    if "--scorer" in options and len(options) > 1:
        assert "retired" in proc.stderr and "--scorer deepeval" in proc.stderr
    assert not output.exists()


@pytest.mark.parametrize("native", NATIVES)
def test_regex_selection_and_threshold_boundaries(native, tmp_path, offline_env):
    for threshold in ("0", "100"):
        output = tmp_path / threshold
        proc = execute(runner(native, output, "--dry-run", "--task-filter", "^task-0[13]-",
                              "--pass-threshold", threshold), offline_env)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        _, summary = read_summary(output)
        assert_inventory(summary, 2, "skipped")
        assert [task["id"][:7] for task in summary["tasks"]] == ["task-01", "task-03"]


@pytest.mark.parametrize("native", NATIVES)
def test_swe_dry_manifest_preserves_inventory_and_legacy_wiring_exit(native, tmp_path, offline_env):
    output = tmp_path / "swe"
    argv = runner(native, output, "--dry-run", "--task-filter", "^django")
    argv[argv.index("custom-eval")] = "swe-bench-subset"
    proc = execute(argv, offline_env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    _, summary = read_summary(output)
    assert_inventory(summary, 4, "setup_error")
    assert "SWE-bench task-prep not wired" in proc.stderr


def test_late_prompt_disappearance_is_full_setup_error(tmp_path, copied_repo, monkeypatch):
    from agile_eval import run_eval, prepare_inputs

    pipeline = copied_repo / "eval/pipeline"
    monkeypatch.setattr(run_eval, "PIPELINE", pipeline)
    monkeypatch.setattr(run_eval, "ROOT", copied_repo)
    prepare_many = prepare_inputs.prepare_many

    def disappear(suite, run, ids):
        result = prepare_many(suite, run, ids)
        (suite / "tasks" / ids[-1] / "prompt.md").unlink()
        return result

    monkeypatch.setattr(prepare_inputs, "prepare_many", disappear)
    output = tmp_path / "output"
    code = run_eval.main(["--suite", "custom-eval", "--dry-run", "--output-root", str(output)])
    assert code == 2
    _, row = read_summary(output)
    assert_inventory(row, 10, "setup_error")


@pytest.fixture
def copied_repo(tmp_path):
    repo = tmp_path / "repo with spaces"
    for name in (
        "eval/authorization.py",
        "eval/pipeline/run_eval.py", "eval/pipeline/run-eval.sh", "eval/pipeline/run-eval.ps1",
        "eval/pipeline/score-judge.sh", "eval/pipeline/score-judge.ps1",
        "eval/deepeval/score_workspace.py",
        "eval/pipeline/custom-eval/prepare_inputs.py", "eval/deepeval/requirements.lock.txt",
        "eval/deepeval/requirements-yaml.lock.txt",
        "plugins/agile-agents-core/skills/acceptance-grading/SKILL.md",
    ):
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, path)
    shutil.copytree(ROOT / "eval/python/agile_eval", repo / "eval/python/agile_eval",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(PIPELINE / "custom-eval/tasks", repo / "eval/pipeline/custom-eval/tasks")
    return repo


@pytest.mark.parametrize("native", NATIVES)
@pytest.mark.parametrize("failure", ["prompt", "utf8", "profile", "dependency", "provenance"])
def test_setup_failure_preserves_full_ten_task_inventory(
        native, failure, tmp_path, offline_env, copied_repo):
    pipeline = copied_repo / "eval/pipeline"
    task = next((pipeline / "custom-eval/tasks").iterdir())
    if failure == "prompt":
        (task / "prompt.md").unlink()
    elif failure == "utf8":
        (task / "prompt.md").write_bytes(b"\xff")
    elif failure == "profile":
        (task / "solution-profile.yaml").write_text("identity: {}", encoding="utf-8")
    elif failure == "dependency":
        (copied_repo / "eval/python/agile_eval/prepare_inputs.py").write_text(
            "raise ImportError('missing yaml')\n", encoding="utf-8")
    else:
        # An invalid requested identifier exercises real provenance capture failure.
        offline_env["AGENT_MODEL"] = "invalid model"
    output = tmp_path / "output"
    proc = execute(runner(native, output, "--dry-run", pipeline=pipeline), offline_env)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    path, summary = read_summary(output)
    assert_inventory(summary, 10, "setup_error")
    assert summary["setup_error_count"] == 10
    manifest = json.loads((path.parent / "run-provenance.json").read_text("utf-8"))
    if failure == "provenance":
        assert manifest["attribution"] == "unavailable"
        assert len(manifest["selected_task_ids"]) == 10
        assert manifest["result_bindings"] == []
    else:
        assert len(manifest["context"]["selected_task_ids"]) == 10
        assert manifest["result_bindings"][-1]["reference"] == "summary.json"
    if failure in {"prompt", "utf8", "profile"}:
        assert {t["preparation_status"] for t in summary["tasks"]} == {"setup_error", "not_prepared"}
    if failure == "dependency":
        assert "PyYAML is required" in proc.stderr
    assert not (path.parent / "ws").exists()


@pytest.mark.parametrize("stage", ["package_path", "dependency_import", "preparation"])
@pytest.mark.parametrize("exception_name", [
    "RuntimeError", "RecursionError", "KeyboardInterrupt", "SystemExit",
    "AsyncCancelledError", "FutureCancelledError",
])
def test_startup_exceptions_retain_inventory_but_interrupts_propagate(
        stage, exception_name, tmp_path, offline_env, copied_repo):
    pipeline = copied_repo / "eval/pipeline"
    output = tmp_path / "output"
    script = """
import sys
import builtins
from asyncio import CancelledError as AsyncCancelledError
from concurrent.futures import CancelledError as FutureCancelledError
sys.path.insert(0, sys.argv[1])
from agile_eval import run_eval
stage, name = sys.argv[3:]
exception = dict(RuntimeError=RuntimeError, RecursionError=RecursionError,
                 KeyboardInterrupt=KeyboardInterrupt, SystemExit=SystemExit,
                 AsyncCancelledError=AsyncCancelledError,
                 FutureCancelledError=FutureCancelledError)[name]
def fail(*args, **kwargs):
    raise exception('private-exception-detail' * 10000)
original_import = builtins.__import__
forbidden = []
def guarded_import(name, *args, **kwargs):
    if name.split('.')[0] in {'copilot', 'deepeval'}:
        forbidden.append(name)
        raise AssertionError('SDK/model imports forbidden')
    if stage == 'dependency_import' and name == 'agile_eval.prepare_inputs':
        fail()
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded_import
def deny_network(event, args):
    if event.startswith(('socket.connect', 'socket.bind', 'socket.getaddrinfo')):
        forbidden.append(event)
        raise AssertionError('network forbidden')
sys.addaudithook(deny_network)
if stage == 'package_path':
    run_eval.dependency_path = fail
elif stage == 'preparation':
    run_eval.dependency_path()
    from agile_eval import prepare_inputs
    prepare_inputs.prepare_many = fail
try:
    code = run_eval.main(['--suite', 'custom-eval', '--dry-run', '--output-root', sys.argv[2]])
except exception:
    assert name not in {'RuntimeError', 'RecursionError'}, 'ordinary exception escaped'
    print('interrupt propagated: ' + name)
    code = 73
assert not any(n.split('.')[0] in {'copilot', 'deepeval'} for n in sys.modules)
assert not forbidden, forbidden
raise SystemExit(code)
"""
    proc = execute(
        [sys.executable, "-I", "-S", "-B", "-X", "utf8", "-c", script,
         copied_repo / "eval/python", output, stage, exception_name], offline_env, cwd=tmp_path,
    )
    run, = output.iterdir()
    assert not (run / "ws").exists()
    assert not (run / "baseline").exists()
    assert not (run / "preflight.json").exists()
    assert "private-exception-detail" not in proc.stdout + proc.stderr
    if exception_name not in {"RuntimeError", "RecursionError"}:
        assert proc.returncode == 73, proc.stdout + proc.stderr
        assert f"interrupt propagated: {exception_name}" in proc.stdout
        assert not (run / "summary.json").exists()
        assert not list(run.glob("*.log"))
        return

    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "SETUP ERROR" in proc.stderr
    path, summary = read_summary(output)
    assert_inventory(summary, 10, "setup_error")
    assert summary["setup_error_count"] == 10
    assert len(summary["setup_errors"]) == 1
    assert len(summary["setup_errors"][0]) < 160
    assert "private-exception-detail" not in path.read_text("utf-8")
    manifest = json.loads((run / "run-provenance.json").read_text("utf-8"))
    if stage == "package_path":
        assert manifest["attribution"] == "unavailable"
        assert manifest["selected_task_ids"] == sorted(t["id"] for t in summary["tasks"])
        assert manifest["result_bindings"] == []
    else:
        assert manifest["context"]["selected_task_ids"] == sorted(t["id"] for t in summary["tasks"])
        assert manifest["result_bindings"][-1]["reference"] == "summary.json"
        assert len(list(run.glob("*.log"))) == 10


def test_recursive_yaml_preflight_retains_full_setup_inventory(tmp_path, offline_env, copied_repo):
    pipeline = copied_repo / "eval/pipeline"
    task = next((pipeline / "custom-eval/tasks").iterdir())
    (task / "solution-profile.yaml").write_text(
        "nested: " + "[" * 2000 + "0" + "]" * 2000, encoding="utf-8",
    )
    output = tmp_path / "output"
    proc = execute(runner("python", output, "--dry-run", pipeline=pipeline), offline_env)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    path, summary = read_summary(output)
    assert_inventory(summary, 10, "setup_error")
    assert summary["setup_errors"] == [
        "fixture preparation failed during initialization or preflight; no agent or judge was invoked"
    ]
    assert not (path.parent / "ws").exists()
    assert not (path.parent / "baseline").exists()
    assert "Traceback" not in proc.stderr


@pytest.mark.parametrize("native", NATIVES)
def test_literal_prompt_content_and_output_siblings_do_not_change_source_identity(
        native, copied_repo, offline_env):
    from agile_eval.file_io import read_json
    from agile_eval.provenance import finalize

    pipeline = copied_repo / "eval/pipeline"
    task = next((pipeline / "custom-eval/tasks").iterdir())
    prompt = "'\"; & | < > $HOME `echo` * ? {{ARTIFACTS}} Grüße 東京\n\n".encode("utf-8")
    (task / "prompt.md").write_bytes(prompt)
    output = copied_repo / "eval/custom-output"
    argv = runner(native, output, "--dry-run", pipeline=pipeline)
    first = execute(argv, offline_env, cwd=copied_repo.parent)
    assert first.returncode == 0, first.stdout + first.stderr
    path, _ = read_summary(output)
    before = read_json(path.parent / "run-provenance.json")["context"]
    path.write_text('{"retained":"changed"}', encoding="utf-8")
    second = execute(argv, offline_env, cwd=copied_repo.parent)
    assert second.returncode == 0, second.stdout + second.stderr
    other, = [run for run in output.iterdir() if run != path.parent]
    after = read_json(other / "run-provenance.json")["context"]
    assert before["run_id"] != after["run_id"]
    assert before["tasks"] == after["tasks"]
    assert before["harness"]["files"] == after["harness"]["files"]
    assert before["harness"]["source_fingerprint"] == after["harness"]["source_fingerprint"]
    assert not any(name.startswith("eval/custom-output/") for name in after["harness"]["files"])
    assert (task / "prompt.md").read_bytes() == prompt
    shutil.copyfile(path, other / "summary.json")
    with pytest.raises(ValueError, match="inventory mismatch|invalid summary"):
        finalize(other, after)


@pytest.mark.parametrize("native", NATIVES)
def test_copied_package_launches_with_unicode_and_literal_path_arguments(
        native, copied_repo, offline_env):
    relocated = copied_repo.with_name("repo Grüße 東京 ; & $ [literal]")
    copied_repo.rename(relocated)
    output = relocated.parent / f"output Grüße 東京 ; & $ [literal] {native}"
    proc = execute(
        runner(native, output, "--dry-run", "--task-filter", "^task-(01|03)-",
               pipeline=relocated / "eval/pipeline"),
        offline_env, cwd=relocated.parent,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    path, summary = read_summary(output)
    assert_inventory(summary, 2, "skipped")
    assert [task["id"][:7] for task in summary["tasks"]] == ["task-01", "task-03"]
    manifest = json.loads((path.parent / "run-provenance.json").read_text("utf-8"))
    assert "eval/python/agile_eval/run_eval.py" in manifest["context"]["harness"]["files"]
    score = execute(
        [*scorer(native, pipeline=relocated / "eval/pipeline"),
         "-SelfTest" if native == "powershell" else "--self-test"],
        offline_env, cwd=relocated.parent,
    )
    assert score.returncode == 0, score.stdout + score.stderr


@pytest.mark.parametrize("native", NATIVES)
def test_no_site_hooks_with_venv_yaml_and_no_deepeval(native, tmp_path, offline_env):
    import yaml

    environment = tmp_path / "venv with spaces"
    venv.EnvBuilder(with_pip=False, symlinks=os.name != "nt").create(environment)
    interpreter = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    packages = (environment / "Lib/site-packages" if os.name == "nt" else
                environment / f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages")
    shutil.copytree(Path(yaml.__file__).parent, packages / "yaml")
    marker = tmp_path / "site-hook"
    (packages / "injection.pth").write_text(
        f"import pathlib; pathlib.Path({str(marker)!r}).touch()\n", encoding="utf-8")
    env = dict(offline_env, PATH=os.pathsep.join(
        [str(interpreter.parent), offline_env["PATH"].split(os.pathsep)[-1]]))
    control = execute([interpreter, "-c", "pass"], env)
    assert control.returncode == 0 and marker.exists()
    marker.unlink()
    output = tmp_path / "output"
    argv = runner(native, output, "--dry-run")
    if native == "python":
        argv[0] = interpreter
    proc = execute(argv, env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not marker.exists()
    path, row = read_summary(output)
    assert_inventory(row, 10, "skipped")
    context = json.loads((path.parent / "run-provenance.json").read_text("utf-8"))["context"]
    assert context["toolchain"]["packages"]["deepeval"] is None
    assert context["toolchain"]["packages"]["PyYAML"] is None  # copied package, no dist-info


@pytest.fixture
def workspace(tmp_path):
    from agile_eval.prepare_inputs import prepare

    task = PIPELINE / "custom-eval/tasks/task-10-helm-to-kustomize"
    ws = tmp_path / "run/ws" / task.name
    baseline = tmp_path / "run/baseline" / task.name
    prepare(task, ws, baseline)
    acceptance = tmp_path / "acceptance.md"
    acceptance.write_text("1. README exists.", encoding="utf-8")
    return ws, acceptance, baseline


def scorer(native, ws=None, acceptance=None, baseline=None, result=None, timeout=900,
           pipeline=PIPELINE):
    if native == "powershell":
        argv = [PWSH, "-NoProfile", "-File", pipeline / "score-judge.ps1"]
        if ws:
            argv += ["-Workspace", ws, "-AcceptancePath", acceptance,
                     "-BaselineDirectory", baseline, "-ResultJson", result,
                     "-JudgeModel", "offline-requested-judge", "-Timeout", timeout]
    else:
        argv = ([BASH, (pipeline / "score-judge.sh").as_posix()] if native == "bash" else
                [sys.executable, "-I", "-S", "-B", pipeline.parent / "deepeval/score_workspace.py"])
        if ws:
            argv += [ws, acceptance, "--baseline-dir", baseline, "--result-json", result,
                     "--model", "offline-requested-judge", "--timeout", timeout]
    return argv


@pytest.mark.parametrize("native", NATIVES)
@pytest.mark.parametrize("timeout", [1, 900])
def test_native_scorers_disable_host_judging_and_emit_unverified(
        native, timeout, workspace, tmp_path, offline_env):
    ws, acceptance, baseline = workspace
    secret = "synthetic-not-a-real-credential"
    (ws / "Source.cs").write_text(f'const string Token = "{secret}";', encoding="utf-8")
    result = tmp_path / "result.json"
    proc = execute(scorer(native, ws, acceptance, baseline, result, timeout), offline_env)
    assert proc.returncode == 3, proc.stdout + proc.stderr
    row = json.loads(result.read_text("utf-8"))
    assert row["status"] == "unverified" and row["exit_code"] == 3
    assert row["expected_criteria"] == 1 and row["claimed_verdict"] == "UNVERIFIED"
    assert row["criteria"] == [{"id": 1, "status": "UNVERIFIED"}]
    assert row["raw_response_persisted"] is False
    assert secret not in result.read_text("utf-8")
    manifest = json.loads(result.with_name(result.name + ".provenance.json").read_text("utf-8"))
    assert manifest["context"]["scorer"] == "deepeval"
    assert manifest["context"]["models"]["requested"]["judge"] == "offline-requested-judge"
    assert manifest["context"]["models"]["observed"] == {}
    assert manifest["result_bindings"][0]["task_id"] == ws.name
    assert manifest["result_bindings"][0]["run_id"] == ws.parent.parent.name


@pytest.mark.parametrize("native", NATIVES)
def test_missing_scorer_arguments_report_setup_not_partial(native, offline_env):
    proc = execute(scorer(native), offline_env)
    assert proc.returncode == 4, proc.stdout + proc.stderr
    assert '"status": "setup_error"' in proc.stdout

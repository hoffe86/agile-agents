"""Exercise native scorers and runner scoring/summary segments with a local fake CLI.

The production runners' human-approval block is tested separately, unmodified.
Post-approval segments are executed as units with a fake dev-lead; no approval
is fabricated, and no real model executable is reachable through the test PATH.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
PIPELINE = ROOT / "eval/pipeline"
BASH = shutil.which("bash")
if os.name == "nt":
    BASH = str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe")
PWSH = shutil.which("pwsh")


def execute(argv, env):
    return subprocess.run([str(a) for a in argv], env=env, text=True, capture_output=True,
                          encoding="utf-8", errors="replace", timeout=90)


@pytest.fixture
def fake_cli(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "copilot.py"
    script.write_text(
        "#!python\n"
        "import json,os,sys\n"
        "from pathlib import Path\n"
        "counter=Path(os.environ['FAKE_COUNTER'])\n"
        "with counter.open('a',encoding='utf-8') as stream: stream.write(json.dumps(sys.argv[1:])+'\\n')\n"
        "raise SystemExit(99)\n", encoding="utf-8",
    )
    if os.name == "nt":
        # Windows CreateProcess searches for .exe, not a .cmd mock. Use pip's
        # already-installed native Python launcher, without another toolchain.
        from pip._vendor.distlib.scripts import ScriptMaker
        maker = ScriptMaker(str(bin_dir), str(bin_dir))
        maker.force = True
        maker.make("copilot.py")
        executable = bin_dir / "copilot.exe"
        assert executable.is_file()
    else:
        executable = bin_dir / "copilot"
        executable.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}"\n', encoding="utf-8")
        executable.chmod(0o700)
    env = os.environ.copy()
    safe_dirs = [str(Path(sys.executable).parent)]
    if PWSH:
        safe_dirs.append(str(Path(PWSH).parent))
    if BASH:
        safe_dirs.append(str(Path(BASH).parent))
        if os.name == "nt":
            safe_dirs.append(str(Path(BASH).parent.parent / "usr/bin"))
    if os.name == "nt":
        safe_dirs.extend([os.environ["SystemRoot"] + "/System32", os.environ["SystemRoot"]])
    real_copilot = shutil.which("copilot")
    if real_copilot:
        real_dir = Path(real_copilot).resolve().parent
        safe_dirs = [directory for directory in safe_dirs
                     if Path(directory).resolve() != real_dir]
    env["PATH"] = os.pathsep.join([str(bin_dir), *safe_dirs])
    env["FAKE_COUNTER"] = str(tmp_path / "calls.txt")
    env["FAKE_RESPONSES"] = "[]"
    env["DEEPEVAL_TELEMETRY_OPT_OUT"] = "1"
    home = tmp_path / "empty-home"
    home.mkdir()
    env["HOME"] = env["USERPROFILE"] = str(home)
    # No real credentials are available to these subprocesses.
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "COPILOT_GITHUB_TOKEN", "OPENAI_API_KEY"):
        env.pop(name, None)
    assert Path(shutil.which("copilot", path=env["PATH"])).resolve() == executable.resolve()
    return env


@pytest.fixture
def workspace(tmp_path):
    sys.path.insert(0, str(PIPELINE / "custom-eval"))
    from prepare_inputs import prepare

    task = PIPELINE / "custom-eval/tasks/task-10-helm-to-kustomize"
    ws = tmp_path / "run/ws" / task.name
    baseline = tmp_path / "run/baseline" / task.name
    prepare(task, ws, baseline)
    (ws / "README.md").write_text("produced deliverable", encoding="utf-8")
    acceptance = tmp_path / "acceptance.md"
    acceptance.write_text("1. README exists.", encoding="utf-8")
    return ws, acceptance, baseline


def scorer_command(native, ws, acceptance, result, timeout=900):
    if native == "powershell":
        return [PWSH, "-NoProfile", "-File", PIPELINE / "score-judge.ps1",
                "-Workspace", ws, "-AcceptancePath", acceptance, "-ResultJson", result,
                "-Timeout", timeout]
    if native == "bash":
        return [BASH, (PIPELINE / "score-judge.sh").as_posix(), ws.as_posix(),
                acceptance.as_posix(), "--result-json", result.as_posix(),
                "--timeout", timeout]
    return [sys.executable, ROOT / "eval/deepeval/score_workspace.py", ws, acceptance,
            "--result-json", result, "--timeout", timeout]


@pytest.mark.parametrize("native", ["powershell", "bash"])
def test_live_runner_fails_closed_before_staging_or_cli(native, fake_cli, tmp_path):
    output_root = tmp_path / "runs"
    if native == "powershell":
        command = [
            PWSH, "-NoProfile", "-File", PIPELINE / "run-eval.ps1",
            "-Suite", "custom-eval", "-TaskFilter", "task-10",
            "-OutputRoot", output_root,
        ]
    else:
        command = [
            BASH, (PIPELINE / "run-eval.sh").as_posix(),
            "--suite", "custom-eval", "--task-filter", "task-10",
            "--output-root", output_root.as_posix(),
        ]
    proc = execute(command, fake_cli)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "OS sandbox" in proc.stderr
    assert not output_root.exists(), "live runner staged files before failing closed"
    assert not Path(fake_cli["FAKE_COUNTER"]).exists(), "live runner invoked the fake CLI"


@pytest.mark.parametrize("native", ["powershell", "bash"])
def test_dry_run_stages_offline_without_invoking_cli(native, fake_cli, tmp_path):
    output_root = tmp_path / "runs"
    if native == "powershell":
        command = [
            PWSH, "-NoProfile", "-File", PIPELINE / "run-eval.ps1",
            "-Suite", "custom-eval", "-TaskFilter", "task-10",
            "-OutputRoot", output_root, "-DryRun",
        ]
    else:
        command = [
            BASH, (PIPELINE / "run-eval.sh").as_posix(),
            "--suite", "custom-eval", "--task-filter", "task-10",
            "--output-root", output_root.as_posix(), "--dry-run",
        ]
    proc = execute(command, fake_cli)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OS sandbox unavailable" in proc.stdout
    run_dirs = list(output_root.iterdir())
    assert len(run_dirs) == 1
    summary = json.loads((run_dirs[0] / "summary.json").read_text(encoding="utf-8-sig"))
    assert summary["dry_run"] is True
    assert summary["tasks"][0]["status"] == "skipped"
    assert "unavailable OS sandbox" in summary["live_run_status"]
    assert not Path(fake_cli["FAKE_COUNTER"]).exists(), "dry run invoked the fake CLI"


@pytest.mark.parametrize("native", ["powershell", "bash", "deepeval"])
def test_native_scorers_disable_host_judging_and_emit_unverified(
        native, workspace, fake_cli, tmp_path):
    ws, acceptance, baseline = workspace
    result = tmp_path / "result.json"
    command = scorer_command(native, ws, acceptance, result)
    if native == "powershell":
        command += ["-BaselineDirectory", baseline]
    elif native == "bash":
        command += ["--baseline-dir", baseline]
    else:
        command += ["--baseline-dir", baseline]
    (ws / "src").mkdir(exist_ok=True)
    (ws / "src" / "Credential.cs").write_text(
        'class C { const string Token = "ghp_fixtureNotARealCredential_1234567890"; }',
        encoding="utf-8",
    )
    (ws / "config.yaml").write_text(
        'password: "fixture-not-a-real-password-123456"', encoding="utf-8"
    )
    proc = execute(command, fake_cli)
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert not Path(fake_cli["FAKE_COUNTER"]).exists(), "judge executable was invoked"
    row = json.loads(result.read_text())
    assert row["status"] == "unverified" and row["exit_code"] == 3
    assert row["expected_criteria"] == 1
    assert row["claimed_verdict"] == "UNVERIFIED"
    assert row["criteria"] == [{"id": 1, "status": "UNVERIFIED"}]
    assert row["raw_response_persisted"] is False


@pytest.mark.parametrize("native", ["powershell", "bash", "deepeval"])
def test_judge_timeout_option_cannot_enable_host_execution(native, workspace, fake_cli, tmp_path):
    ws, acceptance, baseline = workspace
    result = tmp_path / "result.json"
    command = scorer_command(native, ws, acceptance, result, timeout=1)
    if native == "powershell":
        command += ["-BaselineDirectory", baseline]
    else:
        command += ["--baseline-dir", baseline]
    proc = execute(command, fake_cli)
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert json.loads(result.read_text())["status"] == "unverified"
    assert not Path(fake_cli["FAKE_COUNTER"]).exists()


@pytest.mark.parametrize("native", ["powershell", "bash", "deepeval"])
def test_missing_scorer_arguments_report_setup_not_partial(native, fake_cli):
    if native == "powershell":
        argv = [PWSH, "-NoProfile", "-File", PIPELINE / "score-judge.ps1"]
    elif native == "bash":
        argv = [BASH, (PIPELINE / "score-judge.sh").as_posix()]
    else:
        argv = [sys.executable, ROOT / "eval/deepeval/score_workspace.py"]
    proc = execute(argv, fake_cli)
    assert proc.returncode == 4, proc.stdout + proc.stderr
    assert '"status": "setup_error"' in proc.stdout
    assert not Path(fake_cli["FAKE_COUNTER"]).exists()


def segment(source, start, end):
    return source[source.index(start):source.index(end)]


def scoring_unit(native, tmp_path, env, statuses):
    """Run unchanged post-approval scoring/summary source in a disposable native unit."""
    sys.path.insert(0, str(PIPELINE / "custom-eval"))
    from prepare_inputs import prepare

    run = tmp_path / "run"
    run.mkdir()
    task = PIPELINE / "custom-eval/tasks/task-10-helm-to-kustomize"
    prepared = prepare(task, run / "ws" / task.name, run / "baseline" / task.name)
    Path(prepared["workspace"], "README.md").write_text("produced", encoding="utf-8")
    env["FAKE_RESPONSES"] = json.dumps([{"text": response} for response in statuses])
    if native == "powershell":
        source = (PIPELINE / "run-eval.ps1").read_text(encoding="utf-8")
        helpers = segment(source, "function Get-ScoreStatus", "function Invoke-Copilot")
        # $PSScriptRoot points to the test script, so explicitly bind the scoring
        # script root without changing any production logic.
        script = tmp_path / "scoring-unit.ps1"
        bootstrap = f"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repoRoot = '{ROOT}'
$scoringScriptRoot = '{PIPELINE}'
$runDir = '{run}'
$runId = 'offline-unit'
$Suite = 'custom-eval'
$Scorer = 'both'
$DryRun = $false
$PassThreshold = 0
$AgentModel = 'offline-agent'
$JudgeModel = 'offline-judge'
$isolate = $false
$isolatedHome = $null
$tasks = @([pscustomobject]@{{Id='{task.name}'; PromptRef='{task / "prompt.md"}'; Folder='{task}'}})
$preparedTasks = @{{'{task.name}' = @{{workspace='{prepared["workspace"]}'; baseline_dir='{prepared["baseline_dir"]}'}}}}
function Invoke-DevLead {{
    param($PromptText, $Workspace, $BaselineDirectory, $LogPath)
    'offline agent completed' | Set-Content $LogPath
    return 0
}}
"""
        body = source[source.index("# --- Execute each task"):].replace(
            "$PSScriptRoot", "$scoringScriptRoot",
        )
        script.write_text(bootstrap + helpers + body,
                          encoding="utf-8")
        proc = execute([PWSH, "-NoProfile", "-File", script], env)
    else:
        source = (PIPELINE / "run-eval.sh").read_text(encoding="utf-8")
        helpers = segment(source, "run_isolated()", "# --- dev-lead invocation")
        script = tmp_path / "scoring-unit.sh"
        bootstrap = f"""#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT='{ROOT.as_posix()}'
SCRIPT_DIR='{PIPELINE.as_posix()}'
RUN_DIR='{run.as_posix()}'
RUN_ID='offline-unit'
SUITE='custom-eval'
EVAL_SCORER='both'
DRY_RUN=0
PASS_THRESHOLD=0
ISOLATED_HOME=''
AGENT_MODEL='offline-agent'
JUDGE_MODEL='offline-judge'
FILTERED_IDS=('{task.name}')
FILTERED_REFS=('{(task / "prompt.md").as_posix()}')
invoke_dev_lead() {{ printf 'offline agent completed\\n' > "$4"; }}
"""
        script.write_text(bootstrap + helpers + source[source.index("# --- Execute each task"):],
                          encoding="utf-8")
        proc = execute([BASH, script.as_posix()], env)
    for path in (run / "baseline").rglob("*"):
        path.chmod(0o700)
    assert (run / "summary.json").exists(), proc.stdout + proc.stderr
    return proc, json.loads((run / "summary.json").read_text(encoding="utf-8-sig"))


@pytest.mark.parametrize("native", ["powershell", "bash"])
def test_runner_scoring_preserves_unverified_denominator_without_judge_execution(
        native, tmp_path, fake_cli):
    proc, summary = scoring_unit(native, tmp_path, fake_cli, [])
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert summary["total"] == 1
    assert summary["run_status"] == "unverified"
    assert summary["tasks"][0]["status"] == "unverified"
    assert summary["scorer_comparison"][0]["agree"] is True
    assert summary["tasks"][0]["grading"]["shell"]["claimed_verdict"] == "UNVERIFIED"
    assert summary["tasks"][0]["grading"]["deepeval"]["criteria"][0]["status"] == "UNVERIFIED"
    assert not Path(fake_cli["FAKE_COUNTER"]).exists()
    assert sum(summary.get(k, 0) for k in (
        "resolved", "partial", "failed", "unverified", "setup_error_count",
        "blocked_approval_count", "skipped",
    )) == summary["total"]


@pytest.mark.parametrize("native", ["powershell", "bash"])
@pytest.mark.parametrize("invalid_json", [False, True])
def test_native_preparation_exit_two_is_setup_error_not_partial_and_keeps_all_tasks(
        native, invalid_json, tmp_path, fake_cli):
    # A disposable suite contains one valid fixture and one invalid fixture. The
    # all-or-nothing preflight leaves the valid task not_prepared, not discarded.
    root = tmp_path / "repo"
    pipeline = root / "eval/pipeline"
    suite = pipeline / "custom-eval"
    (root / "plugins/agile-agents-core").mkdir(parents=True)
    suite.mkdir(parents=True)
    for name in ("run-eval.ps1", "run-eval.sh"):
        shutil.copy2(PIPELINE / name, pipeline / name)
    if invalid_json:
        (suite / "prepare_inputs.py").write_text(
            "print('not json')\nraise SystemExit(2)\n", encoding="utf-8",
        )
    else:
        shutil.copy2(PIPELINE / "custom-eval/prepare_inputs.py", suite)
    fixture = PIPELINE / "custom-eval/tasks/task-03-bicep-storage-waf"
    shutil.copytree(fixture, suite / "tasks/task-good")
    shutil.copytree(fixture, suite / "tasks/task-bad")
    (suite / "tasks/task-bad/solution-profile.yaml").write_text("identity: {}\n", encoding="utf-8")
    output = tmp_path / "output"
    if native == "powershell":
        argv = [PWSH, "-NoProfile", "-File", pipeline / "run-eval.ps1",
                "-Suite", "custom-eval", "-DryRun", "-OutputRoot", output]
    else:
        argv = [BASH, (pipeline / "run-eval.sh").as_posix(), "--suite", "custom-eval",
                "--dry-run", "--output-root", output.as_posix()]
    proc = execute(argv, fake_cli)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    summary = json.loads(next(output.glob("*/summary.json")).read_text(encoding="utf-8-sig"))
    assert summary["total"] == summary["setup_error_count"] == 2
    assert summary["partial"] == summary["failed"] == summary["unverified"] == 0
    assert {t["status"] for t in summary["tasks"]} == {"setup_error"}
    if not invalid_json:
        assert {t["preparation_status"] for t in summary["tasks"]} == {"setup_error", "not_prepared"}
    assert not Path(fake_cli["FAKE_COUNTER"]).exists()


@pytest.mark.parametrize("native", ["powershell", "bash"])
def test_native_missing_python_setup_preserves_full_suite_denominator(native, tmp_path, fake_cli):
    # Retain native shells/system utilities and the local fake copilot, but remove
    # every Python directory and application-alias directory from executable search.
    directories = [str(Path(fake_cli["FAKE_COUNTER"]).parent / "bin"), str(Path(PWSH).parent)]
    if os.name == "nt":
        directories += [os.environ["SystemRoot"] + "/System32", os.environ["SystemRoot"]]
    else:
        # Portable Unix hosts often put Python in /usr/bin alongside core tools;
        # build an isolated command directory instead of relying on that layout.
        commands = tmp_path / "commands"
        commands.mkdir()
        for name in ("bash", "find", "sort", "date", "mkdir", "dirname", "basename"):
            path = shutil.which(name)
            (commands / name).symlink_to(path)
        directories = [directories[0], str(commands), str(Path(PWSH).parent)]
    fake_cli["PATH"] = os.pathsep.join(directories)
    output = tmp_path / "output"
    if native == "powershell":
        argv = [PWSH, "-NoProfile", "-File", PIPELINE / "run-eval.ps1",
                "-Suite", "custom-eval", "-DryRun", "-OutputRoot", output]
    else:
        argv = [BASH, (PIPELINE / "run-eval.sh").as_posix(), "--suite", "custom-eval",
                "--dry-run", "--output-root", output.as_posix()]
    proc = execute(argv, fake_cli)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    summary = json.loads(next(output.glob("*/summary.json")).read_text(encoding="utf-8-sig"))
    assert summary["total"] == summary["setup_error_count"] == 10
    assert len(summary["tasks"]) == 10
    assert summary["partial"] == summary["failed"] == summary["unverified"] == 0
    assert not Path(fake_cli["FAKE_COUNTER"]).exists()


@pytest.mark.parametrize("native", ["powershell", "bash"])
def test_full_native_runner_dry_run_stages_all_tasks_without_model_calls(native, tmp_path, fake_cli):
    output = tmp_path / "output"
    if native == "powershell":
        argv = [PWSH, "-NoProfile", "-File", PIPELINE / "run-eval.ps1",
                "-Suite", "custom-eval", "-DryRun", "-OutputRoot", output]
    else:
        argv = [BASH, (PIPELINE / "run-eval.sh").as_posix(), "--suite", "custom-eval",
                "--dry-run", "--output-root", output.as_posix()]
    proc = execute(argv, fake_cli)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    summary_path = next(output.glob("*/summary.json"))
    summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
    assert summary["total"] == 10
    assert summary["skipped"] == 10
    assert summary["resolved"] == summary["partial"] == summary["failed"] == summary["unverified"] == 0
    assert not Path(fake_cli["FAKE_COUNTER"]).exists(), "dry-run called a model"
    for path in output.rglob("*"):
        path.chmod(0o700)


@pytest.mark.parametrize("native", ["powershell", "bash"])
def test_full_native_runner_blocks_live_evaluation_before_cli_or_staging(native, tmp_path, fake_cli):
    output = tmp_path / "output"
    if native == "powershell":
        argv = [PWSH, "-NoProfile", "-File", PIPELINE / "run-eval.ps1",
                "-Suite", "custom-eval", "-OutputRoot", output]
    else:
        argv = [BASH, (PIPELINE / "run-eval.sh").as_posix(), "--suite", "custom-eval",
                "--output-root", output.as_posix()]
    proc = execute(argv, fake_cli)
    assert proc.returncode == 2
    assert "live evaluation is disabled" in (proc.stdout + proc.stderr).lower()
    assert not output.exists()
    assert not Path(fake_cli["FAKE_COUNTER"]).exists()

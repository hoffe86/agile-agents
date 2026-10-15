"""Exercise native scorers and runner scoring/summary segments with a local fake CLI.

The production runners' human-approval block is tested separately, unmodified.
Post-approval scoring segments are executed as units with a fake dev-lead; no approval
is fabricated. PATH filtering and an empty HOME are configuration hygiene, not OS
isolation. Only known test fakes run; generated artifacts must never execute here.
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
    # Git/bin/bash.exe is a wrapper that prepends host directories to PATH.
    BASH = str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/usr/bin/bash.exe")
PWSH = shutil.which("pwsh")
if PWSH:
    PWSH = str(Path(PWSH).resolve())

FAKE_ARGUMENTS = ["--prompt", "two words", "Grüße 東京", """'"; & | < > $HOME `echo` * ?"""]


def execute(argv, env):
    return subprocess.run([str(a) for a in argv], env=env, text=True, capture_output=True,
                          encoding="utf-8", errors="replace", timeout=90)


def write_unix_launcher(executable, script):
    executable.write_text(
        f'#!/bin/sh\nexec "{Path(sys.executable).as_posix()}" "{script.as_posix()}" "$@"\n',
        encoding="utf-8",
    )
    executable.chmod(0o700)


def verify_fake_cli(native, env, executable, counter):
    """Fail setup before any runner test if the known fake cannot round-trip argv."""
    resolved = shutil.which("copilot", path=env["PATH"])
    assert resolved and Path(resolved).resolve() == executable.resolve(), (
        "fake CLI missing or shadowed; refusing ambient Copilot fallback"
    )
    probe_env = dict(env, FAKE_EXPECTED=str(executable), FAKE_COUNTER=str(counter),
                     FAKE_ARGUMENTS=json.dumps(FAKE_ARGUMENTS))
    if native == "powershell":
        command = [
            PWSH, "-NoProfile", "-Command",
            "$ErrorActionPreference = 'Stop'; "
            "$resolved = (Get-Command copilot -CommandType Application).Source; "
            "if ($resolved -ne $env:FAKE_EXPECTED) { exit 98 }; "
            "$fakeArgs = @(ConvertFrom-Json $env:FAKE_ARGUMENTS); "
            "& $resolved @fakeArgs; exit $LASTEXITCODE",
        ]
    else:
        command = [
            BASH, "--noprofile", "--norc", "-c",
            'resolved="$(command -v copilot)" || exit 98; '
            '[[ "$resolved" -ef "$1" ]] || exit 98; shift; exec "$resolved" "$@"',
            "fake-probe", executable.as_posix(), *FAKE_ARGUMENTS,
        ]
    proc = execute(command, probe_env)
    assert proc.returncode == 99, f"fake CLI sentinel missing: {proc.stdout}{proc.stderr}"
    assert counter.is_file(), "fake CLI did not record arguments"
    calls = [json.loads(line) for line in counter.read_text(encoding="utf-8").splitlines()]
    assert calls == [FAKE_ARGUMENTS], f"fake CLI changed arguments: {calls!r}"


def isolated_command_path(bin_dir, commands_dir, command_paths):
    """Expose individual utilities, never their Python/Copilot-bearing parents."""
    commands_dir.mkdir()
    for name, source in command_paths.items():
        source = Path(source).resolve(strict=True)
        target = commands_dir / (name + (".exe" if os.name == "nt" else ""))
        if os.name == "nt":
            shutil.copy2(source, target)
            # MSYS utilities need their runtime DLLs beside the executable.
            # Copy only libraries, not other commands from Git's usr/bin.
            for library in source.parent.glob("*.dll"):
                if not (commands_dir / library.name).exists():
                    shutil.copy2(library, commands_dir)
        else:
            target.symlink_to(source)
    return os.pathsep.join([str(bin_dir), str(commands_dir)])


def fake_command_path(bin_dir, shell_commands):
    # A POSIX venv's executable is a symlink to the base Python. Resolving it
    # before selecting its parent loses pyvenv.cfg and the locked dependencies.
    safe_dirs = [str(Path(sys.executable).parent), str(shell_commands)]
    real_copilot = shutil.which("copilot")
    if real_copilot:
        real_dir = Path(real_copilot).resolve().parent
        safe_dirs = [directory for directory in safe_dirs
                     if Path(directory).resolve() != real_dir]
    return os.pathsep.join([str(bin_dir), *safe_dirs])


@pytest.fixture(scope="session")
def shell_commands(tmp_path_factory):
    commands = tmp_path_factory.mktemp("native-utilities") / "commands"
    names = ("bash", "find", "sort", "date", "mkdir", "dirname", "basename", "cat", "awk")
    if os.name == "nt":
        sources = {name: Path(BASH).parent / f"{name}.exe" for name in names}
    else:
        sources = {name: shutil.which(name) for name in names}
    isolated_command_path(commands.parent, commands, sources)
    return commands


@pytest.fixture
def fake_cli(tmp_path, shell_commands):
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
        write_unix_launcher(executable, script)
    env = os.environ.copy()
    env["PATH"] = fake_command_path(bin_dir, shell_commands)
    env["FAKE_COUNTER"] = str(tmp_path / "calls.txt")
    env["FAKE_RESPONSES"] = "[]"
    env["DEEPEVAL_TELEMETRY_OPT_OUT"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    home = tmp_path / "empty-home"
    home.mkdir()
    env["HOME"] = env["USERPROFILE"] = str(home)
    # Remove common credential variables; this is not a credential/OS sandbox.
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "COPILOT_GITHUB_TOKEN", "OPENAI_API_KEY"):
        env.pop(name, None)
    for name in ("BASH_ENV", "ENV"):
        env.pop(name, None)
    for native in ("powershell", "bash"):
        verify_fake_cli(native, env, executable, tmp_path / f"preflight-{native}.jsonl")
    return env


def test_fake_path_and_unix_launcher_preserve_symlinked_interpreter(tmp_path, monkeypatch):
    # Model a POSIX venv even on Windows, where venv normally copies a launcher.
    venv_bin = tmp_path / "venv/bin"
    venv_bin.mkdir(parents=True)
    interpreter = venv_bin / Path(sys.executable).name
    interpreter.symlink_to(sys.executable)
    monkeypatch.setattr(sys, "executable", str(interpreter))
    launcher = tmp_path / "copilot"
    script = tmp_path / "copilot.py"

    path = fake_command_path(tmp_path / "fake-bin", tmp_path / "utilities")
    write_unix_launcher(launcher, script)

    assert path.split(os.pathsep) == [
        str(tmp_path / "fake-bin"), str(venv_bin), str(tmp_path / "utilities"),
    ]
    assert launcher.read_text(encoding="utf-8") == (
        f'#!/bin/sh\nexec "{interpreter.as_posix()}" "{script.as_posix()}" "$@"\n'
    )


@pytest.fixture
def yaml_only_venv(tmp_path):
    import venv
    import yaml

    environment = tmp_path / "isolated-venv"
    venv.EnvBuilder(with_pip=False, symlinks=os.name != "nt").create(environment)
    interpreter = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    proc = execute([
        interpreter, "-I", "-c",
        "import importlib.util,json,sysconfig; "
        "print(json.dumps([importlib.util.find_spec('yaml') is None,"
        "sysconfig.get_path('purelib')]))",
    ], os.environ.copy())
    assert proc.returncode == 0, proc.stdout + proc.stderr
    absent, site_packages = json.loads(proc.stdout)
    assert absent, "isolated venv unexpectedly inherited PyYAML"
    # Reuse the locked package offline; no pip install or ambient site directory.
    package = Path(site_packages) / "yaml"
    shutil.copytree(Path(yaml.__file__).parent, package)
    return interpreter, environment, package / "__init__.py"


@pytest.mark.parametrize("native", ["powershell", "bash"])
def test_native_python_preserves_interpreter_and_yaml_identity(
        native, yaml_only_venv, monkeypatch, request):
    interpreter, environment, yaml_file = yaml_only_venv
    monkeypatch.setattr(sys, "executable", str(interpreter))
    fake_cli = request.getfixturevalue("fake_cli")
    probe = (
        "import json,sys,yaml; "
        "print(json.dumps([sys.executable,sys.prefix,yaml.__file__]))"
    )
    if native == "powershell":
        command = [PWSH, "-NoProfile", "-Command", "python -c $env:PYTHON_PROBE; exit $LASTEXITCODE"]
    else:
        command = [BASH, "--noprofile", "--norc", "-c", 'python -c "$PYTHON_PROBE"']
    proc = execute(command, dict(fake_cli, PYTHON_PROBE=probe))

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert [Path(value) for value in json.loads(proc.stdout)] == [
        interpreter, environment, yaml_file,
    ]
    assert not Path(fake_cli["FAKE_COUNTER"]).exists()


@pytest.mark.parametrize("native", ["powershell", "bash"])
def test_fake_cli_native_invocation_preserves_exact_arguments(native, fake_cli, tmp_path):
    executable = Path(shutil.which("copilot", path=fake_cli["PATH"]))
    verify_fake_cli(native, fake_cli, executable, tmp_path / "positive.jsonl")


def test_unix_fake_launcher_preserves_arguments_even_on_windows(fake_cli, tmp_path):
    # Exercise the Unix wrapper under Git Bash too, not only on Linux CI.
    bin_dir = tmp_path / "unix-bin"
    bin_dir.mkdir()
    executable = bin_dir / "copilot"
    write_unix_launcher(executable, tmp_path / "bin/copilot.py")
    counter = tmp_path / "unix.jsonl"
    env = dict(fake_cli, FAKE_COUNTER=str(counter))
    # Windows command discovery deliberately requires the real .exe; invoke only
    # this known Unix wrapper explicitly, without relaxing the fixture's preflight.
    proc = execute([BASH, executable.as_posix(), *FAKE_ARGUMENTS], env)
    assert proc.returncode == 99, proc.stdout + proc.stderr
    assert [json.loads(line) for line in counter.read_text(encoding="utf-8").splitlines()] == [
        FAKE_ARGUMENTS,
    ]


@pytest.mark.parametrize("native", ["powershell", "bash"])
@pytest.mark.parametrize("failure", ["missing", "broken", "shadowed"])
def test_unusable_fake_fails_setup_without_ambient_fallback(native, failure, fake_cli, tmp_path):
    executable = Path(shutil.which("copilot", path=fake_cli["PATH"]))
    if failure == "missing":
        executable.rename(executable.with_suffix(".disabled"))
    elif failure == "broken":
        executable.write_bytes(b"not-a-valid-fake-cli\n")
    else:
        # A resolvable command is insufficient: it must be this fixture's fake.
        executable = tmp_path / "other-bin" / executable.name
    counter = tmp_path / "unusable.jsonl"

    with pytest.raises(AssertionError, match="fake CLI"):
        verify_fake_cli(native, fake_cli, executable, counter)

    assert not counter.exists(), "setup invoked a different CLI"
    assert not Path(fake_cli["FAKE_COUNTER"]).exists()


def test_missing_python_path_excludes_shared_host_command_directories(tmp_path):
    # Model /usr/bin (including a pwsh entry) or a Windows tools directory
    # containing utilities alongside interpreters and a real CLI.
    host = tmp_path / "usr/bin"
    host.mkdir(parents=True)
    suffix = ".exe" if os.name == "nt" else ""
    for name in ("dirname", "pwsh", "python", "python3", "copilot"):
        executable = host / (name + suffix)
        executable.write_bytes(b"host executable")
        executable.chmod(0o700)
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    commands = tmp_path / "commands"

    path = isolated_command_path(fake_bin, commands, {"dirname": host / ("dirname" + suffix)})

    assert path.split(os.pathsep) == [str(fake_bin), str(commands)]
    assert shutil.which("dirname", path=path) is not None
    assert shutil.which("python", path=path) is None
    assert shutil.which("python3", path=path) is None
    assert shutil.which("copilot", path=path) is None
    assert shutil.which("pwsh", path=path) is None


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
    assert "untrusted artifact workers" in proc.stderr
    assert "not execution-readiness certification" in proc.stderr
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
    from provenance import read_json, identity, binding

    manifest = read_json(run_dirs[0] / "run-provenance.json")
    context = manifest["context"]
    assert context["run_id"] == summary["run_id"]
    assert context["selected_task_ids"] == [task["id"] for task in summary["tasks"]]
    assert manifest["context_sha256"] == identity(context)
    assert manifest["result_bindings"] == [binding(run_dirs[0] / "summary.json", context, None)]
    assert context["toolchain"]["native_version"]
    assert context["toolchain"]["copilot_cli"] is None
    assert context["models"]["observed"] == {}
    assert context["execution"]["execution_ready"] is False
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
        command += ["-JudgeModel", "offline-requested-judge"]
    elif native == "bash":
        command += ["--baseline-dir", baseline]
        command += ["--model", "offline-requested-judge"]
    else:
        command += ["--baseline-dir", baseline]
        command += ["--model", "offline-requested-judge"]
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
    provenance = json.loads(result.with_name(result.name + ".provenance.json").read_text())
    assert provenance["context"]["models"]["requested"]["judge"] == "offline-requested-judge"
    assert provenance["context"]["models"]["observed"] == {}
    assert provenance["result_bindings"][0]["task_id"] == ws.name
    assert provenance["result_bindings"][0]["run_id"] == ws.parent.parent.name


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

    run = tmp_path / "offline-unit"
    run.mkdir()
    task = PIPELINE / "custom-eval/tasks/task-10-helm-to-kustomize"
    prepared = prepare(task, run / "ws" / task.name, run / "baseline" / task.name)
    from provenance import build_context, identity, manifest, write_json

    context = build_context(ROOT, run.name, [task.name], agent="offline-agent",
                            judge="offline-judge", scorer="both")
    write_json(run / "run-provenance.json", manifest(context))
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
$provenanceContext = '{identity(context)}'
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
PROVENANCE_CONTEXT='{identity(context)}'
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
    for name in ("provenance.py", "grading.py"):
        shutil.copy2(ROOT / "eval" / name, root / "eval" / name)
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
    manifest = json.loads(next(output.glob("*/run-provenance.json")).read_text(encoding="utf-8-sig"))
    assert manifest["context"]["selected_task_ids"] == ["task-bad", "task-good"]
    assert manifest["result_bindings"][-1]["reference"] == "summary.json"
    assert summary["partial"] == summary["failed"] == summary["unverified"] == 0
    assert {t["status"] for t in summary["tasks"]} == {"setup_error"}
    if not invalid_json:
        assert {t["preparation_status"] for t in summary["tasks"]} == {"setup_error", "not_prepared"}
    assert not Path(fake_cli["FAKE_COUNTER"]).exists()


@pytest.mark.parametrize("native", ["powershell", "bash"])
def test_native_missing_python_setup_preserves_full_suite_denominator(
        native, tmp_path, fake_cli, shell_commands):
    # Shells run by absolute argv; no shell, system or application-alias directory
    # belongs on PATH, even when pwsh is a symlink under /usr/bin.
    bin_dir = Path(fake_cli["FAKE_COUNTER"]).parent / "bin"
    fake_cli["PATH"] = os.pathsep.join([str(bin_dir), str(shell_commands)])
    assert shutil.which("python", path=fake_cli["PATH"]) is None
    assert shutil.which("python3", path=fake_cli["PATH"]) is None
    assert Path(shutil.which("copilot", path=fake_cli["PATH"])).parent == bin_dir
    # Verify the native shell's actual search too (Windows wrappers can extend it).
    if native == "powershell":
        copilot_name = "copilot.exe" if os.name == "nt" else "copilot"
        probe = [PWSH, "-NoProfile", "-Command",
                 "if (Get-Command python,python3 -CommandType Application -ErrorAction SilentlyContinue) "
                 "{ exit 1 }; "
                 f"$expected = Join-Path (Split-Path $env:FAKE_COUNTER) 'bin/{copilot_name}'; "
                 "if ((Get-Command copilot -CommandType Application).Source -ne $expected) { exit 1 }"]
    else:
        probe = [BASH, "--noprofile", "--norc", "-c",
                 "if command -v python || command -v python3; then exit 1; fi; "
                 '[[ "$(command -v copilot)" -ef "$1" ]]', "probe",
                 (bin_dir / ("copilot.exe" if os.name == "nt" else "copilot")).as_posix()]
    precondition = execute(probe, fake_cli)
    assert precondition.returncode == 0, precondition.stdout + precondition.stderr
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
    manifest = json.loads(next(output.glob("*/run-provenance.json")).read_text(encoding="utf-8-sig"))
    assert manifest["attribution"] == "unavailable"
    assert manifest["reason"] == "python_unavailable"
    assert manifest["result_bindings"] == []
    assert len(summary["tasks"]) == 10
    assert summary["run_status"] == "setup_error"
    assert {task["status"] for task in summary["tasks"]} == {"setup_error"}
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
    manifest = json.loads((summary_path.parent / "run-provenance.json").read_text(encoding="utf-8-sig"))
    assert len(manifest["context"]["selected_task_ids"]) == 10
    assert manifest["context"]["selected_task_ids"] == sorted(t["id"] for t in summary["tasks"])
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


@pytest.mark.parametrize("native", ["powershell", "bash"])
def test_two_native_dry_runs_have_independent_bindings(native, tmp_path, fake_cli):
    from provenance import read_json, finalize

    output = tmp_path / "output"
    if native == "powershell":
        argv = [PWSH, "-NoProfile", "-File", PIPELINE / "run-eval.ps1",
                "-Suite", "custom-eval", "-TaskFilter", "task-01", "-DryRun", "-OutputRoot", output]
    else:
        argv = [BASH, (PIPELINE / "run-eval.sh").as_posix(), "--suite", "custom-eval",
                "--task-filter", "task-01", "--dry-run", "--output-root", output.as_posix()]
    first = execute(argv, fake_cli)
    assert first.returncode == 0, first.stdout + first.stderr
    second = execute(argv, fake_cli)
    assert second.returncode == 0, second.stdout + second.stderr
    runs = sorted(output.iterdir())
    assert len(runs) == 2
    first_context = read_json(runs[0] / "run-provenance.json")["context"]
    second_context = read_json(runs[1] / "run-provenance.json")["context"]
    assert first_context["run_id"] != second_context["run_id"]
    assert first_context["tasks"] == second_context["tasks"]
    shutil.copyfile(runs[0] / "summary.json", runs[1] / "summary.json")
    with pytest.raises(ValueError, match="inventory mismatch"):
        finalize(runs[1], second_context)
    assert not Path(fake_cli["FAKE_COUNTER"]).exists()


@pytest.mark.parametrize("native", ["powershell", "bash"])
def test_native_custom_output_siblings_do_not_contaminate_source_identity(native, tmp_path, fake_cli):
    from provenance import read_json

    # Copy only known harness inputs, never retained runs/environments/research.
    repo = tmp_path / "repo"
    files = [
        "eval/provenance.py", "eval/grading.py", "eval/pipeline/run-eval.ps1",
        "eval/pipeline/run-eval.sh", "eval/pipeline/custom-eval/prepare_inputs.py",
        "eval/deepeval/requirements.lock.txt", "eval/deepeval/requirements-yaml.lock.txt",
        "plugins/agile-agents-core/skills/acceptance-grading/SKILL.md",
    ]
    for name in files:
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    task_id = "task-01-csharp-minimal-api-endpoint"
    shutil.copytree(PIPELINE / "custom-eval/tasks" / task_id,
                    repo / "eval/pipeline/custom-eval/tasks" / task_id)
    output = repo / "eval/custom-output"
    if native == "powershell":
        argv = [PWSH, "-NoProfile", "-File", repo / "eval/pipeline/run-eval.ps1",
                "-Suite", "custom-eval", "-TaskFilter", "task-01", "-DryRun", "-OutputRoot", output]
    else:
        argv = [BASH, (repo / "eval/pipeline/run-eval.sh").as_posix(), "--suite", "custom-eval",
                "--task-filter", "task-01", "--dry-run", "--output-root", output.as_posix()]
    first = execute(argv, fake_cli)
    assert first.returncode == 0, first.stdout + first.stderr
    first_run, = output.iterdir()
    before = read_json(first_run / "run-provenance.json")["context"]["harness"]
    (first_run / "summary.json").write_text('{"retained":"changed"}', encoding="utf-8")
    second = execute(argv, fake_cli)
    assert second.returncode == 0, second.stdout + second.stderr
    second_run, = [path for path in output.iterdir() if path != first_run]
    after = read_json(second_run / "run-provenance.json")["context"]["harness"]
    assert before["files"] == after["files"]
    assert before["source_fingerprint"] == after["source_fingerprint"]
    assert not any(name.startswith("eval/custom-output/") for name in after["files"])
    assert not Path(fake_cli["FAKE_COUNTER"]).exists()

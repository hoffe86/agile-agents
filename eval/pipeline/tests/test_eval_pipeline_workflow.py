"""Offline contracts for workflow provisioning, dispatch, scoring and the live hold."""

from contextlib import chdir, redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "eval-pipeline-outcome.yml"
RUN_EVAL = ROOT / "eval" / "pipeline" / "run-eval.sh"
SKILLS_WORKFLOW = ROOT / ".github" / "workflows" / "eval-skills.yml"
FIXTURE = "eval/deepeval/tests/fixtures/skill-scoring-demo.jsonl"
SCORER = "eval/deepeval/report_skill_usage.py"
REPORT = "eval/pipeline/runs/skill-usage-summary.json"


def _bash_path(bash, path):
    if os.name != "nt":
        return str(path)
    if "Git" in bash:
        resolved = Path(path).resolve().as_posix()
        return f"/{resolved[0].lower()}{resolved[2:]}"
    result = subprocess.run(
        [bash, "-c", 'wslpath -a "$1"', "--", str(path)],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def _find_bash():
    if os.name == "nt":
        for candidate in (
            Path("C:/Program Files/Git/bin/bash.exe"),
            Path("C:/Program Files/Git/usr/bin/bash.exe"),
        ):
            if candidate.is_file():
                return str(candidate)
    return shutil.which("bash")


def _run_bash(bash, script, env_updates):
    exports = "\n".join(
        f"export {key}={shlex.quote(value)}" for key, value in env_updates.items()
    )
    return subprocess.run(
        [bash, "-c", f"{exports}\n{script}"],
        check=False, capture_output=True, text=True,
    )


def _install_cli_sentinel(bash, temp_dir):
    tools = temp_dir / "bin"
    tools.mkdir(parents=True)
    sentinel = temp_dir / "copilot-invoked"
    executable = tools / "copilot"
    executable.write_text(
        '#!/usr/bin/env bash\nprintf invoked > "$COPILOT_SENTINEL"\n',
        encoding="utf-8", newline="\n",
    )
    executable.chmod(0o755)
    return _bash_path(bash, tools), _bash_path(bash, sentinel), sentinel


def _run_actual_runner(bash, args, env_updates):
    # Python is a prelaunch prerequisite; keep the actual interpreter on Windows too.
    env_updates = dict(env_updates)
    env_updates["PATH"] = (
        _bash_path(bash, Path(sys.executable).parent) + ":" + env_updates.get("PATH", "")
    )
    runner = shlex.quote(_bash_path(bash, RUN_EVAL))
    command = "bash " + runner + " " + " ".join(shlex.quote(arg) for arg in args)
    return _run_bash(bash, command, env_updates)


class EvalPipelineWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow_text = WORKFLOW.read_text(encoding="utf-8")
        # BaseLoader preserves GitHub's `on` key rather than YAML 1.1 boolean True.
        cls.workflow = yaml.load(cls.workflow_text, Loader=yaml.BaseLoader)
        cls.skills = yaml.load(SKILLS_WORKFLOW.read_text("utf-8"), Loader=yaml.BaseLoader)
        cls.job = cls.workflow["jobs"]["pipeline-outcome"]
        cls.steps = {step.get("name"): step for step in cls.job["steps"]}
        cls.scoring = cls.steps["Score existing recorded skill invocation"]["run"]
        cls.guard = cls.steps["Validate mode and enforce live hold"]["run"]
        cls.staging = cls.steps["Stage fixtures without execution"]["run"]

    def default_env(self):
        inputs = self.workflow["on"]["workflow_dispatch"]["inputs"]
        return {
            key: inputs[expression.removeprefix("${{ inputs.").removesuffix(" }}")]["default"]
            for key, expression in self.job["env"].items()
            if expression.startswith("${{ inputs.")
        }

    def bash(self):
        bash = _find_bash()
        if not bash:
            self.skipTest("bash is not installed")
        return bash

    def execute_python(self, source, root, env):
        # Execute the exact trusted workflow body, never trace contents.
        with chdir(root), patch.dict(os.environ, env), patch.object(sys, "argv", []):
            exec(compile(source, "<workflow-step>", "exec"), {"__name__": "__main__"})

    def test_only_reviewed_dispatch_inputs_are_exposed(self):
        self.assertEqual(set(self.workflow["on"]), {"workflow_dispatch"})
        self.assertEqual(
            set(self.workflow["on"]["workflow_dispatch"]["inputs"]),
            {"mode", "trace_path", "expected_skills", "suite", "task_filter",
             "pass_threshold", "dry_run"},
        )

    def test_default_actually_scores_synthetic_fixture_not_staging(self):
        inputs = self.workflow["on"]["workflow_dispatch"]["inputs"]
        self.assertEqual(inputs["mode"]["default"], "offline-score")
        self.assertEqual(inputs["mode"]["options"], ["offline-score", "fixture-staging"])
        self.assertEqual(inputs["trace_path"]["default"], FIXTURE)
        self.assertEqual(json.loads(inputs["expected_skills"]["default"]), ["fixture-skill-a"])
        self.assertEqual(inputs["dry_run"]["type"], "boolean")
        self.assertEqual(inputs["dry_run"]["default"], "true")
        self.assertIn("SYNTHETIC", inputs["trace_path"]["description"])
        self.assertEqual(set(self.workflow["jobs"]), {"pipeline-outcome"})
        self.assertEqual(self.job["if"], "${{ github.event_name == 'workflow_dispatch' }}")
        self.assertEqual(self.job["timeout-minutes"], "15")

    def test_native_experiment_is_removed_not_hidden_behind_another_mode(self):
        text = self.workflow_text + repr(self.skills["jobs"]["runtime-contracts"])
        for forbidden in (
            "native_only", "native-qualification", "native_controller",
            "native_runtime_integration", "native_process_contracts", "--run-native",
            "bwrap", "bubblewrap", "slirp4netns", "apt-get", "download-runtime",
            "-m copilot", "copilot-sdk", "secrets.", "github.token", "GH_TOKEN",
            "GITHUB_TOKEN", "deepeval login", "continue-on-error",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)
        self.assertIn("issues/22", self.workflow_text)

    def test_permissions_and_actions_are_least_privilege_and_immutable(self):
        for workflow, job in (
            (self.workflow, self.job),
            (self.skills, self.skills["jobs"]["runtime-contracts"]),
            (self.skills, self.skills["jobs"]["skill-quality"]),
        ):
            self.assertEqual(workflow["permissions"], {"contents": "read"})
            self.assertNotIn("permissions", job)
            self.assertNotIn("environment", job)
            for step in job["steps"]:
                if "uses" in step:
                    self.assertRegex(step["uses"], r"^actions/[\w-]+@[a-f0-9]{40}$")
                    if step["uses"].startswith("actions/checkout@"):
                        self.assertEqual(step["with"]["persist-credentials"], "false")

    def test_run_bodies_never_interpolate_dispatch_expressions(self):
        for step in self.job["steps"]:
            self.assertNotIn("${{", step.get("run", ""))

    def test_live_hold_precedes_checkout_and_all_provisioning(self):
        self.assertEqual(self.job["steps"][0]["name"], "Validate mode and enforce live hold")
        self.assertNotIn("if", self.job["steps"][0])
        for mode in ("offline-score", "fixture-staging"):
            for dry_run in ("false", "", "TRUE"):
                with self.subTest(mode=mode, dry_run=dry_run):
                    result = _run_bash(
                        self.bash(), self.guard,
                        self.default_env() | {"EVAL_MODE": mode, "DRY_RUN": dry_run},
                    )
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn("live evaluation is disabled", result.stdout)
                    self.assertIn("no execution or offline substitution", result.stdout)

    def test_invalid_mode_and_threshold_fail_closed(self):
        for overrides in (
            {"EVAL_MODE": "live"}, {"EVAL_MODE": ""},
            *({"PASS_THRESHOLD": value} for value in ("-1", "101", "1.5", "", "75; echo invalid")),
        ):
            with self.subTest(overrides=overrides):
                result = _run_bash(self.bash(), self.guard, self.default_env() | overrides)
                self.assertEqual(result.returncode, 2, result.stderr)
        for value in ("0", "75", "100", "075"):
            with self.subTest(valid=value):
                result = _run_bash(
                    self.bash(), self.guard, self.default_env() | {"PASS_THRESHOLD": value},
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_both_modes_get_python_hash_locked_wheels_and_dependency_checks_first(self):
        for job, consumer in (
            (self.job, "Score existing recorded skill invocation"),
            (self.skills["jobs"]["runtime-contracts"],
             "Demonstrate offline skill scoring on a synthetic fixture"),
        ):
            steps = {step.get("name"): step for step in job["steps"]}
            setup = next(step for step in job["steps"]
                         if step.get("uses", "").startswith("actions/setup-python@"))
            self.assertEqual(setup["with"]["python-version"], "3.12")
            ordered = [
                "Create a clean evaluation environment",
                "Download hash-verified evaluation wheels",
                "Install evaluation wheels without an index",
                "Check the installed dependency closure",
                "Require real DeepEval and its deterministic contract",
                consumer,
            ]
            names = [step.get("name") for step in job["steps"]]
            self.assertLess(job["steps"].index(setup), names.index(ordered[0]))
            positions = [names.index(name) for name in ordered]
            self.assertEqual(positions, sorted(positions))
            for name in ordered[:-1]:
                self.assertNotIn("if", steps[name])
                self.assertNotIn("continue-on-error", steps[name])
            self.assertIn("-m venv", steps[ordered[0]]["run"])
            self.assertIn("GITHUB_PATH", steps[ordered[0]]["run"])
            download, install = (steps[name]["run"] for name in ordered[1:3])
            for command in (download, install):
                self.assertIn("--require-hashes --only-binary=:all:", command)
                self.assertIn("--requirement eval/deepeval/requirements.lock.txt", command)
                self.assertNotIn("--upgrade", command)
            self.assertIn("--isolated download --index-url https://pypi.org/simple", download)
            self.assertIn("--isolated install --no-index", install)
            self.assertEqual(steps[ordered[3]]["run"], "python -m pip check")
            self.assertEqual(steps[ordered[4]]["run"], "python eval/deepeval/check_environment.py")
            self.assertEqual(job["env"]["DEEPEVAL_TELEMETRY_OPT_OUT"], "1")
            self.assertEqual(job["env"]["EVAL_REQUIRE_DEEPEVAL"], "1")
        names = [step.get("name") for step in self.job["steps"]]
        self.assertLess(names.index("Require real DeepEval and its deterministic contract"),
                        names.index("Stage fixtures without execution"))
        lock = (ROOT / "eval/deepeval/requirements.lock.txt").read_text("utf-8")
        self.assertIn("-r requirements-yaml.lock.txt", lock)
        yaml_lock = (ROOT / "eval/deepeval/requirements-yaml.lock.txt").read_text("utf-8")
        self.assertRegex(yaml_lock, r"(?im)^pyyaml==")
        self.assertIn("deepeval==4.1.8", lock)

    def test_every_referenced_python_file_lock_and_test_selector_exists(self):
        # unittest discover with a deleted -p selector otherwise succeeds with zero tests.
        for workflow in (self.workflow, self.skills):
            for job in workflow["jobs"].values():
                for step in job["steps"]:
                    command = step.get("run", "")
                    for path in re.findall(r"\b(?:eval|scripts)/[\w./-]+\.(?:py|txt|jsonl)\b", command):
                        with self.subTest(path=path):
                            self.assertTrue((ROOT / path).is_file(), path)
                    args = command.split()
                    if "discover" in args and "-s" in args and "-p" in args:
                        directory = ROOT / args[args.index("-s") + 1]
                        pattern = args[args.index("-p") + 1]
                        self.assertTrue(list(directory.glob(pattern)), (directory, pattern))
                    if "-m pytest" in command:
                        for path in args[args.index("pytest") + 1:]:
                            if not path.startswith("-"):
                                self.assertTrue((ROOT / path).is_dir(), path)
        self.assertTrue((ROOT / FIXTURE).is_file())
        self.assertTrue(RUN_EVAL.is_file())

    def test_ordinary_ci_preserves_matrix_unittest_pytest_and_trajectory(self):
        job = self.skills["jobs"]["runtime-contracts"]
        self.assertEqual(job["strategy"]["matrix"]["os"], ["ubuntu-latest", "windows-latest"])
        commands = [step.get("run", "") for step in job["steps"]]
        for directory, selector in (
            ("eval/pipeline/tests", "test_dependency_environment.py"),
            ("eval/pipeline/tests", "test_eval_pipeline_workflow.py"),
            ("eval/pipeline/tests", "test_authorization.py"),
            ("eval/pipeline/trajectory", "test_check_trajectory.py"),
            ("scripts/tests", "test_runtime_contracts.py"),
        ):
            self.assertIn(f"python -m unittest discover -s {directory} -p {selector} -v", commands)
        self.assertIn("python -m pytest -q eval/pipeline/custom-eval/tests eval/deepeval/tests", commands)
        demo = next(step for step in job["steps"]
                    if step.get("name") == "Demonstrate offline skill scoring on a synthetic fixture")
        self.assertNotIn("if", demo)
        self.assertEqual(
            demo["run"],
            f"python {SCORER} {FIXTURE} --score --expect-skill fixture-skill-a "
            "--output eval/pipeline/runs/skill-fixture-summary.json",
        )

    def test_score_uses_literal_arguments_and_propagates_all_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "logs with spaces"
            source.mkdir()
            skills = ["fixture-skill-a", "--output=elsewhere.json", "$(touch injected)", "a b"]
            env = self.default_env() | {"TRACE_PATH": source.name, "EXPECTED_SKILLS": json.dumps(skills)}
            for code in (0, 1, 2):
                captured = []

                def fake_cli(path, *, run_name):
                    self.assertEqual((path, run_name), (SCORER, "__main__"))
                    captured.extend(sys.argv)
                    raise SystemExit(code)

                with self.subTest(code=code), patch("runpy.run_path", side_effect=fake_cli):
                    with self.assertRaises(SystemExit) as result:
                        self.execute_python(self.scoring, root, env)
                    self.assertEqual(result.exception.code, code)
                    self.assertEqual(captured, [
                        SCORER, str(source.resolve()), "--score",
                        *(f"--expect-skill={skill}" for skill in skills),
                        "--output", str(root.resolve() / REPORT),
                    ])
                    self.assertFalse((root / "injected").exists())

    def test_default_dispatch_invokes_the_actual_scoring_entrypoint(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = root / FIXTURE
            fixture.parent.mkdir(parents=True)
            fixture.write_text("", encoding="utf-8")
            captured = []
            with patch("runpy.run_path", side_effect=lambda *a, **k: captured.extend(sys.argv)):
                self.execute_python(self.scoring, root, self.default_env())
            self.assertEqual(captured[0], SCORER)
            self.assertEqual(captured[1], str(fixture.resolve()))
            self.assertIn("--score", captured)
            self.assertIn("--expect-skill=fixture-skill-a", captured)
            self.assertNotIn("--pass-threshold", captured)

    def test_bad_trace_paths_and_expected_skill_inputs_never_reach_cli(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            root.mkdir()
            (root / "valid.jsonl").write_text("", encoding="utf-8")
            outside = Path(temp) / "outside.jsonl"
            outside.write_text("", encoding="utf-8")
            invalid = [
                {"TRACE_PATH": ""},
                {"TRACE_PATH": "../outside.jsonl"},
                {"TRACE_PATH": str(outside.resolve())},
                {"TRACE_PATH": "not-found.jsonl"},
                {"TRACE_PATH": "$(touch injected)"},
                *({"EXPECTED_SKILLS": value} for value in
                  ("not-json", "null", "{}", '"skill"', "[]", '[""]', '["  "]', "[1]")),
            ]
            for overrides in invalid:
                env = self.default_env() | {"TRACE_PATH": "valid.jsonl"} | overrides
                with self.subTest(overrides=overrides), patch("runpy.run_path") as cli:
                    with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as result:
                        self.execute_python(self.scoring, root, env)
                    self.assertEqual(result.exception.code, 2)
                    cli.assert_not_called()
                    self.assertFalse((root / REPORT).exists())
                    self.assertFalse((root / "injected").exists())

    def test_input_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            logs = root / "logs"
            logs.mkdir(parents=True)
            outside = Path(temp) / "outside.jsonl"
            outside.write_text("", encoding="utf-8")
            link = logs / "linked.jsonl"
            try:
                link.symlink_to(outside)
            except OSError:
                self.skipTest("file symlinks unavailable on this host")
            for source in ("logs", "logs/linked.jsonl"):
                with self.subTest(source=source), patch("runpy.run_path") as cli:
                    with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as result:
                        self.execute_python(self.scoring, root, self.default_env() | {"TRACE_PATH": source})
                    self.assertEqual(result.exception.code, 2)
                    cli.assert_not_called()

    def test_existing_output_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "log.jsonl").write_text("", encoding="utf-8")
            report = root / REPORT
            report.parent.mkdir(parents=True)
            report.write_text("existing", encoding="utf-8")
            with patch("runpy.run_path") as cli:
                with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as result:
                    self.execute_python(
                        self.scoring, root, self.default_env() | {"TRACE_PATH": "log.jsonl"},
                    )
                self.assertEqual(result.exception.code, 2)
                cli.assert_not_called()
                self.assertEqual(report.read_text("utf-8"), "existing")

    def test_output_directory_symlink_cannot_escape_owned_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "repo"
            pipeline = root / "eval/pipeline"
            pipeline.mkdir(parents=True)
            outside = Path(temp) / "outside"
            outside.mkdir()
            try:
                (pipeline / "runs").symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("directory symlinks unavailable on this host")
            (root / "log.jsonl").write_text("", encoding="utf-8")
            with patch("runpy.run_path") as cli:
                with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as result:
                    self.execute_python(
                        self.scoring, root, self.default_env() | {"TRACE_PATH": "log.jsonl"},
                    )
                self.assertEqual(result.exception.code, 2)
                cli.assert_not_called()
                self.assertEqual(list(outside.iterdir()), [])

    def test_staging_filter_is_literal_and_threshold_is_not_reinterpreted(self):
        bash = self.bash()
        with tempfile.TemporaryDirectory() as temp:
            marker = Path(temp) / "expanded"
            captured = Path(temp) / "args"
            payload = '$(printf executed > "$INJECTION_MARKER")'
            env = self.default_env() | {
                "EVAL_MODE": "fixture-staging", "TASK_FILTER": payload, "PASS_THRESHOLD": "75",
                "INJECTION_MARKER": _bash_path(bash, marker),
                "CAPTURED_ARGS": _bash_path(bash, captured),
            }
            script = 'bash() { printf "%s\\0" "$@" > "$CAPTURED_ARGS"; }\n' + self.guard + self.staging
            result = _run_bash(bash, script, env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(marker.exists(), "task_filter was evaluated as shell syntax")
            self.assertEqual(captured.read_bytes().decode().rstrip("\0").split("\0"), [
                "eval/pipeline/run-eval.sh", "--suite", "custom-eval",
                "--task-filter", payload, "--pass-threshold", "75", "--dry-run",
            ])

    def test_modes_are_exclusive_and_runner_failure_is_not_swallowed(self):
        for name, mode in (
            ("Score existing recorded skill invocation", "offline-score"),
            ("Stage fixtures without execution", "fixture-staging"),
        ):
            self.assertEqual(self.steps[name]["if"], f"inputs.mode == '{mode}'")
            self.assertNotIn("continue-on-error", self.steps[name])
        result = _run_bash(
            self.bash(), "bash() { return 2; }\n" + self.staging, self.default_env(),
        )
        self.assertEqual(result.returncode, 2)

    def test_artifacts_are_summary_only_bounded_and_uploaded_on_failure(self):
        uploads = [step for step in self.job["steps"]
                   if step.get("uses", "").startswith("actions/upload-artifact@")]
        self.assertEqual(len(uploads), 2)
        for step, mode, path in zip(uploads, ("offline-score", "fixture-staging"),
                                    (REPORT, "eval/pipeline/runs/*/summary.json")):
            self.assertEqual(step["if"], f"always() && inputs.dry_run && inputs.mode == '{mode}'")
            self.assertEqual(step["with"]["path"], path)
            self.assertEqual(step["with"]["if-no-files-found"], "error")
            self.assertEqual(step["with"]["retention-days"], "7")
        self.assertEqual(self.steps["Write summary"]["if"], "always()")

    def test_summary_labels_fixture_scope_errors_staging_and_live_refusal(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            summary = root / "step-summary.md"
            env = self.default_env() | {"GITHUB_STEP_SUMMARY": str(summary)}
            body = self.steps["Write summary"]["run"]
            self.execute_python(body, root, env)
            text = summary.read_text("utf-8")
            self.assertIn("SYNTHETIC fixture demonstration", text)
            self.assertIn("NOT a current-harness benchmark", text)
            self.assertIn("No scoring summary produced", text)
            self.assertIn("Acceptance scoring remains UNVERIFIED", text)
            self.assertIn("NOT successful tool completion", text)
            report = root / REPORT
            report.parent.mkdir(parents=True)
            report.write_text(json.dumps({
                "status": "failed", "measured": 1, "total": 1, "threshold": 1.0,
                "expected_skills": ["untrusted-markdown"], "raw": "never-rendered",
            }), encoding="utf-8")
            summary.unlink()
            self.execute_python(body, root, env | {"TRACE_PATH": "existing-logs"})
            text = summary.read_text("utf-8")
            self.assertIn("provenance is not established", text)
            self.assertIn('"status": "failed"', text)
            self.assertNotIn("untrusted-markdown", text)
            self.assertNotIn("never-rendered", text)
            summary.unlink()
            self.execute_python(body, root, env | {"EVAL_MODE": "fixture-staging"})
            self.assertIn("Fixture preflight/staging only", summary.read_text("utf-8"))
            summary.unlink()
            self.execute_python(body, root, env | {"DRY_RUN": "false"})
            text = summary.read_text("utf-8")
            self.assertIn("Live request refused", text)
            self.assertNotIn('"status":', text)

    def test_runner_rejects_invalid_threshold_before_live_guard_or_cli(self):
        bash = self.bash()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tools, sentinel_path, sentinel = _install_cli_sentinel(bash, root)
            raw_threshold = "75; printf injected"
            result = _run_actual_runner(
                bash, [
                    "--suite", "custom-eval", "--pass-threshold", raw_threshold,
                    "--output-root", _bash_path(bash, root / "runs"),
                ],
                {"PATH": f"{tools}:/usr/bin:/bin:{os.environ.get('PATH', '')}",
                 "COPILOT_SENTINEL": sentinel_path},
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            output = result.stdout + result.stderr
            self.assertIn("pass-threshold must be an integer from 0 through 100", output)
            self.assertNotIn(raw_threshold, output)
            self.assertNotIn("live evaluation is disabled", output)
            self.assertFalse(sentinel.exists(), "invalid threshold reached the CLI")

    def test_non_dry_runner_refuses_live_evaluation_before_invoking_cli(self):
        bash = self.bash()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tools, sentinel_path, sentinel = _install_cli_sentinel(bash, root)
            result = _run_actual_runner(
                bash, [
                    "--suite", "custom-eval", "--pass-threshold", "75",
                    "--output-root", _bash_path(bash, root / "runs"),
                ],
                {"PATH": f"{tools}:/usr/bin:/bin:{os.environ.get('PATH', '')}",
                 "COPILOT_SENTINEL": sentinel_path},
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("live evaluation is disabled", result.stderr)
            self.assertFalse(sentinel.exists(), "live refusal must precede CLI invocation")


if __name__ == "__main__":
    unittest.main()

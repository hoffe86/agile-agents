"""Offline contracts for workflow provisioning, dispatch and DeepEval scoring."""

from contextlib import chdir, redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "eval-pipeline-outcome.yml"
SKILLS_WORKFLOW = ROOT / ".github" / "workflows" / "eval-skills.yml"
FIXTURE = "eval/deepeval/tests/fixtures/skill-scoring-demo.jsonl"
SCORER = "eval/deepeval/report_skill_usage.py"
REPORT = "eval/pipeline/runs/skill-usage-summary.json"


def _copy_scoring_sources(root: Path) -> None:
    """Copy only trusted scorer code and its static fixture into an isolated checkout."""
    for relative in (SCORER, FIXTURE):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    shutil.copytree(
        ROOT / "eval/python", root / "eval/python",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


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

    def default_env(self) -> dict[str, str]:
        inputs = self.workflow["on"]["workflow_dispatch"]["inputs"]
        return {
            key: inputs[expression.removeprefix("${{ inputs.").removesuffix(" }}")]["default"]
            for key, expression in self.job["env"].items()
            if expression.startswith("${{ inputs.")
        }

    def execute_python(self, source: str, root: Path, env: dict[str, str]) -> None:
        # Execute the exact trusted workflow body, never trace contents.
        with chdir(root), patch.dict(os.environ, env), patch.object(sys, "argv", []):
            exec(compile(source, "<workflow-step>", "exec"), {"__name__": "__main__"})

    def test_only_reviewed_dispatch_inputs_are_exposed(self):
        self.assertEqual(set(self.workflow["on"]), {"workflow_dispatch"})
        self.assertEqual(
            set(self.workflow["on"]["workflow_dispatch"]["inputs"]),
            {"trace_path", "expected_skills"},
        )
        self.assertIn("DeepEval", self.workflow["name"])
        self.assertEqual(set(self.default_env()), {"TRACE_PATH", "EXPECTED_SKILLS"})

    def test_default_scores_synthetic_fixture(self):
        inputs = self.workflow["on"]["workflow_dispatch"]["inputs"]
        self.assertEqual(inputs["trace_path"]["default"], FIXTURE)
        self.assertEqual(json.loads(inputs["expected_skills"]["default"]), ["fixture-skill-a"])
        self.assertTrue(all(value["type"] == "string" for value in inputs.values()))
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

    def test_only_active_scoring_entrypoint_remains_and_legacy_ci_references_are_absent(self):
        for path in (
            "eval/pipeline/run_eval.py", "eval/pipeline/run-eval.sh",
            "eval/pipeline/run-eval.ps1", "eval/pipeline/shell_judge.py",
            "eval/pipeline/score-judge.sh", "eval/pipeline/score-judge.ps1",
            "eval/pipeline/custom-eval/prepare_inputs.py", "eval/deepeval/score_workspace.py",
        ):
            with self.subTest(path=path):
                self.assertFalse((ROOT / path).exists(), path)
                self.assertNotIn(path, self.workflow_text)
                self.assertNotIn(path, repr(self.skills))
        for obsolete in (
            "EVAL_MODE", "EVAL_SUITE", "TASK_FILTER", "PASS_THRESHOLD", "DRY_RUN",
            "fixture-staging", "test_authorization.py",
        ):
            with self.subTest(obsolete=obsolete):
                self.assertNotIn(obsolete, self.workflow_text + repr(self.skills))
        step = self.steps["Score existing recorded skill invocation"]
        self.assertNotIn("if", step)
        self.assertNotIn("continue-on-error", step)
        self.assertEqual(step["id"], "scoring")

    def test_both_workflows_get_python_hash_locked_wheels_and_dependency_checks_first(self):
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
                    for path in re.findall(
                        r"\b(?:eval|scripts)/[\w./-]+\.(?:py|ps1|sh|txt|jsonl)\b", command,
                    ):
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
                                self.assertTrue(list((ROOT / path).rglob("test_*.py")), path)
        self.assertTrue((ROOT / FIXTURE).is_file())
        self.assertTrue((ROOT / SCORER).is_file())

    def test_ordinary_ci_preserves_matrix_unittest_pytest_and_trajectory(self):
        job = self.skills["jobs"]["runtime-contracts"]
        self.assertEqual(job["strategy"]["matrix"]["os"], ["ubuntu-latest", "windows-latest"])
        commands = [step.get("run", "") for step in job["steps"]]
        for directory, selector in (
            ("eval/pipeline/tests", "test_dependency_environment.py"),
            ("eval/pipeline/tests", "test_eval_pipeline_workflow.py"),
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

    def test_directory_symlink_escape_and_dangling_input_link_are_rejected(self) -> None:
        for dangling in (False, True):
            with self.subTest(dangling=dangling), tempfile.TemporaryDirectory() as temp:
                root = Path(temp) / "repo"
                logs = root / "logs"
                logs.mkdir(parents=True)
                outside = Path(temp) / "outside"
                if not dangling:
                    outside.mkdir()
                    (outside / "trace.jsonl").write_text("", encoding="utf-8")
                try:
                    (logs / "linked").symlink_to(outside, target_is_directory=True)
                except OSError:
                    self.skipTest("directory symlinks unavailable on this host")
                with patch("runpy.run_path") as cli:
                    with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as result:
                        self.execute_python(
                            self.scoring, root, self.default_env() | {"TRACE_PATH": "logs"},
                        )
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

    def test_artifacts_are_summary_only_bounded_and_uploaded_on_failure(self):
        uploads = [step for step in self.job["steps"]
                   if step.get("uses", "").startswith("actions/upload-artifact@")]
        self.assertEqual(len(uploads), 1)
        step = uploads[0]
        self.assertEqual(step["if"], "always() && steps.scoring.outputs.summary_ready == 'true'")
        self.assertEqual(step["with"]["path"], REPORT)
        self.assertEqual(step["with"]["if-no-files-found"], "error")
        self.assertEqual(step["with"]["retention-days"], "7")
        self.assertEqual(self.steps["Write summary"]["if"], "always()")
        self.assertEqual(
            self.steps["Write summary"]["env"],
            {"SUMMARY_READY": "${{ steps.scoring.outputs.summary_ready }}"},
        )

    def test_summary_labels_fixture_scope_and_errors_without_raw_trace_or_labels(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            summary = root / "step-summary.md"
            env = self.default_env() | {"GITHUB_STEP_SUMMARY": str(summary), "SUMMARY_READY": ""}
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
            self.execute_python(
                body, root, env | {"TRACE_PATH": "existing-logs", "SUMMARY_READY": "true"},
            )
            text = summary.read_text("utf-8")
            self.assertIn("provenance is not established", text)
            self.assertIn('"status": "failed"', text)
            self.assertNotIn("untrusted-markdown", text)
            self.assertNotIn("never-rendered", text)
            summary.unlink()
            # A pre-existing file is not evidence that this job measured anything.
            self.execute_python(body, root, env)
            text = summary.read_text("utf-8")
            self.assertIn("No scoring summary produced", text)
            self.assertNotIn('"status":', text)

    def test_summary_path_resolution_errors_render_failure_without_publishing_stale_scores(self) -> None:
        body = self.steps["Write summary"]["run"]
        for error_type in (ValueError, OSError, RuntimeError):
            for failing_path in ("fixture", "trace"):
                for stale_report in (False, True):
                    with self.subTest(
                        error=error_type.__name__, failing_path=failing_path,
                        stale_report=stale_report,
                    ), tempfile.TemporaryDirectory() as temp:
                        root = Path(temp)
                        summary = root / "step-summary.md"
                        report = root / REPORT
                        stale_contents = json.dumps({
                            "status": "passed", "measured": 1, "total": 1, "threshold": 1.0,
                            "raw": "stale-report-must-not-be-rendered",
                        })
                        if stale_report:
                            report.parent.mkdir(parents=True)
                            report.write_text(stale_contents, encoding="utf-8")
                        env = self.default_env() | {
                            "TRACE_PATH": "existing-logs",
                            "GITHUB_STEP_SUMMARY": str(summary),
                        }
                        resolutions = []
                        if failing_path == "trace":
                            resolutions.append(root / FIXTURE)
                        resolutions.append(error_type("path resolution failed"))
                        # SUMMARY_READY must be absent, even if set by the test runner.
                        with patch.dict(os.environ, {}, clear=True), patch.object(
                            Path, "resolve", autospec=True, side_effect=resolutions,
                        ) as resolve:
                            self.execute_python(body, root, env)
                        expected_paths = [Path(FIXTURE)]
                        if failing_path == "trace":
                            expected_paths.append(Path("existing-logs"))
                        self.assertEqual(
                            [call.args[0] for call in resolve.call_args_list], expected_paths,
                        )
                        text = summary.read_text(encoding="utf-8")
                        self.assertIn("## DeepEval offline scoring", text)
                        self.assertIn(
                            "No scoring summary produced; consult the failed step. No score inferred.",
                            text,
                        )
                        self.assertIn("provenance is not established", text)
                        self.assertIn("Acceptance scoring remains UNVERIFIED", text)
                        self.assertNotIn("SYNTHETIC fixture demonstration", text)
                        self.assertNotIn("```json", text)
                        for field in ("status", "measured", "total", "threshold"):
                            self.assertNotIn(f'"{field}":', text)
                        self.assertNotIn("stale-report-must-not-be-rendered", text)
                        if stale_report:
                            self.assertEqual(report.read_text(encoding="utf-8"), stale_contents)
                        else:
                            self.assertFalse(report.exists())

    def test_embedded_workflow_measures_with_real_deepeval_and_propagates_exit_codes(self) -> None:
        cases = (
            (["fixture-skill-a"], None, 0, "passed", 1.0, 1),
            (["missing-skill"], None, 1, "failed", 0.0, 1),
            (["fixture-skill-a"], "not-json\n", 2, "schema_error", None, 0),
        )
        for expected, contents, code, status, score, measured in cases:
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                _copy_scoring_sources(root)
                if contents is not None:
                    (root / FIXTURE).write_text(contents, encoding="utf-8")
                outputs = root / "step-output"
                result = subprocess.run(
                    [sys.executable, "-c", self.scoring],
                    cwd=root, env=dict(
                        os.environ,
                        **(self.default_env() | {"EXPECTED_SKILLS": json.dumps(expected)}),
                        GITHUB_OUTPUT=str(outputs), DEEPEVAL_TELEMETRY_OPT_OUT="1",
                        DEEPEVAL_DISABLE_PROGRESS_BAR="1", EVAL_REQUIRE_DEEPEVAL="1",
                    ),
                    capture_output=True, text=True, timeout=90,
                )
                self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                report = json.loads((root / REPORT).read_text(encoding="utf-8"))
                self.assertEqual(report["status"], status)
                self.assertEqual(report["measured"], measured)
                self.assertEqual(report["total"], 1)
                self.assertEqual(report["results"][0]["score"], score)
                self.assertEqual(report["metric"], "ToolCorrectnessMetric")
                self.assertEqual(report["deepeval_version"], "4.1.8")
                self.assertEqual(outputs.read_text(encoding="utf-8"), "summary_ready=true\n")

    def test_unsupported_cli_options_are_rejected_not_mapped_to_offline_scoring(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _copy_scoring_sources(root)
            for arguments in (
                ["--mode", "live"], ["--dry-run"], ["--suite", "custom-eval"],
                ["--task-filter", ".*"], ["--pass-threshold", "75"],
            ):
                with self.subTest(arguments=arguments):
                    result = subprocess.run(
                        [sys.executable, SCORER, FIXTURE, "--score",
                         "--expect-skill", "fixture-skill-a", "--output", REPORT, *arguments],
                        cwd=root, capture_output=True, text=True, timeout=30,
                    )
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn("unrecognized arguments", result.stderr)
                    self.assertFalse((root / REPORT).exists())

    def test_validation_failure_cannot_publish_existing_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _copy_scoring_sources(root)
            report = root / REPORT
            report.parent.mkdir(parents=True)
            report.write_text("untrusted existing report", encoding="utf-8")
            outputs = root / "step-output"
            env = self.default_env() | {"GITHUB_OUTPUT": str(outputs)}
            with patch("runpy.run_path") as cli:
                with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as result:
                    self.execute_python(self.scoring, root, env)
                self.assertEqual(result.exception.code, 2)
                cli.assert_not_called()
            self.assertFalse(outputs.exists())
            self.assertEqual(report.read_text(encoding="utf-8"), "untrusted existing report")

    def test_unexpected_scorer_exception_propagates_without_publishing_a_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "log.jsonl").write_text("", encoding="utf-8")
            outputs = root / "step-output"
            env = self.default_env() | {"TRACE_PATH": "log.jsonl", "GITHUB_OUTPUT": str(outputs)}
            with patch("runpy.run_path", side_effect=RuntimeError("scorer failed")):
                with self.assertRaisesRegex(RuntimeError, "scorer failed"):
                    self.execute_python(self.scoring, root, env)
            self.assertFalse(outputs.exists())
            self.assertFalse((root / REPORT).exists())


if __name__ == "__main__":
    unittest.main()

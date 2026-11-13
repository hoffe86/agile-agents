"""Offline contracts for the retained skills workflow."""

from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[3]
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
        # BaseLoader preserves GitHub's `on` key rather than YAML 1.1 boolean True.
        cls.skills = yaml.load(SKILLS_WORKFLOW.read_text("utf-8"), Loader=yaml.BaseLoader)

    def test_native_experiment_is_removed_not_hidden_behind_another_mode(self):
        text = repr(self.skills["jobs"]["runtime-contracts"])
        for forbidden in (
            "native_only", "native-qualification", "native_controller",
            "native_runtime_integration", "native_process_contracts", "--run-native",
            "bwrap", "bubblewrap", "slirp4netns", "apt-get", "download-runtime",
            "-m copilot", "copilot-sdk", "secrets.", "github.token", "GH_TOKEN",
            "GITHUB_TOKEN", "deepeval login", "continue-on-error",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)

    def test_permissions_and_actions_are_least_privilege_and_immutable(self):
        for job in (self.skills["jobs"]["runtime-contracts"],
                    self.skills["jobs"]["skill-quality"]):
            self.assertEqual(self.skills["permissions"], {"contents": "read"})
            self.assertNotIn("permissions", job)
            self.assertNotIn("environment", job)
            for step in job["steps"]:
                if "uses" in step:
                    self.assertRegex(step["uses"], r"^actions/[\w-]+@[a-f0-9]{40}$")
                    if step["uses"].startswith("actions/checkout@"):
                        self.assertEqual(step["with"]["persist-credentials"], "false")

    def test_only_active_scoring_entrypoint_remains_and_legacy_ci_references_are_absent(self):
        for path in (
            "eval/pipeline/run_eval.py", "eval/pipeline/run-eval.sh",
            "eval/pipeline/run-eval.ps1", "eval/pipeline/shell_judge.py",
            "eval/pipeline/score-judge.sh", "eval/pipeline/score-judge.ps1",
            "eval/pipeline/custom-eval/prepare_inputs.py", "eval/deepeval/score_workspace.py",
        ):
            with self.subTest(path=path):
                self.assertFalse((ROOT / path).exists(), path)
                self.assertNotIn(path, repr(self.skills))
        for obsolete in (
            "EVAL_MODE", "EVAL_SUITE", "TASK_FILTER", "PASS_THRESHOLD", "DRY_RUN",
            "fixture-staging", "test_authorization.py",
        ):
            with self.subTest(obsolete=obsolete):
                self.assertNotIn(obsolete, repr(self.skills))

    def test_skills_workflow_gets_python_hash_locked_wheels_and_dependency_checks_first(self):
        job = self.skills["jobs"]["runtime-contracts"]
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
            "Demonstrate offline skill scoring on a synthetic fixture",
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
        for job in self.skills["jobs"].values():
            for step in job["steps"]:
                command = step.get("run", "")
                for path in re.findall(
                    r"\b(?:eval|scripts)/[\w./-]+\.(?:py|ps1|sh|txt|jsonl)\b", command,
                ):
                    with self.subTest(path=path):
                        self.assertTrue((ROOT / path).is_file(), path)
                args = command.split()
                if "discover" in args and "-s" in args and "-p" in args:
                    args = shlex.split(command)
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
            ("eval/pipeline/tests", "test_eval_custom_workflow.py"),
            ("eval/pipeline/trajectory", "test_check_trajectory.py"),
            ("scripts/tests", "'test_*.py'"),
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

    def test_script_regressions_are_unconditional_with_native_prerequisites(self):
        self.assertIn("push", self.skills["on"])
        self.assertIn("pull_request", self.skills["on"])
        job = self.skills["jobs"]["runtime-contracts"]
        self.assertEqual(job["runs-on"], "${{ matrix.os }}")
        self.assertEqual(job["strategy"]["matrix"], {"os": ["ubuntu-latest", "windows-latest"]})
        self.assertNotIn("if", job)
        self.assertNotIn("continue-on-error", job)
        self.assertEqual(job["env"]["RUNTIME_GATE_REQUIRE_RUNNERS"], "1")
        steps = {step.get("name"): step for step in job["steps"]}
        scripts = steps["Offline runtime and instruction regressions"]
        self.assertNotIn("if", scripts)
        self.assertNotIn("continue-on-error", scripts)
        args = shlex.split(scripts["run"])
        selected = {path.name for path in
                    (ROOT / args[args.index("-s") + 1]).glob(args[args.index("-p") + 1])}
        self.assertTrue({
            "test_runtime_contracts.py", "test_gate_commands.py",
        } <= selected, selected)

        powershell = steps["Install the gate's YAML parser"]
        self.assertEqual(powershell["shell"], "pwsh")
        self.assertNotIn("if", powershell)
        self.assertNotIn("continue-on-error", powershell)
        self.assertIn("#requires -Version 7.2", powershell["run"])
        self.assertIn("Install-Module powershell-yaml -RequiredVersion 0.4.12", powershell["run"])
        self.assertIn("Import-Module powershell-yaml -RequiredVersion 0.4.12 -ErrorAction Stop",
                      powershell["run"])
        bash = steps["Check the Bash gate's YAML parser"]
        self.assertEqual(bash["if"], "runner.os == 'Linux'")
        self.assertEqual(bash["shell"], "bash")
        self.assertNotIn("continue-on-error", bash)
        self.assertIn("command -v bash curl", bash["run"])
        self.assertIn("yq --version | grep -E 'mikefarah/yq/.*version v4\\.'", bash["run"])
        for prerequisite in (powershell, bash):
            self.assertLess(job["steps"].index(prerequisite), job["steps"].index(scripts))

    def test_invocation_grading_workflow_is_retired(self):
        self.assertFalse((ROOT / ".github/workflows/eval-pipeline-outcome.yml").exists())

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

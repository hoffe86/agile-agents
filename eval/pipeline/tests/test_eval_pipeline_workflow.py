"""Offline regressions for the manually-dispatched pipeline evaluation workflow."""

import os
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
WORKFLOW = ROOT / ".github" / "workflows" / "eval-pipeline-outcome.yml"
RUN_EVAL = ROOT / "eval" / "pipeline" / "run-eval.sh"
SKILLS_WORKFLOW = ROOT / ".github" / "workflows" / "eval-skills.yml"


def _run_blocks(workflow_text):
    lines = workflow_text.splitlines()
    blocks = []
    index = 0
    while index < len(lines):
        if lines[index] == "        run: |":
            index += 1
            body = []
            while index < len(lines):
                line = lines[index]
                if line and not line.startswith("          "):
                    break
                body.append(line[10:] if line else "")
                index += 1
            blocks.append("\n".join(body))
        else:
            index += 1
    return blocks


def _bash_path(bash, path):
    if os.name != "nt":
        return str(path)
    if "Git" in bash:
        resolved = Path(path).resolve().as_posix()
        return f"/{resolved[0].lower()}{resolved[2:]}"
    result = subprocess.run(
        [bash, "-c", 'wslpath -a "$1"', "--", str(path)],
        check=True,
        capture_output=True,
        text=True,
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
        check=False,
        capture_output=True,
        text=True,
    )


def _install_cli_sentinel(bash, temp_dir):
    tools = temp_dir / "bin"
    tools.mkdir(parents=True)
    sentinel = temp_dir / "copilot-invoked"
    executable = tools / "copilot"
    executable.write_text(
        '#!/usr/bin/env bash\nprintf invoked > "$COPILOT_SENTINEL"\n',
        encoding="utf-8",
        newline="\n",
    )
    executable.chmod(0o755)
    return _bash_path(bash, tools), _bash_path(bash, sentinel), sentinel


def _run_actual_runner(bash, args, env_updates):
    # Python is now a prelaunch prerequisite, not merely an optional diagnostic.
    # Keep these runner tests on their actual interpreter, including Windows venvs.
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
        # BaseLoader preserves GitHub's YAML `on` key (not YAML 1.1 boolean True).
        cls.workflow = yaml.load(cls.workflow_text, Loader=yaml.BaseLoader)
        cls.run_blocks = _run_blocks(cls.workflow_text)
        if len(cls.run_blocks) < 2:
            raise AssertionError("expected harness and summary shell blocks")

    def test_workflow_permissions_and_checkout_do_not_persist_credentials(self):
        self.assertRegex(self.workflow_text, r"(?m)^permissions:\n  contents: read$")
        self.assertRegex(
            self.workflow_text,
            r"(?s)uses: actions/checkout@[0-9a-f]{40} # v4\.3\.1\n"
            r"        with:\n          persist-credentials: false",
        )

    def test_shell_blocks_do_not_interpolate_workflow_inputs(self):
        for block in self.run_blocks:
            self.assertNotIn("${{", block)

    def test_only_reviewed_dispatch_inputs_are_exposed(self):
        declared = set(
            re.findall(
                r"(?m)^      ([a-z_]+):\n        description:",
                self.workflow_text,
            )
        )
        self.assertEqual(
            declared,
            {"suite", "task_filter", "pass_threshold", "dry_run", "native_only"},
        )

    def test_default_remains_offline_and_native_requires_explicit_boolean_opt_in(self):
        self.assertEqual(set(self.workflow["on"]), {"workflow_dispatch"})
        inputs = self.workflow["on"]["workflow_dispatch"]["inputs"]
        self.assertEqual(inputs["dry_run"]["type"], "boolean")
        self.assertEqual(inputs["dry_run"]["default"], "true")
        self.assertEqual(inputs["native_only"]["type"], "boolean")
        self.assertEqual(inputs["native_only"]["default"], "false")
        jobs = self.workflow["jobs"]
        self.assertEqual(
            jobs["pipeline-outcome"]["if"],
            "${{ github.event_name == 'workflow_dispatch' && !inputs.native_only }}",
        )
        self.assertEqual(
            jobs["native-qualification"]["if"],
            "${{ github.event_name == 'workflow_dispatch' && inputs.native_only }}",
        )
        self.assertNotIn("needs", jobs["pipeline-outcome"])
        self.assertNotIn("needs", jobs["native-qualification"])

    def test_native_job_is_bounded_and_does_not_grade_or_inherit_credentials(self):
        job = self.workflow["jobs"]["native-qualification"]
        self.assertEqual(job["runs-on"], "ubuntu-24.04")
        self.assertEqual(job["timeout-minutes"], "15")
        self.assertNotIn("environment", job)
        text = repr(job["steps"]) + repr(job.get("env", {}))
        for forbidden in (
            "secrets.", "github.token", "GH_TOKEN", "GITHUB_TOKEN", "inputs.",
            "run-eval", "summary.json", "GITHUB_STEP_SUMMARY", "upload-artifact@",
            "continue-on-error", "sudo ", "sysctl ", "apparmor_parser", "--version --",
        ):
            self.assertNotIn(forbidden, text)
        steps = {step.get("name"): step for step in job["steps"]}
        native = steps["Execute no-model native boundary checks"]
        self.assertEqual(native["timeout-minutes"], "5")
        self.assertIn("env -i PATH=/usr/bin:/bin", native["run"])
        self.assertIn("COPILOT_SKIP_CLI_DOWNLOAD=1", native["run"])
        self.assertIn("--run-native --runtime-path", native["run"])
        self.assertIn(
            '"$COPILOT_CLI_EXTRACT_DIR/prebuilds/linux-x64/copilot-runtime"',
            native["run"],
        )
        self.assertNotIn("||", native["run"])
        self.assertNotIn("--version", native["run"])
        self.assertEqual(steps["Remove qualification provisioning"]["if"], "always()")
        self.assertIn('"$COPILOT_CLI_EXTRACT_DIR"', steps["Remove qualification provisioning"]["run"])

    def test_native_provisioning_reuses_hash_lock_and_publisher_pin(self):
        job = self.workflow["jobs"]["native-qualification"]
        steps = {step.get("name"): step for step in job["steps"]}
        self.assertIn(
            'COPILOT_CLI_EXTRACT_DIR=$RUNNER_TEMP/native-runtime-1.0.101',
            steps["Set qualification paths"]["run"],
        )
        download = steps["Download hash-verified evaluation wheels"]["run"]
        install = steps["Install evaluation wheels without an index"]["run"]
        for command in (download, install):
            self.assertIn("--require-hashes --only-binary=:all:", command)
            self.assertIn("--requirement eval/deepeval/requirements.lock.txt", command)
            self.assertNotIn("--upgrade", command)
        self.assertIn("--isolated download --index-url https://pypi.org/simple", download)
        self.assertIn("--isolated install --no-index", install)
        self.assertEqual(
            steps["Provision the publisher-pinned runtime"]["run"],
            '"$EVAL_PYTHON" -m copilot download-runtime',
        )
        self.assertIn("-m pip check", steps["Check the installed dependency closure"]["run"])
        self.assertIn(
            "test_native_runtime_integration.py",
            steps["Offline native qualification contracts"]["run"],
        )
        prerequisites = steps["Require native host prerequisites"]["run"]
        self.assertIn("bwrap slirp4netns", prerequisites)
        self.assertIn("bwrap --unshare-user --unshare-net", prerequisites)
        self.assertIn("exit 1", prerequisites)

    def test_manual_workflow_actions_are_immutable_and_checkout_has_no_saved_token(self):
        for job in self.workflow["jobs"].values():
            for step in job["steps"]:
                if "uses" not in step:
                    continue
                self.assertRegex(step["uses"], r"^actions/[\w-]+@[a-f0-9]{40}$")
                if step["uses"].startswith("actions/checkout@"):
                    self.assertEqual(step["with"]["persist-credentials"], "false")

    def test_ordinary_ci_collects_offline_contracts_without_native_execution(self):
        workflow = yaml.load(SKILLS_WORKFLOW.read_text("utf-8"), Loader=yaml.BaseLoader)
        job = workflow["jobs"]["runtime-contracts"]
        matches = [
            step for step in job["steps"]
            if "test_native_runtime_integration.py" in step.get("run", "")
        ]
        self.assertEqual(len(matches), 1)
        self.assertNotIn("if", matches[0])
        self.assertEqual(
            matches[0]["run"],
            "python -m unittest discover -s eval/pipeline/tests "
            "-p test_native_runtime_integration.py -v",
        )
        for step in job["steps"]:
            self.assertNotIn("--run-native", step.get("run", ""))

    def test_missing_host_prerequisite_fails_closed_without_provisioning(self):
        bash = _find_bash()
        if not bash:
            self.skipTest("bash is not installed")
        steps = self.workflow["jobs"]["native-qualification"]["steps"]
        preflight = next(step["run"] for step in steps
                         if step.get("name") == "Require native host prerequisites")
        result = _run_bash(bash, "command() { return 1; }\n" + preflight, {})
        self.assertEqual(result.returncode, 1)
        self.assertIn("native prerequisite missing: bwrap", result.stdout)

    def test_harness_passes_tainted_filter_as_a_literal_argument(self):
        bash = _find_bash()
        if not bash:
            self.skipTest("bash is not installed")

        harness = self.run_blocks[0]
        self.assertIn('bash eval/pipeline/run-eval.sh "${RUN_ARGS[@]}"', harness)
        with tempfile.TemporaryDirectory() as temp_dir:
            marker = Path(temp_dir) / "expanded"
            captured_args = Path(temp_dir) / "args"
            payload = '$(printf executed > "$INJECTION_MARKER")'
            env = {
                "EVAL_SUITE": "custom-eval",
                "TASK_FILTER": payload,
                "PASS_THRESHOLD": "75",
                "DRY_RUN": "true",
                "INJECTION_MARKER": _bash_path(bash, marker),
                "CAPTURED_ARGS": _bash_path(bash, captured_args),
            }
            script = (
                'bash() { printf "%s\\0" "$@" > "$CAPTURED_ARGS"; }\n'
                + harness
            )
            result = _run_bash(bash, script, env)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(marker.exists(), "task_filter was evaluated as shell syntax")
            actual_args = captured_args.read_bytes().decode().rstrip("\0").split("\0")
            self.assertEqual(
                actual_args,
                [
                    "eval/pipeline/run-eval.sh",
                    "--suite",
                    "custom-eval",
                    "--task-filter",
                    payload,
                    "--pass-threshold",
                    "75",
                    "--dry-run",
                ],
            )

    def test_invalid_threshold_is_rejected_before_invoking_runner(self):
        bash = _find_bash()
        if not bash:
            self.skipTest("bash is not installed")

        env = {
            "EVAL_SUITE": "custom-eval",
            "TASK_FILTER": ".*",
            "PASS_THRESHOLD": "75; echo invalid",
            "DRY_RUN": "true",
        }
        script = (
            "bash() { echo runner-invoked >&2; exit 99; }\n"
            + self.run_blocks[0]
        )
        result = _run_bash(bash, script, env)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("runner-invoked", result.stderr)
        self.assertIn("pass_threshold must be an integer", result.stdout)

    def test_runner_rejects_invalid_threshold_before_live_guard_or_cli(self):
        bash = _find_bash()
        if not bash:
            self.skipTest("bash is not installed")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tools, sentinel_path, sentinel = _install_cli_sentinel(bash, root)
            raw_threshold = "75; printf injected"
            env = {
                "PATH": f"{tools}:/usr/bin:/bin:{os.environ.get('PATH', '')}",
                "COPILOT_SENTINEL": sentinel_path,
            }
            result = _run_actual_runner(
                bash,
                [
                    "--suite", "custom-eval",
                    "--pass-threshold", raw_threshold,
                    "--output-root", _bash_path(bash, root / "runs"),
                ],
                env,
            )

            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            output = result.stdout + result.stderr
            self.assertIn("pass-threshold must be an integer from 0 through 100", output)
            self.assertNotIn(raw_threshold, output)
            self.assertNotIn("live evaluation is disabled", output)
            self.assertFalse(sentinel.exists(), "invalid threshold reached the CLI")

    def test_non_dry_runner_refuses_live_evaluation_before_invoking_cli(self):
        bash = _find_bash()
        if not bash:
            self.skipTest("bash is not installed")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tools, sentinel_path, sentinel = _install_cli_sentinel(bash, root)
            result = _run_actual_runner(
                bash,
                [
                    "--suite", "custom-eval",
                    "--pass-threshold", "75",
                    "--output-root", _bash_path(bash, root / "runs"),
                ],
                {
                    "PATH": f"{tools}:/usr/bin:/bin:{os.environ.get('PATH', '')}",
                    "COPILOT_SENTINEL": sentinel_path,
                },
            )

            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("live evaluation is disabled", result.stderr)
            self.assertFalse(sentinel.exists(), "live refusal must precede CLI invocation")


if __name__ == "__main__":
    unittest.main()

"""Offline contracts for the live custom-eval workflow: trust zones, pinning, rendering."""

import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
import yaml


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "eval-custom.yml"
HOSTILE = "```\n[click](https://evil.example) ![x](https://evil.example/p.png) <img src=x> | col"


def _steps(job: dict) -> dict:
    return {step.get("name") or step.get("uses"): step for step in job["steps"]}


class EvalCustomWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        # BaseLoader keeps GitHub's `on` key instead of YAML 1.1 boolean True.
        cls.wf = yaml.load(cls.text, Loader=yaml.BaseLoader)
        cls.jobs = cls.wf["jobs"]

    def run_body(self, job: str, step: str, env: dict) -> str:
        source = _steps(self.jobs[job])[step]["run"]
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp, "summary.md")
            with patch.dict(os.environ, {**env, "GITHUB_STEP_SUMMARY": str(summary)}):
                exec(compile(source, f"{job}:{step}", "exec"), {})
            return summary.read_text(encoding="utf-8")

    def test_manual_dispatch_only_with_safe_defaults(self):
        self.assertEqual(list(self.wf["on"]), ["workflow_dispatch"])
        inputs = self.wf["on"]["workflow_dispatch"]["inputs"]
        self.assertEqual(inputs["judge"]["default"], "none")
        self.assertEqual(inputs["judge"]["options"], ["none", "azure-openai"])
        self.assertNotIn("approver", inputs)
        self.assertNotIn("inputs.approver", self.text)
        self.assertTrue(re.fullmatch(r"task-\d{2}", inputs["task"]["default"]))
        self.assertIn("(( MAX_AI_CREDITS >= 30 && MAX_AI_CREDITS <= 2000 ))",
                      _steps(self.jobs["plan"])["Validate inputs"]["run"])

    def test_least_privilege_and_trust_zones(self):
        self.assertEqual(self.wf["permissions"], {"contents": "read"})
        for name in ("plan", "implement"):
            job = self.jobs[name]
            self.assertEqual(job["permissions"],
                             {"contents": "read", "copilot-requests": "write"})
            self.assertNotIn("azure/login", json.dumps(job))
            self.assertNotIn("EVAL_AZURE", json.dumps(job))
        score = self.jobs["score"]
        self.assertEqual(score["permissions"], {"contents": "read", "id-token": "write"})
        self.assertNotIn("run_custom_eval", json.dumps(score), "the agent never runs where OIDC is")
        self.assertNotIn("GITHUB_TOKEN", json.dumps(score))
        self.assertNotIn("github.token", json.dumps(score))
        login = _steps(score)["azure/login@eec3c95657c1536435858eda1f3ff5437fee8474"]
        login_gate = " ".join(login["if"].split())
        self.assertIn("inputs.judge == 'azure-openai'", login_gate)
        self.assertIn("needs.plan.outputs.status == 'gate_skipped'", login_gate)
        self.assertIn("needs.plan.outputs.status == 'complete'", login_gate)
        self.assertIn("needs.implement.result == 'success'", login_gate)

    def test_simulated_approver_holds_oidc_and_never_the_agent_token(self):
        approve = self.jobs["approve"]
        self.assertEqual(approve["permissions"], {"contents": "read", "id-token": "write"})
        self.assertEqual(approve["needs"], "plan")
        self.assertEqual(approve["if"],
                         "${{ needs.plan.outputs.status == 'awaiting_approval' }}")
        body = json.dumps(approve)
        self.assertNotIn("GITHUB_TOKEN", body)
        self.assertNotIn("github.token", body)
        self.assertNotIn("--unsandboxed", body, "the approver runs no agent")
        self.assertNotIn("setup-dotnet", body)
        decide = _steps(approve)["Simulated plan approval (LLM, eval-only)"]["run"]
        self.assertIn("--phase approve", decide)
        self.assertNotIn("--approver", decide)
        self.assertIn('["approved"] is True else "rejected"', decide)

    def test_copilot_token_is_scoped_to_the_agent_steps(self):
        holders = [(job, step.get("name")) for job, body in self.jobs.items()
                   for step in body["steps"] if "GITHUB_TOKEN" in step.get("env", {})]
        self.assertEqual(holders, [
            ("plan", "Phase 1 - run dev-lead up to the plan gate"),
            ("implement", "Phase 2 - resume the same session with the recorded approval"),
        ])
        self.assertNotIn("GITHUB_TOKEN", self.wf.get("env", {}))
        self.assertNotIn("EVAL_COPILOT_TOKEN", self.text)
        self.assertNotIn("COPILOT_GITHUB_TOKEN", self.text)
        for job, step in holders:
            self.assertNotIn("GITHUB_TOKEN", self.jobs[job].get("env", {}))
            self.assertEqual(_steps(self.jobs[job])[step]["env"]["GITHUB_TOKEN"],
                             "${{ github.token }}")

    def test_plan_gate_requires_the_successful_simulated_decision(self):
        implement = self.jobs["implement"]
        self.assertEqual(implement["needs"], ["plan", "approve"])
        self.assertNotIn("environment", implement)
        gate = " ".join(implement["if"].split())
        self.assertIn("needs.plan.outputs.status == 'awaiting_approval'", gate)
        self.assertIn("needs.approve.result == 'success'", gate)
        self.assertIn("needs.approve.outputs.decision == 'approved'", gate)
        phase2 = _steps(implement)["Phase 2 - resume the same session with the recorded approval"]
        self.assertIn("--phase 2", phase2["run"])
        self.assertNotIn("--approve", phase2["run"])

    def test_simulated_decision_artifact_is_required_and_restored_from_approve(self):
        approval_upload = next(
            step for step in self.jobs["approve"]["steps"]
            if step.get("uses", "").startswith("actions/upload-artifact@"))
        self.assertEqual(approval_upload["with"]["name"], "custom-eval-approval")
        self.assertEqual(approval_upload["with"]["if-no-files-found"], "error")
        downloads = [
            step for step in self.jobs["implement"]["steps"]
            if step.get("uses", "").startswith("actions/download-artifact@")
        ]
        self.assertEqual([step["with"]["name"] for step in downloads],
                         ["custom-eval-plan", "custom-eval-approval"])
        self.assertNotIn("if", downloads[1])
        score_downloads = [
            step for step in self.jobs["score"]["steps"]
            if step.get("uses", "").startswith("actions/download-artifact@")
        ]
        self.assertEqual(score_downloads[-1]["with"]["name"], "custom-eval-approval")
        self.assertEqual(score_downloads[-1]["if"], "${{ needs.approve.result == 'success' }}")

    def test_approval_summary_renders_judge_reasons_inert(self):
        with tempfile.TemporaryDirectory() as run_dir:
            Path(run_dir, "plan-approval.json").write_text(json.dumps({
                "approver": "llm-simulated", "approved": False,
                "judgement": {"criteria": [{"id": 1, "status": "FAIL", "reason": HOSTILE}]},
            }), encoding="utf-8")
            out = self.run_body("approve", "Write summary", {"RUN_DIR": run_dir})
        self.assertIn("(llm-simulated, eval-only): rejected", out)
        self.assertNotIn("](https://", out)
        self.assertNotIn("<img", out)
        row = [line for line in out.splitlines() if line.startswith("| 1 |")][0]
        self.assertEqual(len(re.findall(r"(?<!\\)\|", row)), 4, row)

    def test_actions_are_pinned_and_checkouts_drop_credentials(self):
        for job in self.jobs.values():
            for step in job["steps"]:
                if "uses" in step:
                    self.assertRegex(step["uses"], r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$")
                if step.get("uses", "").startswith("actions/checkout@"):
                    self.assertEqual(step["with"]["persist-credentials"], "false")

    def test_no_input_is_interpolated_into_a_script(self):
        for job in self.jobs.values():
            for step in job["steps"]:
                self.assertNotRegex(step.get("run", ""), r"\$\{\{\s*(inputs|github\.event)\.")

    def test_run_artifacts_keep_hidden_dirs_and_drop_the_session(self):
        names = {}
        for job_name in ("plan", "implement"):
            uploads = [s for s in self.jobs[job_name]["steps"]
                       if s.get("uses", "").startswith("actions/upload-artifact@")]
            self.assertEqual(len(uploads), 1)
            self.assertEqual(uploads[0]["with"]["include-hidden-files"], "true")
            names[job_name] = uploads[0]["with"]["name"]
        steps = [s.get("name") for s in self.jobs["implement"]["steps"]]
        self.assertLess(steps.index("Drop the Copilot session before publishing the run"),
                        len(steps) - 1)
        score = json.dumps(self.jobs["score"])
        self.assertIn(names["plan"], score)
        self.assertIn(names["implement"], score)

    def test_phase1_status_output_is_allowlisted(self):
        run = _steps(self.jobs["plan"])["Phase 1 - run dev-lead up to the plan gate"]["run"]
        self.assertIn("awaiting_approval|blocked_approval|gate_skipped|complete) ;; *) status=invalid", run)

    def test_unverified_approval_is_reported_as_blocked(self):
        with tempfile.TemporaryDirectory() as run_dir:
            Path(run_dir, "state.json").write_text(json.dumps({
                "status": "blocked_approval", "plan_message": "No verified approval request",
            }), encoding="utf-8")
            out = self.run_body("plan", "Show the plan to the approver", {"RUN_DIR": run_dir})
        self.assertIn("phase 1: blocked_approval", out)
        self.assertIn("approver and phase 2 will not run", out)

    def test_plan_summary_renders_agent_text_inert(self):
        with tempfile.TemporaryDirectory() as run_dir:
            Path(run_dir, "state.json").write_text(json.dumps({
                "status": "awaiting_approval", "task": HOSTILE, "plan_message": HOSTILE + "\n````",
            }), encoding="utf-8")
            out = self.run_body("plan", "Show the plan to the approver", {"RUN_DIR": run_dir})
        self.assertIn("phase 1: awaiting_approval", out)
        self.assertIn("simulated approver (llm, eval-only)", out)
        self.assertNotIn("https://evil", out.split("`````text", 1)[0])
        self.assertIn("`````text\n" + HOSTILE + "\n````\n`````", out)

    def test_plan_summary_rejects_unknown_status(self):
        with tempfile.TemporaryDirectory() as run_dir:
            Path(run_dir, "state.json").write_text(json.dumps({"status": HOSTILE}), "utf-8")
            out = self.run_body("plan", "Show the plan to the approver", {"RUN_DIR": run_dir})
        self.assertIn("phase 1: invalid state", out)
        self.assertNotIn("evil", out.split("plan message", 1)[0])

    def test_score_summary_escapes_trace_derived_cells(self):
        report = {"status": "failed", "judge": "none", "results": [{
            "plan_gate": {"name": "plan_gate", "score": 1.0, "passed": True, "reason": "ok"},
            "trajectory": [{"name": "skills:coding", "score": 0.0, "passed": False,
                            "reason": HOSTILE}],
            "acceptance": {"verdict": "UNVERIFIED"}, "errors": [HOSTILE],
            "checks": [{"criterion": 1, "command": HOSTILE, "status": "failed",
                        "reason": HOSTILE}],
        }]}
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "custom-eval-summary.json").write_text(json.dumps(report), "utf-8")
            out = self.run_body("score", "Write summary", {"RUNNER_TEMP": tmp, "JUDGE": "none"})
        self.assertIn("| skills:coding | 0.0 | False |", out)
        self.assertIn("| command c1 | - | failed |", out)
        self.assertNotIn("](https://", out)
        self.assertNotIn("<img", out)
        for line in out.splitlines():
            if line.startswith(("| skills:coding", "| error", "| command")):
                self.assertEqual(len(re.findall(r"(?<!\\)\|", line)), 5, line)

    def test_agent_jobs_install_the_toolchain_the_checks_need(self):
        for name in ("plan", "implement"):
            dotnet = [s for s in self.jobs[name]["steps"]
                      if s.get("uses", "").startswith("actions/setup-dotnet@")]
            self.assertEqual(len(dotnet), 1, name)
            self.assertEqual(dotnet[0]["with"]["dotnet-version"], "10.0.x")
            lint = [s for s in self.jobs[name]["steps"] if s.get("name") == "Install actionlint"]
            self.assertEqual(len(lint), 1, name)
            self.assertIn("sha256sum --check --strict", lint[0]["run"])
            self.assertIn('>> "$GITHUB_PATH"', lint[0]["run"])
        self.assertRegex(self.wf["env"]["ACTIONLINT_VERSION"], r"^\d+\.\d+\.\d+$")
        self.assertRegex(self.wf["env"]["ACTIONLINT_SHA256"], r"^[0-9a-f]{64}$")
        self.assertNotIn("setup-dotnet", json.dumps(self.jobs["score"]),
                         "the score job never runs agent code")
        self.assertNotIn("actionlint", json.dumps(self.jobs["score"]))

    def test_python_task_tools_are_pinned_and_only_in_agent_jobs(self):
        body = None
        for name, phase in (
            ("plan", "Phase 1 - run dev-lead up to the plan gate"),
            ("implement", "Phase 2 - resume the same session with the recorded approval"),
        ):
            steps = self.jobs[name]["steps"]
            names = [step.get("name") for step in steps]
            tool_step = _steps(self.jobs[name])["Install task 02 Python tools"]
            self.assertLess(names.index("Install the pinned evaluation lock and Copilot CLI"),
                            names.index("Install task 02 Python tools"))
            self.assertLess(names.index("Install task 02 Python tools"), names.index(phase))
            self.assertNotIn("GITHUB_TOKEN", tool_step.get("env", {}))
            run = tool_step["run"]
            self.assertIn('[[ "$TASK" == task-02 || "$TASK" == task-02-* ]]', run)
            self.assertIn("--require-hashes --only-binary=:all:", run)
            self.assertIn("eval/pipeline/custom-eval/requirements-task02.lock.txt", run)
            self.assertIn("python -m pip check", run)
            if body is not None:
                self.assertEqual(body, run)
            body = run
        for name in ("approve", "score"):
            self.assertNotIn("requirements-task02.lock.txt", json.dumps(self.jobs[name]))

        lock = (ROOT / "eval/pipeline/custom-eval/requirements-task02.lock.txt").read_text(
            encoding="utf-8")
        self.assertIn("-r ../../deepeval/requirements.lock.txt", lock)
        for name in ("fastapi", "librt", "mypy", "mypy-extensions", "pathspec",
                     "ruff", "starlette"):
            self.assertRegex(lock, rf"(?m)^{name}==\S+ --hash=sha256:[0-9a-f]{{64}}")
        self.assertNotRegex(lock, r"(?m)^[^#\s-].* --(?!hash=)")

    def test_python_tool_versions_satisfy_the_task_baseline(self):
        versions = {}
        for path in (ROOT / "eval/deepeval/requirements.lock.txt",
                     ROOT / "eval/pipeline/custom-eval/requirements-task02.lock.txt"):
            for name, version in re.findall(
                    r"(?m)^([a-zA-Z0-9_.-]+)==([^\s;]+)", path.read_text("utf-8")):
                versions[canonicalize_name(name)] = version
        baseline = ROOT / "eval/pipeline/custom-eval/tasks/task-02-python-di-refactor/baseline"
        for path in (baseline / "requirements.txt", baseline / "requirements-dev.txt"):
            for line in path.read_text("utf-8").splitlines():
                if not line or line.startswith(("#", "-r ")):
                    continue
                requirement = Requirement(line)
                name = canonicalize_name(requirement.name)
                with self.subTest(requirement=line):
                    self.assertIn(name, versions)
                    self.assertIn(versions[name], requirement.specifier)


if __name__ == "__main__":
    unittest.main()

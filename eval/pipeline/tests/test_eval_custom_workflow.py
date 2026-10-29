"""Offline contracts for the live custom-eval workflow: trust zones, pinning, rendering."""

import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

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
        self.assertTrue(re.fullmatch(r"task-\d{2}", inputs["task"]["default"]))
        self.assertIn("(( MAX_AI_CREDITS >= 30 && MAX_AI_CREDITS <= 2000 ))",
                      _steps(self.jobs["plan"])["Validate inputs"]["run"])

    def test_least_privilege_and_trust_zones(self):
        self.assertEqual(self.wf["permissions"], {"contents": "read"})
        for name in ("plan", "implement"):
            job = self.jobs[name]
            self.assertNotIn("permissions", job, f"{name} must inherit read-only permissions")
            self.assertNotIn("azure/login", json.dumps(job))
            self.assertNotIn("EVAL_AZURE", json.dumps(job))
        score = self.jobs["score"]
        self.assertEqual(score["permissions"], {"contents": "read", "id-token": "write"})
        self.assertNotIn("run_custom_eval", json.dumps(score), "the agent never runs where OIDC is")
        self.assertNotIn("EVAL_COPILOT_TOKEN", json.dumps(score))
        login = _steps(score)["azure/login@eec3c95657c1536435858eda1f3ff5437fee8474"]
        self.assertEqual(login["if"], "${{ inputs.judge == 'azure-openai' }}")

    def test_copilot_token_is_scoped_to_the_agent_steps(self):
        holders = [(job, step.get("name")) for job, body in self.jobs.items()
                   for step in body["steps"] if "EVAL_COPILOT_TOKEN" in json.dumps(step)]
        self.assertEqual(holders, [
            ("plan", "Phase 1 - run dev-lead up to the plan gate"),
            ("implement", "Phase 2 - resume the same session with the recorded approval"),
        ])

    def test_human_gate_is_an_environment_on_the_resume_job(self):
        implement = self.jobs["implement"]
        self.assertEqual(implement["needs"], "plan")
        self.assertEqual(implement["environment"], "eval-approval")
        self.assertEqual(implement["if"], "${{ needs.plan.outputs.status == 'awaiting_approval' }}")
        phase2 = _steps(implement)["Phase 2 - resume the same session with the recorded approval"]
        self.assertIn("--phase 2", phase2["run"])
        self.assertIn("--approve", phase2["run"])

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
        self.assertIn("awaiting_approval|gate_skipped|complete) ;; *) status=invalid", run)

    def test_plan_summary_renders_agent_text_inert(self):
        with tempfile.TemporaryDirectory() as run_dir:
            Path(run_dir, "state.json").write_text(json.dumps({
                "status": "awaiting_approval", "task": HOSTILE, "plan_message": HOSTILE + "\n````",
            }), encoding="utf-8")
            out = self.run_body("plan", "Show the plan to the approver", {"RUN_DIR": run_dir})
        self.assertIn("phase 1: awaiting_approval", out)
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
        }]}
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "custom-eval-summary.json").write_text(json.dumps(report), "utf-8")
            out = self.run_body("score", "Write summary", {"RUNNER_TEMP": tmp, "JUDGE": "none"})
        self.assertIn("| skills:coding | 0.0 | False |", out)
        self.assertNotIn("](https://", out)
        self.assertNotIn("<img", out)
        for line in out.splitlines():
            if line.startswith("| skills:coding") or line.startswith("| error"):
                self.assertEqual(len(re.findall(r"(?<!\\)\|", line)), 5, line)


if __name__ == "__main__":
    unittest.main()

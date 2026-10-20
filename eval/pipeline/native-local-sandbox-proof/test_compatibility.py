"""Offline test doubles validate proof logic, not native callbacks."""

import ast
from pathlib import Path
import tempfile
import unittest

import compatibility as proof


class CompatibilityTests(unittest.TestCase):
    def test_no_send_or_private_dispatch(self):
        tree = ast.parse(Path(proof.__file__).read_text())
        calls = [n.func.attr for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
        self.assertFalse(set(calls) & {"send", "send_and_wait", "start_agent", "approve_all"})
        self.assertFalse(any(name.startswith("_handle_") for name in calls))

    def test_callback_absence_does_not_prove_denial(self):
        with tempfile.TemporaryDirectory() as temp:
            row = proof.mutation_observation(Path(temp) / "absent", [], [], {})
            self.assertFalse(row["controller_denial_proved"])

    def test_callback_plus_absence_proves_observed_denial(self):
        with tempfile.TemporaryDirectory() as temp:
            row = proof.mutation_observation(Path(temp) / "absent", [{}], [], {})
            self.assertTrue(row["controller_denial_proved"])

    def test_mutation_defeats_callback_denial(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "present"
            path.touch()
            row = proof.mutation_observation(path, [{}], [{}], {})
            self.assertFalse(row["controller_denial_proved"])

    def test_agent_path_and_body_are_independent_evidence(self):
        source = proof.PLUGIN / "agents/dev-lead.agent.md"
        body = source.read_text(encoding="utf-8").split("---", 2)[2].strip()
        row = proof.agent_evidence({"name": "dev-lead", "path": str(source),
                                    "prompt": body}, proof.PLUGIN)
        self.assertTrue(row["path_matches"])
        self.assertTrue(row["prompt_matches"])
        row = proof.agent_evidence({"name": "dev-lead", "path": "/wrong",
                                    "prompt": "wrong"}, proof.PLUGIN)
        self.assertFalse(row["path_matches"])
        self.assertFalse(row["prompt_matches"])

    def result(self):
        return {"textResultForLlm": 'CREDENTIAL_PROBE={"masked_is_original":false}\n',
                "contents": [{"type": "shell_exit", "exitCode": 0}],
                "toolTelemetry": {"properties": {"sandboxApplied": True,
                                                 "sandboxOptOutRequested": False}}}

    def test_unique_completed_sandboxed_result(self):
        self.assertEqual(proof.parse_credential_result(self.result()),
                         {"masked_is_original": False})

    def test_duplicate_result_rejected(self):
        result = self.result()
        result["textResultForLlm"] *= 2
        with self.assertRaises(AssertionError):
            proof.parse_credential_result(result)

    def test_unsandboxed_result_rejected(self):
        result = self.result()
        result["toolTelemetry"] = {}
        with self.assertRaises(AssertionError):
            proof.parse_credential_result(result)

    def test_failed_shell_rejected_even_with_outer_success(self):
        result = self.result()
        result["resultType"] = "success"
        result["contents"][0]["exitCode"] = 1
        with self.assertRaises(AssertionError):
            proof.parse_credential_result(result)


if __name__ == "__main__":
    unittest.main()

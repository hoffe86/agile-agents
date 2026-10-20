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
            row = proof.mutation_observation(Path(temp) / "absent", [{}], [],
                                             {"resultType": "denied"})
            self.assertTrue(row["controller_denial_proved"])

    def test_sandbox_failure_does_not_prove_controller_denial(self):
        with tempfile.TemporaryDirectory() as temp:
            row = proof.mutation_observation(Path(temp) / "absent", [], [{}],
                                             {"resultType": "failure", "error": "denied path"})
            self.assertFalse(row["controller_denial_proved"])

    def test_mutation_defeats_callback_denial(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "present"
            path.touch()
            row = proof.mutation_observation(path, [{}], [{}], {})
            self.assertFalse(row["controller_denial_proved"])

    def test_native_permission_rejection_is_observed_without_changing_raw_evidence(self):
        # CLI 1.0.98 / SDK 1.0.22 run 39424597215: reject and hook-exception.
        result = {
            "textResultForLlm": "The user rejected this tool call.",
            "resultType": "rejected",
            "sessionLog": "The user rejected this tool call.",
            "error": "The user rejected this tool call.",
            "toolTelemetry": {"properties": {"shell_error_category": "permission_denied"}},
        }
        with tempfile.TemporaryDirectory() as temp:
            for hooks in ([], [{}]):
                with self.subTest(hooks=hooks):
                    row = proof.mutation_observation(Path(temp) / "absent", [{}], hooks, result)
                    self.assertTrue(row["controller_denial_proved"])
                    self.assertFalse(row["host_mutated"])
                    self.assertEqual(row["permission_callback_count"], 1)
                    self.assertEqual(row["pre_tool_callback_count"], len(hooks))
                    self.assertIs(row["native_result"], result)

    def test_native_hook_denial_needs_no_permission_callback(self):
        result = {
            "resultType": "denied",
            "textResultForLlm": "Denied by preToolUse hook: No reason provided",
            "error": "Denied by preToolUse hook: No reason provided",
            "toolTelemetry": {},
        }
        with tempfile.TemporaryDirectory() as temp:
            row = proof.mutation_observation(Path(temp) / "absent", [], [{}], result)
            self.assertTrue(row["controller_denial_proved"])

    def test_explicit_refusal_without_callbacks_is_not_controller_denial(self):
        with tempfile.TemporaryDirectory() as temp:
            for kind in ("denied", "rejected"):
                with self.subTest(kind=kind):
                    row = proof.mutation_observation(
                        Path(temp) / "absent", [], [], {"resultType": kind})
                    self.assertFalse(row["controller_denial_proved"])

    def test_host_mutation_overrules_explicit_native_refusal(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "present"
            path.touch()
            for kind in ("denied", "rejected"):
                with self.subTest(kind=kind):
                    row = proof.mutation_observation(path, [{}], [{}], {"resultType": kind})
                    self.assertTrue(row["host_mutated"])
                    self.assertFalse(row["controller_denial_proved"])

    def test_non_refusal_result_types_and_prose_do_not_prove_denial(self):
        results = [
            {},
            {"textResultForLlm": "The user rejected this tool call."},
            {"error": "Permission denied"},
            {"toolTelemetry": {"properties": {"shell_error_category": "permission_denied"}}},
            {"resultType": None},
            {"resultType": ["rejected"]},
            {"resultType": "unknown"},
            {"resultType": "not rejected"},
            {"resultType": "not denied"},
            {"resultType": "success", "textResultForLlm": "not rejected"},
            {"resultType": "success", "error": "The user rejected this tool call.",
             "contents": [{"type": "shell_exit", "exitCode": 0}]},
            {"resultType": "failure", "error": "Permission denied"},
            {"rpc_error": "The user rejected this tool call."},
        ]
        with tempfile.TemporaryDirectory() as temp:
            for result in results:
                with self.subTest(result=result):
                    row = proof.mutation_observation(Path(temp) / "absent", [{}], [{}], result)
                    self.assertFalse(row["controller_denial_proved"])

    def test_shell_completion_contradicts_controller_refusal(self):
        with tempfile.TemporaryDirectory() as temp:
            for kind in ("denied", "rejected"):
                for exit_code in (0, 1, None):
                    with self.subTest(kind=kind, exit_code=exit_code):
                        result = {"resultType": kind, "contents": [
                            {"type": "shell_exit", "exitCode": exit_code}]}
                        row = proof.mutation_observation(
                            Path(temp) / "absent", [{}], [{}], result)
                        self.assertFalse(row["controller_denial_proved"])

    def test_rpc_error_contradicts_controller_refusal(self):
        with tempfile.TemporaryDirectory() as temp:
            for kind in ("denied", "rejected"):
                with self.subTest(kind=kind):
                    result = {"resultType": kind, "rpc_error": "TimeoutError"}
                    row = proof.mutation_observation(Path(temp) / "absent", [{}], [{}], result)
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

    def test_namespaced_native_agent_maps_to_exact_repository_source(self):
        source = proof.PLUGIN / "agents/dev-lead.agent.md"
        body = source.read_text(encoding="utf-8").split("---", 2)[2].strip()
        row = proof.agent_evidence({"name": "agile-agents-core:dev-lead",
                                    "path": str(source), "prompt": body}, proof.PLUGIN)
        self.assertTrue(row["path_matches"])
        self.assertTrue(row["prompt_matches"])
        self.assertEqual(proof.local_agent_name("other:dev-lead"), "other:dev-lead")

    def test_input_callbacks_are_not_shadowed_by_deny_hook(self):
        tree = ast.parse(Path(proof.__file__).read_text())
        hook = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "hook")
        # Bind just the proof callback, not fabricated native callback inputs.
        namespace = {"row": {"pre_tool_hooks": []}, "mode": "hook-deny"}
        exec(compile(ast.Module(body=[hook], type_ignores=[]), "<proof-hook>", "exec"), namespace)
        self.assertIsNone(namespace["hook"]({"toolName": "ask_user"}, {}))
        self.assertIsNone(namespace["hook"]({"toolName": "exit_plan_mode"}, {}))
        self.assertEqual(namespace["hook"]({"toolName": "bash"}, {}), {"permissionDecision": "deny"})

    def test_hook_exception_is_not_misreported_as_explicit_denial(self):
        tree = ast.parse(Path(proof.__file__).read_text())
        hook = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "hook")
        namespace = {"row": {"pre_tool_hooks": []}, "mode": "hook-exception"}
        exec(compile(ast.Module(body=[hook], type_ignores=[]), "<proof-hook>", "exec"), namespace)
        with self.assertRaisesRegex(ValueError, "SYNTHETIC"):
            namespace["hook"]({"toolName": "bash"}, {})

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

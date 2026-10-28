"""Offline entrypoint/timeout contracts, NOT evidence of native enforcement."""
from __future__ import annotations

import ast
from contextlib import redirect_stdout
import inspect
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import native_runtime_integration as native


def completion_event(call_id=native.PROTECTED_READ_CALL_ID, **data):
    return {
        "id": "00000000-0000-0000-0000-000000000001",
        "timestamp": "2026-01-01T00:00:00Z", "type": "tool.execution_complete",
        "data": {"toolCallId": call_id, "success": False, **data},
    }


class NativeActivationTests(unittest.TestCase):
    """Evaluate creation arguments against the pinned SDK, without running a coroutine.

    AST inspection keeps these contracts usable on hosts that cannot create an
    event loop. It does not simulate native discovery or claim runtime enforcement.
    """

    @classmethod
    def setUpClass(cls):
        from copilot import CopilotClient
        from copilot.rpc import SkillList

        if native.metadata.version("github-copilot-sdk") != native.SDK_VERSION:
            raise AssertionError("activation contracts require the pinned SDK")
        cls.skill_list = SkillList
        cls.tree = ast.parse(inspect.getsource(native.native_checks))
        cls.calls = sorted(
            (node for node in ast.walk(cls.tree) if isinstance(node, ast.Call)),
            key=lambda node: node.lineno,
        )
        # Evaluate only the real create_session call's arguments. No client is
        # constructed and no SDK method, coroutine, process or socket is invoked.
        imports = [node for node in cls.tree.body[0].body
                   if isinstance(node, ast.ImportFrom) and node.module.startswith("copilot")]
        namespace = dict(vars(native))
        exec(compile(ast.Module(body=imports, type_ignores=[]), native.__file__, "exec"),
             namespace)
        creation = next(node for node in cls.calls
                        if ast.unparse(node.func) == "client.create_session")
        capture = Mock()
        namespace.update(
            client=SimpleNamespace(create_session=capture),
            session_id="synthetic-session", workspace=Path("/synthetic/workspace"),
            root=Path("/synthetic"), permission=Mock(), pre_tool=Mock(),
            exit_plan=Mock(), on_event=Mock(),
        )
        eval(compile(ast.Expression(creation), native.__file__, "eval"), namespace)
        cls.options = capture.call_args.kwargs
        inspect.signature(CopilotClient.create_session).bind(None, **cls.options)
        cls.sdk_namespace = namespace

    def test_creation_uses_only_native_allowlisted_tools_and_no_ambient_sources(self):
        from copilot import BUILTIN_TOOLS_ISOLATED

        options = self.options
        self.assertEqual(options["available_tools"].to_list(),
                         [f"builtin:{name}" for name in [*BUILTIN_TOOLS_ISOLATED, "view"]])
        self.assertNotIn("tools", options)
        self.assertNotIn("skill_provider", options)
        self.assertFalse(options["enable_config_discovery"])
        self.assertEqual(options["mcp_servers"], {})
        self.assertEqual(options["disabled_mcp_servers"], ["*"])
        for key in ("plugin_directories", "agent_directories",
                    "instruction_directories", "hook_directories"):
            self.assertEqual(options[key], [])
        permissions = options["managed_settings"].permissions
        self.assertEqual(permissions.disable_bypass_permissions_mode, "disable")
        self.assertTrue(permissions.disable_assisted_permissions_mode)
        self.assertEqual(permissions.limit_to, [])
        self.assertIs(options["on_exit_plan_mode_request"], self.sdk_namespace["exit_plan"])

    def test_registered_user_input_callback_never_accepts_supplied_approval(self):
        callback = self.options["on_user_input_request"]
        self.assertIs(callback, native.refuse_user_input)
        for request in (
            {}, None,
            {"question": "Approve execution?", "choices": ["Approve", "exit_only"],
             "allowFreeform": False},
            {"answer": "approved", "approved": True, "selectedAction": "autopilot"},
        ):
            with self.subTest(request=request):
                self.assertEqual(callback(request, {"session_id": "untrusted"}), {
                    "answer": "REFUSE: native_check_refused", "wasFreeform": True,
                })

    def test_creation_points_to_one_existing_direct_skill_bundle(self):
        expected = (Path(native.__file__).resolve().parents[3] / "plugins"
                    / "agile-agents-core" / "skills" / "trade-off-reporting")
        self.assertTrue(self.options["enable_skills"])
        self.assertEqual(self.options["skill_directories"], [str(expected)])
        self.assertTrue((expected / "SKILL.md").is_file())
        self.assertFalse((expected / "plugin.json").exists())

    def test_plan_is_set_and_verified_before_current_tool_initialization(self):
        from copilot.rpc import ModeSetRequest
        from copilot.session_events import SessionMode

        def first(name):
            return next(node for node in self.calls if ast.unparse(node.func) == name)

        transition = first("session.rpc.mode.set")
        request = eval(compile(ast.Expression(transition.args[0]), native.__file__, "eval"),
                       {"ModeSetRequest": ModeSetRequest, "SessionMode": SessionMode})
        self.assertEqual(request.mode, SessionMode.PLAN)
        verified = next(node for node in self.calls
                        if ast.unparse(node.func) == "require"
                        and ast.literal_eval(node.args[1]) == "native_plan_mode_required")
        self.assertIn("session.rpc.mode.get()", ast.unparse(verified.args[0]))
        self.assertIn("== SessionMode.PLAN", ast.unparse(verified.args[0]))
        self.assertLess(transition.lineno, verified.lineno)
        self.assertLess(verified.lineno, first("session.rpc.skills.ensure_loaded").lineno)
        self.assertLess(first("session.rpc.skills.ensure_loaded").lineno,
                        first("session.rpc.tools.initialize_and_validate").lineno)
        self.assertLess(first("session.rpc.tools.initialize_and_validate").lineno,
                        first("session.rpc.tools.get_current_metadata").lineno)
        self.assertLess(first("session.rpc.skills.list").lineno,
                        first("require_trusted_skill").lineno)
        self.assertEqual(ast.unparse(first("require_trusted_skill").args[0]), "skills.skills")

    def discovered_skill(self, **overrides):
        values = {
            "name": "trade-off-reporting", "description": "Trusted repo skill",
            "enabled": True, "source": "project", "userInvocable": True,
            "path": str(native.TRUSTED_SKILL_DIRECTORY / "SKILL.md"),
        }
        return self.skill_list.from_dict({"skills": [{**values, **overrides}]}).skills[0]

    def test_native_discovery_requires_enabled_skill_at_exact_trusted_path(self):
        native.require_trusted_skill([self.discovered_skill()])
        for overrides in (
            {"enabled": False}, {"name": "other-skill"}, {"path": None},
            {"path": str(Path("/ambient/trade-off-reporting/SKILL.md"))},
            {"pluginName": "ambient-plugin"},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex(native.CheckFailure, "trusted_skill_not_discovered"):
                    native.require_trusted_skill([self.discovered_skill(**overrides)])

    def test_empty_or_extra_native_skill_inventory_fails_closed(self):
        for skills in ([], [self.discovered_skill(), self.discovered_skill(name="extra")]):
            with self.subTest(count=len(skills)):
                with self.assertRaisesRegex(native.CheckFailure, "unexpected_skill_inventory"):
                    native.require_trusted_skill(skills)

    def test_native_reads_use_distinct_fixed_call_ids_in_pinned_wire_requests(self):
        requests = [node for node in self.calls
                    if ast.unparse(node.func) == "ToolsExecuteRequest"
                    and any(key.arg == "name" and ast.literal_eval(key.value) == "view"
                            for key in node.keywords)]
        namespace = {**self.sdk_namespace, "readable_path": Path("/synthetic/readable"),
                     "protected": Path("/synthetic/protected")}
        wire = [eval(compile(ast.Expression(node), native.__file__, "eval"),
                     namespace).to_dict() for node in requests]
        self.assertEqual([item["toolCallId"] for item in wire],
                         ["native-positive-read", "native-protected-read"])
        self.assertNotEqual(native.POSITIVE_READ_CALL_ID, native.PROTECTED_READ_CALL_ID)

    def test_actual_sdk_client_environment_excludes_parent_credentials_and_canary(self):
        creation = next(node for node in self.calls if ast.unparse(node.func) == "CopilotClient")
        capture = Mock()
        root = Path("/synthetic")
        namespace = {**self.sdk_namespace, "CopilotClient": capture, "root": root,
                     "runtime": Path("/synthetic/runtime"), "workspace": root / "workspace"}
        with patch.dict(native.os.environ, {
            "GITHUB_TOKEN": "invented-opaque-value", "ACTIONS_RUNTIME_TOKEN": "invented-ci-value",
            native.CANARY_NAME: "synthetic-ambient-canary",
        }):
            eval(compile(ast.Expression(creation), native.__file__, "eval"), namespace)
        options = capture.call_args.kwargs
        self.assertEqual(options["env"], native.isolated_environment(root))
        self.assertNotIn("invented-opaque-value", options["env"].values())
        self.assertNotIn("ACTIONS_RUNTIME_TOKEN", options["env"])
        self.assertNotIn(native.CANARY_NAME, options["env"])
        self.assertIsNone(options["github_token"])
        self.assertFalse(options["use_logged_in_user"])

    def test_child_reads_original_owned_fixture_before_constructing_sdk_client(self):
        body = next(node for node in self.tree.body[0].body if isinstance(node, ast.Try)).body
        client = next(node for node in self.calls if ast.unparse(node.func) == "CopilotClient")
        setup = [node for node in body if node.lineno < client.lineno]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "workspace").mkdir()
            (root / "protected").mkdir()
            fixture = root / "protected" / "control-plane.txt"
            original = "a" * 32
            fixture.write_text(original, encoding="utf-8")
            namespace = {**vars(native), "root": root}
            exec(compile(ast.Module(body=setup, type_ignores=[]), native.__file__, "exec"),
                 namespace)
            self.assertEqual(namespace["protected_marker"], original)
            self.assertEqual(fixture.read_text(encoding="utf-8"), original)


class NativeCompletionDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.completion = native._ProtectedReadCompletion()
        self.completion.active = True

    def safe_report(self, diagnostic):
        return native.safe_failure_report(json.dumps({
            "check": "native_file_denial", "reason": "explicit_native_denial_required",
            "protected_read": {}, "protected_completion": diagnostic,
        }))

    def test_actual_python_typed_event_matches_and_only_retains_safe_fields(self):
        from copilot.session_events import (
            SessionEventType, ToolExecutionCompleteData, session_event_from_dict,
        )

        event = session_event_from_dict(completion_event(
            error={"message": "sensitive-message /private/path", "code": "sensitive-code",
                   "remediation": "review_sandbox_policy"},
            result={"content": "sensitive-protected-content"},
            toolTelemetry={"private": "sensitive-metadata"},
        ))
        self.assertIs(event.type, SessionEventType.TOOL_EXECUTION_COMPLETE)
        self.assertIsInstance(event.data, ToolExecutionCompleteData)
        self.completion.observe(event)
        expected = {
            "event": "seen", "correlation": "match", "success": False,
            "error": "present", "code": "present", "remediation": "review_sandbox_policy",
        }
        self.assertEqual(self.completion.diagnostic, expected)
        self.assertEqual(self.safe_report(expected)["protected_completion"], expected)
        self.assertNotIn("sensitive", json.dumps(self.safe_report(expected)))

    def test_remediation_allowlist_exactly_matches_pinned_python_enum(self):
        from copilot.session_events import RemediationAction, session_event_from_dict

        self.assertEqual(set(native.COMPLETION_REMEDIATIONS),
                         {item.value for item in RemediationAction})
        for remediation in RemediationAction:
            with self.subTest(remediation=remediation.value):
                completion = native._ProtectedReadCompletion()
                completion.active = True
                completion.observe(session_event_from_dict(completion_event(
                    error={"message": "sensitive-message", "remediation": remediation.value})))
                self.assertEqual(completion.diagnostic["remediation"], remediation.value)
                self.assertEqual(self.safe_report(completion.diagnostic)["protected_completion"],
                                 completion.diagnostic)

    def test_absence_and_internal_sandbox_events_are_not_denial_evidence(self):
        expected = dict(self.completion.diagnostic)
        self.completion.observe({
            "type": "sandbox.decision",
            "data": {"toolCallId": native.PROTECTED_READ_CALL_ID, "success": False,
                     "error": {"remediation": "review_sandbox_policy"}},
        })
        self.assertEqual(self.completion.diagnostic, expected)
        self.assertEqual(self.safe_report(expected)["protected_completion"], expected)
        self.assertEqual(expected["event"], "not_seen")
        self.assertEqual(expected["success"], "unknown")

    def test_positive_and_unrelated_completions_never_supply_protected_error_details(self):
        for call_id in (native.POSITIVE_READ_CALL_ID, "sensitive-unrelated-id"):
            with self.subTest(call_id=call_id):
                self.completion.observe(completion_event(
                    call_id, error={"message": "sensitive", "code": "sensitive",
                                    "remediation": "review_sandbox_policy"}))
                self.assertEqual(self.completion.diagnostic, {
                    "event": "seen", "correlation": "mismatch", "success": "unknown",
                    "error": "unknown", "code": "unknown", "remediation": "absent",
                })

    def test_matching_event_supersedes_nonmatches_and_late_events_cannot_contaminate_it(self):
        self.completion.observe(completion_event(native.POSITIVE_READ_CALL_ID, success=True))
        self.completion.observe(completion_event(
            error={"message": "sensitive", "remediation": "review_sandbox_policy"}))
        expected = dict(self.completion.diagnostic)
        for call_id in (native.POSITIVE_READ_CALL_ID, "unrelated",
                        native.PROTECTED_READ_CALL_ID, None):
            self.completion.observe(completion_event(
                call_id, success=True, error={"message": "sensitive", "remediation": "sign_in"}))
        self.assertEqual(self.completion.diagnostic, expected)
        self.assertEqual(expected["correlation"], "match")
        self.assertIs(expected["success"], False)
        self.assertEqual(expected["remediation"], "review_sandbox_policy")

    def test_inactive_window_ignores_matching_events_before_and_after_probe(self):
        self.completion.active = False
        expected = dict(self.completion.diagnostic)
        self.completion.observe(completion_event())
        self.assertEqual(self.completion.diagnostic, expected)
        self.completion.active = True
        self.completion.observe(completion_event(success=True))
        expected = dict(self.completion.diagnostic)
        self.completion.active = False
        self.completion.observe(completion_event(error={"message": "sensitive"}))
        self.assertEqual(self.completion.diagnostic, expected)

    def test_missing_and_malformed_correlation_never_attributes_details(self):
        for call_id, expected in ((None, "absent"), ("", "absent"), ([], "unrecognized"),
                                  ({}, "unrecognized"), (True, "unrecognized"),
                                  (1, "unrecognized")):
            with self.subTest(call_id_type=type(call_id).__name__):
                completion = native._ProtectedReadCompletion()
                completion.active = True
                completion.observe(completion_event(
                    call_id, success=True, error={"message": "sensitive", "code": "sensitive"}))
                self.assertEqual(completion.diagnostic, {
                    "event": "seen", "correlation": expected, "success": "unknown",
                    "error": "unknown", "code": "unknown", "remediation": "absent",
                })
        self.completion.observe({"type": "tool.execution_complete", "data": {}})
        self.assertEqual(self.completion.diagnostic["correlation"], "absent")
        self.assertEqual(self.completion.diagnostic["error"], "unknown")

    def test_malformed_events_are_bounded_and_do_not_raise(self):
        for event in (None, {}, [], "sensitive", {"type": []},
                      {"type": "tool.execution_complete"},
                      {"type": "tool.execution_complete", "data": "sensitive"}):
            self.completion.observe(event)
        self.assertEqual(self.completion.diagnostic, {
            "event": "seen", "correlation": "absent", "success": "unknown",
            "error": "unknown", "code": "unknown", "remediation": "absent",
        })
        for _ in range(200):
            self.completion.observe(completion_event("sensitive-unrelated-id" * 100))
        self.assertEqual(len(self.completion.diagnostic), 6)
        self.assertLess(len(json.dumps(self.completion.diagnostic)), 200)
        self.assertFalse(hasattr(self.completion, "__dict__"))
        self.assertNotIn("sensitive", json.dumps(self.completion.diagnostic))

    def test_only_strict_boolean_success_and_allowlisted_remediation_survive(self):
        for value in (None, 0, 1, "true", "sensitive", [], {}):
            with self.subTest(value_type=type(value).__name__):
                completion = native._ProtectedReadCompletion()
                completion.active = True
                completion.observe(completion_event(
                    success=value, error={"message": "sensitive", "remediation": value}))
                self.assertEqual(completion.diagnostic["success"], "unknown")
                self.assertEqual(completion.diagnostic["remediation"],
                                 "absent" if value is None else "unrecognized")
                self.assertNotIn("sensitive", json.dumps(self.safe_report(completion.diagnostic)))
        self.completion.observe(completion_event(success=True))
        self.assertIs(self.completion.diagnostic["success"], True)
        self.assertEqual(self.completion.diagnostic["error"], "absent")
        self.assertEqual(self.completion.diagnostic["code"], "absent")
        self.assertIs(self.safe_report(self.completion.diagnostic)["protected_completion"]["success"],
                      True)

    def test_error_and_code_are_presence_only_even_for_malformed_values(self):
        for error, code in ((None, "absent"), ({}, "absent"),
                            ("sensitive", "absent"), ([], "absent"),
                            ({"code": None}, "absent"), ({"code": ""}, "present"),
                            ({"code": {"sensitive": "value"}}, "present")):
            with self.subTest(error_type=type(error).__name__):
                completion = native._ProtectedReadCompletion()
                completion.active = True
                completion.observe(completion_event(error=error))
                self.assertEqual(completion.diagnostic["error"],
                                 "absent" if error is None else "present")
                self.assertEqual(completion.diagnostic["code"], code)
                self.assertNotIn("sensitive", json.dumps(completion.diagnostic))

    def test_observer_never_reads_message_result_arguments_or_metadata(self):
        class Error:
            code = "sensitive"
            remediation = None

            def __getattr__(self, _name):
                raise AssertionError("accessed forbidden error field")

        class Data:
            tool_call_id = native.PROTECTED_READ_CALL_ID
            success = False
            error = Error()

            def __getattr__(self, _name):
                raise AssertionError("accessed forbidden completion field")

        self.completion.observe(SimpleNamespace(type="tool.execution_complete", data=Data()))
        self.assertEqual(self.completion.diagnostic["code"], "present")

    def test_failure_boundary_rejects_malicious_fields_and_nonboolean_success(self):
        for value in (0, 1, None, [], {}, "sensitive"):
            with self.subTest(value_type=type(value).__name__):
                safe = self.safe_report({
                    "event": "seen", "correlation": "match", "success": value,
                    "error": value, "code": value, "remediation": value,
                    "message": "sensitive-message", "arguments": {"path": "sensitive-path"},
                    "result": "sensitive-content", "metadata": "sensitive-metadata",
                })["protected_completion"]
                self.assertEqual(safe, {"event": "seen", "correlation": "match"})
        self.assertNotIn("protected_completion", self.safe_report([]))

    def test_failure_boundary_does_not_attribute_forged_uncorrelated_errors(self):
        for event, correlation in (("not_seen", "match"), ("seen", "mismatch"),
                                   ("seen", "absent"), ("seen", "unrecognized"),
                                   ("sensitive", "sensitive")):
            with self.subTest(event=event, correlation=correlation):
                safe = self.safe_report({
                    "event": event, "correlation": correlation, "success": False,
                    "error": "present", "code": "present", "remediation": "sign_in",
                })["protected_completion"]
                self.assertEqual(safe["success"], "unknown")
                self.assertEqual(safe["error"], "unknown")
                self.assertEqual(safe["code"], "unknown")
                self.assertEqual(safe["remediation"], "absent")
                self.assertNotIn("sensitive", json.dumps(safe))

    def test_completion_is_only_reported_for_protected_probe_failure_context(self):
        for check, reason in (("native_toolset", "explicit_native_denial_required"),
                              ("native_file_denial", "native_file_positive_control_failed"),
                              ("native_file_denial", "sensitive"),
                              ("bounded_cleanup", "operation_failed")):
            with self.subTest(check=check, reason=reason):
                safe = native.safe_failure_report(json.dumps({
                    "check": check, "reason": reason, "protected_read": {},
                    "protected_completion": self.completion.diagnostic,
                }))
                self.assertNotIn("protected_completion", safe)

    def test_registered_handler_keeps_model_activity_checks_and_routes_completion(self):
        tree = ast.parse(inspect.getsource(native.native_checks))
        handler = next(node for node in tree.body[0].body
                       if isinstance(node, ast.FunctionDef) and node.name == "on_event")
        activity = Mock()
        namespace = {**vars(native), "model_activity": activity,
                     "protected_completion": self.completion}
        exec(compile(ast.Module(body=[handler], type_ignores=[]), native.__file__, "exec"),
             namespace)
        namespace["on_event"](completion_event())
        activity.set.assert_not_called()
        self.assertEqual(self.completion.diagnostic["correlation"], "match")
        for kind in ("assistant.turn_start", "assistant.message", "assistant.message_delta"):
            namespace["on_event"](SimpleNamespace(type=SimpleNamespace(value=kind)))
        self.assertEqual(activity.set.call_count, 3)


class NativeEntrypointTests(unittest.TestCase):
    def test_import_does_not_import_sdk_or_create_event_loop(self):
        code = (
            "import builtins, runpy\n"
            "original = builtins.__import__\n"
            "def guarded(name, *args, **kwargs):\n"
            "    if name.split('.')[0] in ('copilot', 'asyncio'):\n"
            "        raise AssertionError('runtime import during discovery')\n"
            "    return original(name, *args, **kwargs)\n"
            "builtins.__import__ = guarded\n"
            f"runpy.run_path({str(Path(native.__file__).resolve())!r})\n"
        )
        result = subprocess.run(
            [sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_execution_requires_both_explicit_gate_and_runtime_path(self):
        with patch.object(native, "check_prerequisites") as prerequisites:
            with self.assertRaises(SystemExit) as error:
                native.main(["--runtime-path", "/not/executed"])
        self.assertEqual(error.exception.code, 2)
        prerequisites.assert_not_called()

    def test_missing_runtime_path_fails_before_prerequisites(self):
        with patch.object(native, "check_prerequisites") as prerequisites:
            with self.assertRaises(SystemExit) as error:
                native.main(["--run-native"])
        self.assertEqual(error.exception.code, 2)
        prerequisites.assert_not_called()

    def test_explicit_execution_on_non_linux_fails_without_sdk_lookup(self):
        with patch.object(native.sys, "platform", "win32"):
            with patch.object(native.metadata, "distribution") as distribution:
                with self.assertRaisesRegex(native.CheckFailure, "hosted_linux_required"):
                    native.check_prerequisites(Path("/not/executed"))
        distribution.assert_not_called()

    def test_missing_sdk_is_failure_not_skip(self):
        with patch.object(native.sys, "platform", "linux"):
            with patch.object(native.metadata, "distribution",
                              side_effect=native.metadata.PackageNotFoundError):
                with self.assertRaisesRegex(native.CheckFailure, "sdk_not_installed"):
                    native.check_prerequisites(Path("/not/executed"))

    def test_wrong_sdk_version_fails_before_reading_publisher_pin(self):
        distribution = Mock(version="1.0.22")
        with patch.object(native.sys, "platform", "linux"):
            with patch.object(native.metadata, "distribution", return_value=distribution):
                with self.assertRaisesRegex(native.CheckFailure, "sdk_version_mismatch"):
                    native.check_prerequisites(Path("/not/executed"))
        distribution.locate_file.assert_not_called()

    def test_publisher_pin_mismatch_fails_without_starting_runtime(self):
        distribution = Mock(version=native.SDK_VERSION)
        distribution.locate_file.return_value.read_text.return_value = (
            'CLI_VERSION: str | None = "1.0.100"\n'
        )
        with patch.object(native.sys, "platform", "linux"):
            with patch.object(native.metadata, "distribution", return_value=distribution):
                with self.assertRaisesRegex(native.CheckFailure, "publisher_cli_pin_mismatch"):
                    native.check_prerequisites(Path("/not/executed"))

    def test_runtime_environment_does_not_inherit_credentials_or_canary(self):
        with patch.dict(native.os.environ, {"GITHUB_TOKEN": "synthetic-not-a-token",
                                           native.CANARY_NAME: "synthetic-canary"}):
            env = native.isolated_environment(Path("/synthetic"))
        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertNotIn(native.CANARY_NAME, env)
        self.assertEqual(env["COPILOT_SKIP_CLI_DOWNLOAD"], "1")
        self.assertEqual(env["HOME"], "/synthetic/home".replace("/", native.os.sep))

    def test_only_explicit_native_denial_counts_as_denial(self):
        native.require_denial({"resultType": "denied"})
        native.require_denial(SimpleNamespace(result_type="rejected"))
        with self.assertRaisesRegex(native.CheckFailure, "explicit_native_denial_required"):
            native.require_denial({"resultType": "failure", "error": "missing auth"})
        with self.assertRaises(native.CheckFailure):
            native.require_denial({"resultType": "success"})
        with self.assertRaises(native.CheckFailure):
            native.require_denial({})

    def test_outer_timeout_kills_only_owned_group_and_returns_failure(self):
        process = Mock(pid=12345)
        process.communicate.side_effect = [
            subprocess.TimeoutExpired("synthetic", native.OUTER_TIMEOUT), ("", None),
        ]
        with patch.object(native.subprocess, "Popen", return_value=process) as launch:
            with patch.object(native, "kill_owned_group") as kill:
                with redirect_stdout(io.StringIO()) as output:
                    status = native.run_bounded(Path("/synthetic/runtime"))
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(output.getvalue())["check"], "outer_timeout")
        kill.assert_called_once_with(process)
        self.assertTrue(launch.call_args.kwargs["start_new_session"])
        self.assertEqual(process.communicate.call_args_list[0].kwargs,
                         {"timeout": native.OUTER_TIMEOUT})
        self.assertEqual(process.communicate.call_args_list[1].kwargs, {"timeout": 5})

    def test_success_requires_every_native_stage_and_child_zero_exit(self):
        report = {"status": "pass", "check": "bounded_cleanup",
                  "sdk": native.SDK_VERSION, "publisher_cli": native.CLI_VERSION,
                  "runtime": native.CLI_VERSION, "protocol": 1, "passed": list(native.CHECKS)}
        process = Mock(pid=12345, returncode=0)
        process.communicate.return_value = (json.dumps(report), None)
        with patch.object(native.subprocess, "Popen", return_value=process):
            with patch.object(native, "kill_owned_group") as kill:
                with redirect_stdout(io.StringIO()):
                    status = native.run_bounded(Path("/synthetic/runtime"))
        self.assertEqual(status, 0)
        kill.assert_called_once_with(process)

    def test_success_stdout_shape_is_unchanged_even_with_extra_child_diagnostics(self):
        expected = {"status": "pass", "check": "bounded_cleanup",
                    "sdk": native.SDK_VERSION, "publisher_cli": native.CLI_VERSION,
                    "runtime": native.CLI_VERSION, "protocol": 3, "passed": list(native.CHECKS)}
        process = Mock(pid=12345, returncode=0)
        process.communicate.return_value = (json.dumps({
            **expected, "protected_completion": {"error": "sensitive"},
            "protected_read": {"marker": "absent"},
            "protected_error": {"source": "error", "text": "sensitive"},
        }), None)
        with patch.object(native.subprocess, "Popen", return_value=process):
            with patch.object(native, "kill_owned_group"):
                with redirect_stdout(io.StringIO()) as output:
                    status = native.run_bounded(Path("/synthetic/runtime"))
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue()), expected)
        self.assertNotIn("sensitive", output.getvalue())

    def test_failure_stdout_retains_only_safe_correlated_completion_summary(self):
        process = Mock(pid=12345, returncode=1)
        completion = {
            "event": "seen", "correlation": "match", "success": False,
            "error": "present", "code": "present", "remediation": "review_sandbox_policy",
        }
        process.communicate.return_value = (json.dumps({
            "status": "fail", "check": "native_file_denial",
            "reason": "explicit_native_denial_required", "protected_read": {},
            "protected_completion": {
                **completion, "message": "sensitive-message", "result": "sensitive-content",
                "toolCallId": "sensitive-id", "arguments": {"path": "sensitive-path"},
                "metadata": "sensitive-metadata",
            },
        }), None)
        with patch.object(native.subprocess, "Popen", return_value=process):
            with patch.object(native, "kill_owned_group"):
                with redirect_stdout(io.StringIO()) as output:
                    status = native.run_bounded(Path("/synthetic/runtime"))
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(output.getvalue())["protected_completion"], completion)
        self.assertNotIn("sensitive", output.getvalue())

    def test_zero_exit_with_incomplete_checks_is_not_green(self):
        process = Mock(pid=12345, returncode=0)
        process.communicate.return_value = (json.dumps({
            "status": "pass", "check": "runtime_identity", "passed": ["runtime_identity"],
        }), None)
        with patch.object(native.subprocess, "Popen", return_value=process):
            with patch.object(native, "kill_owned_group"):
                with redirect_stdout(io.StringIO()):
                    status = native.run_bounded(Path("/synthetic/runtime"))
        self.assertEqual(status, 1)

    def test_nonzero_exit_overrides_a_complete_success_report(self):
        process = Mock(pid=12345, returncode=1)
        process.communicate.return_value = (json.dumps({
            "status": "pass", "check": "bounded_cleanup", "sdk": native.SDK_VERSION,
            "publisher_cli": native.CLI_VERSION, "runtime": native.CLI_VERSION,
            "protocol": 1, "passed": list(native.CHECKS),
        }), None)
        with patch.object(native.subprocess, "Popen", return_value=process):
            with patch.object(native, "kill_owned_group"):
                with redirect_stdout(io.StringIO()):
                    status = native.run_bounded(Path("/synthetic/runtime"))
        self.assertEqual(status, 1)

    def test_native_failure_is_nonzero_with_only_allowlisted_diagnostics(self):
        process = Mock(pid=12345, returncode=1)
        process.communicate.return_value = (json.dumps({
            "status": "fail", "check": "session_startup",
            "reason": "authentication_required", "passed": ["runtime_identity"],
            "error": "synthetic-sensitive-runtime-diagnostic",
        }), None)
        with patch.object(native.subprocess, "Popen", return_value=process):
            with patch.object(native, "kill_owned_group"):
                with redirect_stdout(io.StringIO()) as output:
                    status = native.run_bounded(Path("/synthetic/runtime"))
        self.assertEqual(status, 1)
        self.assertNotIn("sensitive", output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["reason"], "authentication_required")

    def test_malformed_output_is_not_relayed(self):
        self.assertEqual(native.safe_failure_report("synthetic-sensitive-diagnostic"), {
            "status": "fail", "check": "invalid_child_report",
        })


class NativeErrorTextTests(unittest.TestCase):
    def setUp(self):
        self.root = Path("/synthetic")
        self.marker = "synthetic-protected-marker"
        # All environment values in these tests are invented, never CI secrets.
        self.environment = patch.dict(native.os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def scrub(self, text):
        return native._scrub_native_error(text, root=self.root, protected_marker=self.marker)

    def candidate(self, error):
        return {
            "status": "fail", "check": "native_file_denial",
            "reason": "explicit_native_denial_required",
            "denial_result": {"shape": "mapping", "kind": "failure"},
            "protected_read": {"marker": "absent"},
            "protected_error": error,
        }

    def outer(self, candidate):
        return native.safe_failure_report(
            json.dumps(candidate), root=self.root, protected_marker=self.marker)

    def test_pinned_error_string_precedes_text_fallback_without_reading_other_fields(self):
        from copilot.rpc import ToolResultExpanded

        wire = ToolResultExpanded.from_dict({
            "resultType": "failure", "textResultForLlm": "not-the-error",
            "error": "Synthetic filesystem policy could not initialize",
        }).to_dict()
        wire.update(sessionLog=object(), contents=object(), structuredContent=object(),
                    toolTelemetry=object())
        diagnostic = native._protected_error(
            wire, root=self.root, protected_marker=self.marker)
        self.assertEqual(diagnostic, {
            "source": "error", "text": "Synthetic filesystem policy could not initialize",
        })
        self.assertEqual(self.outer(self.candidate(diagnostic))["protected_error"], diagnostic)

    def test_missing_null_empty_and_whitespace_error_use_same_scrubbed_fallback(self):
        for fields in ({}, {"error": None}, {"error": ""}, {"error": " \n\t"}):
            with self.subTest(fields=fields):
                diagnostic = native._protected_error({
                    "resultType": "failure", "textResultForLlm": "Synthetic read unavailable",
                    **fields,
                }, root=self.root, protected_marker=self.marker)
                self.assertEqual(diagnostic, {
                    "source": "textResultForLlm", "text": "Synthetic read unavailable",
                })

    def test_malformed_mixed_fields_do_not_fall_back_or_stringify(self):
        class NoString:
            def __str__(self):
                raise AssertionError("must not stringify")

            def __repr__(self):
                raise AssertionError("must not repr")

        for value in (True, 1, [], {}, NoString()):
            for field in ("error", "textResultForLlm"):
                with self.subTest(value_type=type(value).__name__, field=field):
                    diagnostic = native._protected_error({
                        "resultType": "failure", "error": "Synthetic error",
                        "textResultForLlm": "Synthetic fallback", field: value,
                    }, root=self.root, protected_marker=self.marker)
                    self.assertEqual(diagnostic, {"suppressed": "malformed"})
        self.assertEqual(native._protected_error(
            NoString(), root=self.root, protected_marker=self.marker),
            {"suppressed": "malformed"})

    def test_full_candidate_is_scanned_before_truncation_or_path_redaction(self):
        prefix = "x" * native.ERROR_TEXT_LIMIT
        with self.assertRaisesRegex(native.CheckFailure, "^protected_canary_leaked$"):
            self.scrub(prefix + self.marker)
        with patch.dict(native.os.environ, {"GITHUB_TOKEN": "synthetic-known-value"}):
            self.assertEqual(self.scrub(prefix + "synthetic-known-value"),
                             {"suppressed": "credential_material"})
            self.assertEqual(self.scrub(str(self.root / "synthetic-known-value")),
                             {"suppressed": "credential_material"})
        self.assertEqual(self.scrub(prefix + " Bearer synthetic-value"),
                         {"suppressed": "credential_material"})

    def test_known_environment_credentials_are_suppressed_without_forwarding_them(self):
        for name in ("GITHUB_TOKEN", "GH_TOKEN", "COPILOT_GITHUB_TOKEN",
                     "ACTIONS_RUNTIME_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
                     "AZURE_CLIENT_SECRET", "OPENAI_API_KEY", "AZURE_OPENAI_KEY", "SERVICE_PASSWORD",
                     "AWS_SECRET_ACCESS_KEY", "SERVICE_CONNECTION_STRING"):
            with self.subTest(name=name):
                with patch.dict(native.os.environ, {name: "invented-opaque-value"}):
                    self.assertEqual(self.scrub("failure: invented-opaque-value"),
                                     {"suppressed": "credential_material"})
                    env = native.isolated_environment(self.root)
                    self.assertNotIn(name, env)
                    self.assertNotIn("invented-opaque-value", env.values())

    def test_credential_patterns_suppress_the_entire_error_in_child_and_parent(self):
        for text in (
            "Bearer invented", "Authorization: Basic invented", "Authorization: invented",
            "token=synthetic", '"access_token": "synthetic"', "api-key: synthetic",
            "password=synthetic", "AccountKey=synthetic", "sig=synthetic",
            "https://invented:invented@example.invalid/path",
            "-----BEGIN PRIVATE KEY-----\ninvented",
            "-----BEGIN RSA PRIVATE KEY-----\ninvented",
            "ghp_" + "synthetic" * 5, "github_pat_" + "synthetic" * 5,
            "sk-" + "synthetic" * 5, "AKIA" + "SYNTHETIC" * 3,
            "AIza" + "synthetic" * 5, "xoxb-" + "synthetic" * 5,
            "eyJsynthetic.eyJsynthetic.synthetic",
            "Be\x00arer invented", "to\u202eken=synthetic", "Be\x1b[31marer invented",
        ):
            with self.subTest(case=text[:12]):
                self.assertEqual(self.scrub(text), {"suppressed": "credential_material"})
                safe = self.outer(self.candidate({"source": "error", "text": text}))
                self.assertEqual(safe["protected_error"], {"suppressed": "credential_material"})
                self.assertNotIn(text, json.dumps(safe))

    def test_controls_ansi_and_workflow_commands_cannot_be_echoed_as_commands(self):
        text = "\x1b[31mSynthetic\n::error::failed\r\t\x00\x7f\u0085\u202e\u2028\u2029"
        diagnostic = self.scrub(text)
        self.assertEqual(diagnostic, {"text": "Synthetic: :error: :failed"})
        safe = self.outer(self.candidate({"source": "error", "text": text}))
        self.assertEqual(safe["protected_error"]["text"], diagnostic["text"])
        self.assertNotIn("::", json.dumps(safe))
        self.assertNotIn("\n", json.dumps(safe))

    def test_known_synthetic_repo_runner_home_and_temp_paths_are_labelled(self):
        with patch.dict(native.os.environ, {
            "GITHUB_WORKSPACE": str(Path("/repo").absolute()),
            "RUNNER_WORKSPACE": str(Path("/runner").absolute()),
            "RUNNER_TEMP": str(Path("/runner-temp").absolute()),
            "HOME": str(Path("/runner-home").absolute()),
        }):
            text = " | ".join(str(path) for path in (
                self.root / "protected" / "control-plane.txt",
                Path("/repo/file.py").absolute(), Path("/runner/job").absolute(),
                Path("/runner-temp/scratch").absolute(), Path("/runner-home/config").absolute(),
                Path(native.__file__).resolve().parents[3] / "eval",
                Path(tempfile.gettempdir()) / "scratch",
            ))
            result = self.scrub(text)
        expected = " | ".join((
            "[synthetic]/protected/control-plane.txt", "[repo]/file.py",
            "[runner]/job", "[temp]/scratch", "[home]/config",
            "[repo]/eval", "[temp]/scratch",
        )).replace("/", native.os.sep)
        self.assertEqual(result, {"text": expected})
        self.assertEqual(self.scrub("cannot read /unrecognized-private/file"),
                         {"suppressed": "unrecognized_path"})

    def test_limits_empty_context_and_bad_types_suppress_without_partial_output(self):
        self.assertEqual(self.scrub("x" * native.ERROR_INPUT_LIMIT),
                         {"text": "x" * native.ERROR_INPUT_LIMIT})
        self.assertEqual(self.outer(self.candidate({
            "source": "error", "text": "x" * native.ERROR_INPUT_LIMIT,
        }))["protected_error"]["text"], "x" * native.ERROR_TEXT_LIMIT)
        self.assertEqual(self.scrub("x" * (native.ERROR_INPUT_LIMIT + 1)),
                         {"suppressed": "oversized"})
        self.assertEqual(self.scrub(" \n\t"), {"suppressed": "empty"})
        self.assertEqual(self.scrub(None), {"suppressed": "malformed"})
        self.assertEqual(native._scrub_native_error(
            "Synthetic", root=None, protected_marker=self.marker),
            {"suppressed": "context_missing"})
        self.assertEqual(native._scrub_native_error(
            "Synthetic", root=self.root, protected_marker=None),
            {"suppressed": "context_missing"})
        for field in ("error", "textResultForLlm"):
            diagnostic = native._protected_error({
                "resultType": "failure", "error": "Synthetic", "textResultForLlm": "",
                field: "x" * (native.ERROR_INPUT_LIMIT + 1),
            }, root=self.root, protected_marker=self.marker)
            self.assertEqual(diagnostic, {"suppressed": "oversized"})

    def test_parent_revalidates_bounds_structure_and_original_marker(self):
        for diagnostic in (None, [], "synthetic", {"text": "synthetic"},
                           {"source": "sessionLog", "text": "synthetic"},
                           {"source": "error", "text": "synthetic", "extra": "private"},
                           {"source": "error", "text": []},
                           {"suppressed": "untrusted-reason"}):
            with self.subTest(diagnostic_type=type(diagnostic).__name__):
                self.assertEqual(self.outer(self.candidate(diagnostic))["protected_error"],
                                 {"suppressed": "malformed"})
        safe = self.outer(self.candidate({
            "source": "error", "text": "x" * (native.ERROR_INPUT_LIMIT + 1),
        }))
        self.assertEqual(safe["protected_error"], {"suppressed": "oversized"})
        safe = self.outer(self.candidate({
            "source": "error", "text": "x" * native.ERROR_TEXT_LIMIT + self.marker,
        }))
        self.assertEqual(safe["reason"], "protected_canary_leaked")
        self.assertEqual(safe["protected_read"]["marker"], "present")
        self.assertNotIn("protected_error", safe)
        self.assertNotIn(self.marker, json.dumps(safe))
        self.assertEqual(native.safe_failure_report(" " * (native.CHILD_REPORT_LIMIT + 1)), {
            "status": "fail", "check": "invalid_child_report",
        })

    def test_parent_requires_exact_failure_context_and_never_uses_child_context(self):
        diagnostic = {"source": "error", "text": "Synthetic error"}
        for overrides in (
            {"check": "native_toolset"}, {"check": "bounded_cleanup"},
            {"reason": "native_file_positive_control_failed"}, {"reason": "protected_canary_leaked"},
            {"reason": "permission_session_mismatch"}, {"status": "pass"},
            {"denial_result": {"shape": "mapping", "kind": "denied"}},
            {"protected_read": {"marker": "unknown"}}, {"protected_read": {"marker": "present"}},
        ):
            with self.subTest(overrides=overrides):
                self.assertNotIn("protected_error", self.outer({
                    **self.candidate(diagnostic), **overrides,
                }))
        safe = native.safe_failure_report(json.dumps({
            **self.candidate(diagnostic), "root": "/synthetic", "protected_marker": "forged",
        }))
        self.assertEqual(safe["protected_error"], {"suppressed": "context_missing"})

    def test_outer_retains_original_root_marker_even_if_child_replaces_fixture(self):
        original = []

        def launch(_args, **options):
            root = Path(options["cwd"]).parent
            fixture = root / "protected" / "control-plane.txt"
            original.append(fixture.read_text(encoding="utf-8"))
            fixture.write_text("replacement", encoding="utf-8")
            self.assertNotIn("GITHUB_TOKEN", options["env"])
            self.assertNotIn("invented-opaque-value", options["env"].values())
            payload = self.candidate({
                "source": "error", "text": "x" * native.ERROR_TEXT_LIMIT + original[0],
            })
            payload.update(root="forged", protected_marker="replacement")
            process = Mock(pid=12345, returncode=1)
            process.communicate.return_value = (json.dumps(payload), None)
            return process

        with patch.dict(native.os.environ, {"GITHUB_TOKEN": "invented-opaque-value"}):
            with patch.object(native.subprocess, "Popen", side_effect=launch):
                with patch.object(native, "kill_owned_group"):
                    with redirect_stdout(io.StringIO()) as output:
                        status = native.run_bounded(Path("/synthetic/runtime"))
        self.assertEqual(status, 1)
        report = json.loads(output.getvalue())
        self.assertEqual(report["reason"], "protected_canary_leaked")
        self.assertNotIn("protected_error", report)
        self.assertNotIn(original[0], output.getvalue())

    def test_outer_stdout_renders_meaningful_error_as_one_json_line_and_remains_failure(self):
        process = Mock(pid=12345, returncode=1)
        process.communicate.return_value = (json.dumps(self.candidate({
            "source": "error", "text": "Synthetic filesystem policy could not initialize",
        })), None)
        with patch.object(native.subprocess, "Popen", return_value=process):
            with patch.object(native, "kill_owned_group"):
                with redirect_stdout(io.StringIO()) as output:
                    status = native.run_bounded(Path("/synthetic/runtime"))
        self.assertEqual(status, 1)
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        report = json.loads(output.getvalue())
        self.assertEqual(report["reason"], "explicit_native_denial_required")
        self.assertEqual(report["protected_error"]["text"],
                         "Synthetic filesystem policy could not initialize")

    def test_outer_rescans_forged_child_text_for_parent_only_credential_before_truncation(self):
        process = Mock(pid=12345, returncode=1)
        process.communicate.return_value = (json.dumps(self.candidate({
            "source": "error",
            "text": "x" * native.ERROR_TEXT_LIMIT + "invented-parent-only-value",
        })), None)
        with patch.dict(native.os.environ, {"GITHUB_TOKEN": "invented-parent-only-value"}):
            with patch.object(native.subprocess, "Popen", return_value=process):
                with patch.object(native, "kill_owned_group"):
                    with redirect_stdout(io.StringIO()) as output:
                        status = native.run_bounded(Path("/synthetic/runtime"))
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(output.getvalue())["protected_error"],
                         {"suppressed": "credential_material"})
        self.assertNotIn("invented-parent-only-value", output.getvalue())

    def test_child_does_not_split_parent_only_secret_before_parent_can_scan_it(self):
        secret = "invented-parent-only-value"
        # Model the real minimal child environment: it does not know this value.
        diagnostic = native._protected_error({
            "resultType": "failure", "textResultForLlm": "",
            "error": "x" * (native.ERROR_TEXT_LIMIT - 5) + secret,
        }, root=self.root, protected_marker=self.marker)
        self.assertTrue(diagnostic["text"].endswith(secret))
        with patch.dict(native.os.environ, {"GITHUB_TOKEN": secret}):
            report = self.outer(self.candidate(diagnostic))
        self.assertEqual(report["protected_error"], {"suppressed": "credential_material"})
        self.assertNotIn(secret[:5], json.dumps(report))


class NativePositiveReadPermissionTests(unittest.TestCase):
    """Run the actual synchronous callback with pinned SDK types, never a loop."""

    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(inspect.getsource(native.native_checks))
        cls.imports = [node for node in cls.tree.body[0].body
                       if isinstance(node, ast.ImportFrom) and node.module.startswith("copilot")]
        callback = next(node for node in cls.tree.body[0].body
                        if isinstance(node, ast.FunctionDef) and node.name == "permission")
        cls.callback_code = compile(ast.Module(body=[callback], type_ignores=[]),
                                    native.__file__, "exec")

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.fixture = self.workspace / "readable.txt"
        self.fixture.write_text("native-readable-canary", encoding="utf-8")
        self.protected = self.root / "protected.txt"
        self.protected.write_text("synthetic-protected-canary", encoding="utf-8")
        self.namespace = {
            **vars(native), "session_id": "owned-session", "readable_path": self.fixture,
            "positive_read_pending": True, "positive_read_decisions": [],
            "permission_sessions": [], "protected_read_pending": False,
            "protected": self.protected, "protected_observation": {
                "callback": "not_requested", "callback_session": "not_requested",
            },
        }
        exec(compile(ast.Module(body=self.imports, type_ignores=[]), native.__file__, "exec"),
             self.namespace)
        exec(self.callback_code, self.namespace)
        self.permission = self.namespace["permission"]
        self.context = {"session_id": "owned-session"}

    def request(self, **overrides):
        from copilot.session_events import PermissionRequestRead

        return PermissionRequestRead(**{
            "intention": "Read synthetic fixture", "path": str(self.fixture), **overrides,
        })

    def assert_rejected(self, request, context=None):
        from copilot.rpc import PermissionDecisionReject

        decision = self.permission(request, self.context if context is None else context)
        self.assertIs(type(decision), PermissionDecisionReject)
        self.assertEqual(decision.to_dict(), {
            "kind": "reject", "feedback": "native_check_denied",
        })

    def test_exact_typed_fixture_read_is_approved_once_and_session_is_recorded(self):
        from copilot.rpc import PermissionDecisionApproveOnce

        for resolved in (None, str(self.fixture)):
            with self.subTest(resolved=resolved):
                decision = self.permission(self.request(resolved_path=resolved), self.context)
                self.assertIs(type(decision), PermissionDecisionApproveOnce)
                self.assertEqual(decision.to_dict(), {"kind": "approve-once"})
        self.assertEqual(self.namespace["permission_sessions"], ["owned-session"] * 2)
        self.assertEqual(self.namespace["positive_read_decisions"], ["approved"] * 2)

    def test_fixture_approval_is_confined_to_positive_read_and_owned_session(self):
        self.namespace["positive_read_pending"] = False
        self.assert_rejected(self.request())
        self.assertEqual(self.namespace["positive_read_decisions"], [])
        self.namespace["positive_read_pending"] = True
        for context in ({}, {"session_id": "other", "agentId": "owned-session"}):
            with self.subTest(context=context):
                self.assert_rejected(self.request(), context)
        self.assertEqual(self.namespace["permission_sessions"], ["owned-session", None, "other"])
        self.assertEqual(self.namespace["positive_read_decisions"], ["rejected"] * 2)

    def test_protected_outside_sibling_directory_and_traversal_paths_are_rejected(self):
        for path in (
            self.protected, self.root / "outside.txt", self.workspace / "other.txt",
            self.workspace, self.workspace / "readable.txt.extra",
            self.workspace / ".." / "workspace" / "readable.txt",
            self.workspace / ".." / "protected.txt", "readable.txt",
            str(self.fixture) + "/../readable.txt",
        ):
            with self.subTest(path=str(path)):
                self.assert_rejected(self.request(path=str(path)))

    def test_malformed_and_multiple_paths_are_not_reduced_to_one_allowed_path(self):
        for path in (
            None, 1, True, [], [str(self.fixture)],
            [str(self.fixture), str(self.protected)], {"path": str(self.fixture)},
            str(self.fixture) + "\0", str(self.fixture) + "\n" + str(self.protected),
        ):
            with self.subTest(path_type=type(path).__name__):
                self.assert_rejected(self.request(path=path))

    def test_unknown_permission_types_and_tool_arguments_cannot_authorize_read(self):
        from copilot.session_events import PermissionRequestWrite

        wire = {"kind": "read", "path": str(self.fixture), "agentId": "owned-session",
                "toolArgs": {"path": str(self.fixture)}}
        for request in (
            None, wire, SimpleNamespace(**wire),
            {**wire, "paths": [str(self.fixture), str(self.protected)]},
            PermissionRequestWrite.from_dict({
                "kind": "write", "intention": "Synthetic write", "fileName": str(self.fixture),
                "canOfferSessionApproval": False, "diff": "",
            }),
        ):
            with self.subTest(request_type=type(request).__name__):
                self.assert_rejected(request)

    def test_resolved_path_mismatch_bypass_and_managed_approval_are_rejected(self):
        for overrides in (
            {"resolved_path": str(self.protected)},
            {"resolved_path": [str(self.fixture), str(self.protected)]},
            {"managed_approval_required": True}, {"managed_approval_required": "false"},
            {"request_sandbox_bypass": True}, {"request_sandbox_bypass": 0},
            {"request_sandbox_bypass_reason": "approved"},
            {"sandbox_path_grant": {"path": str(self.fixture)}},
        ):
            with self.subTest(field=next(iter(overrides))):
                self.assert_rejected(self.request(**overrides))

    def test_symlink_alias_and_fixture_symlink_replacement_are_rejected(self):
        # Model canonical resolution rather than require Windows symlink privileges.
        with patch.object(Path, "resolve", return_value=self.fixture):
            self.assert_rejected(self.request(path=str(self.workspace / "alias.txt")))
        with patch.object(Path, "resolve", return_value=self.protected):
            self.assert_rejected(self.request())

    def test_missing_directory_or_unresolvable_fixture_is_rejected(self):
        self.fixture.unlink()
        self.assert_rejected(self.request())
        self.fixture.mkdir()
        self.assert_rejected(self.request())
        for error in (PermissionError("synthetic"), RuntimeError("symlink loop")):
            with self.subTest(error_type=type(error).__name__):
                with patch.object(Path, "resolve", side_effect=error):
                    self.assert_rejected(self.request())

    def test_auto_approval_and_bypass_remain_disabled_without_extra_path_grants(self):
        calls = [node for node in ast.walk(self.tree) if isinstance(node, ast.Call)]
        config = next(node for node in calls
                      if ast.unparse(node.func) == "PermissionsConfigureParams")
        params = eval(compile(ast.Expression(config), native.__file__, "eval"), {
            **self.namespace, "workspace": self.workspace,
        })
        self.assertEqual(params.to_dict(), {
            "approveAllReadPermissionRequests": False, "approveAllToolPermissionRequests": False,
            "paths": {"unrestricted": False, "includeTempDirectory": False,
                      "workspacePath": str(self.workspace)},
        })
        sandbox = next(node for node in calls if ast.unparse(node.func) == "SandboxConfig")
        policy = eval(compile(ast.Expression(sandbox), native.__file__, "eval"), {
            **self.namespace, "root": self.root,
        })
        self.assertEqual(policy.to_dict(), {
            "enabled": True, "allowBypass": False, "allowDevToolAccess": False,
            "userPolicy": {
                "filesystem": {"deniedPaths": [str(self.root / "protected")]},
                "network": {"allowOutbound": False, "allowLocalNetwork": False},
            },
        })

    def test_positive_read_window_closes_before_protected_read_even_on_error(self):
        body = next(node for node in self.tree.body[0].body if isinstance(node, ast.Try)).body
        window = next(node for node in body if isinstance(node, ast.Try) and node.finalbody)
        self.assertIn("name='view', arguments={'path': str(readable_path)}", ast.unparse(window))
        for node in window.finalbody:
            exec(compile(ast.Module(body=[node], type_ignores=[]), native.__file__, "exec"),
                 self.namespace)
        self.assertFalse(self.namespace["positive_read_pending"])
        calls = [node for node in ast.walk(self.tree) if isinstance(node, ast.Call)]
        positive = next(node for node in calls if ast.unparse(node.func) == "require_positive_read")
        protected = next(node for node in calls if ast.unparse(node.func) == "ToolsExecuteRequest"
                         and "str(protected)" in ast.unparse(node))
        self.assertLess(window.end_lineno, positive.lineno)
        self.assertLess(positive.lineno, protected.lineno)
        self.assertIn("require_denial(denied, report)", ast.unparse(self.tree))
        self.assertIn("'protected_canary_leaked'", ast.unparse(self.tree))
        self.assertIn("permission_sessions and all((value == session_id",
                      ast.unparse(self.tree))

    def test_protected_observations_do_not_reuse_prior_positive_approval(self):
        self.permission(self.request(), self.context)
        observation = self.namespace["protected_observation"]
        self.assertEqual(observation, {
            "callback": "not_requested", "callback_session": "not_requested",
        })
        self.namespace["positive_read_pending"] = False
        self.namespace["protected_read_pending"] = True
        self.assert_rejected(self.request(path=str(self.protected)))
        self.assertEqual(observation, {
            "callback": "rejected_exact_read", "callback_session": "match",
        })
        self.assertEqual(self.namespace["positive_read_decisions"], ["approved"])

    def test_unknown_protected_callbacks_are_rejected_and_not_labelled_exact_reads(self):
        self.namespace["positive_read_pending"] = False
        self.namespace["protected_read_pending"] = True
        for request in (None, {"kind": "read", "path": str(self.protected)},
                        self.request(), self.request(path=str(self.protected),
                                                     resolved_path=str(self.fixture))):
            with self.subTest(request_type=type(request).__name__):
                self.assert_rejected(request)
                self.assertEqual(self.namespace["protected_observation"]["callback"],
                                 "rejected_other")
        self.assert_rejected(self.request(path=str(self.protected)))
        self.assertEqual(self.namespace["protected_observation"]["callback"], "mixed")

    def test_protected_callback_session_mismatch_is_sticky_and_window_scoped(self):
        self.namespace["positive_read_pending"] = False
        self.namespace["protected_read_pending"] = True
        self.assert_rejected(self.request(path=str(self.protected)), {})
        self.assert_rejected(self.request(path=str(self.protected)))
        self.assertEqual(self.namespace["protected_observation"]["callback_session"], "mismatch")
        self.namespace["protected_read_pending"] = False
        self.assert_rejected(None)
        self.assertEqual(self.namespace["protected_observation"]["callback"], "rejected_exact_read")


class NativeProtectedReadTests(unittest.TestCase):
    """Execute the actual probe statements with RPC stubs, never an event loop."""

    @classmethod
    def setUpClass(cls):
        tree = ast.parse(inspect.getsource(native.native_checks))
        # Match the existing synchronous callback/handler contract technique.
        # Strip only await syntax; all branches, checks and finally blocks stay.
        class Synchronous(ast.NodeTransformer):
            def visit_Await(self, node):
                return self.visit(node.value)

            def visit_AsyncFunctionDef(self, node):
                return ast.FunctionDef(
                    name=node.name, args=node.args, body=[self.visit(x) for x in node.body],
                    decorator_list=[], returns=node.returns, type_comment=None,
                )

        inspector = next(node for node in tree.body[0].body
                         if isinstance(node, ast.AsyncFunctionDef)
                         and node.name == "inspect_protected_policy")
        probe = next(node for node in ast.walk(tree) if isinstance(node, ast.Try)
                     and any(isinstance(child, ast.Call)
                             and ast.unparse(child.func) == "protected_canary_present"
                             for statement in node.body for child in ast.walk(statement))
                     and any(isinstance(child, ast.Call)
                             and ast.unparse(child.func) == "inspect_protected_policy"
                             for handler in node.handlers for child in ast.walk(handler)))
        cls.probe = compile(ast.fix_missing_locations(Synchronous().visit(
            ast.Module(body=[probe], type_ignores=[]))), native.__file__, "exec")
        cls.inspector = compile(ast.fix_missing_locations(Synchronous().visit(
            ast.Module(body=[inspector], type_ignores=[]))), native.__file__, "exec")
        cls.imports = [node for node in tree.body[0].body
                       if isinstance(node, ast.ImportFrom) and node.module.startswith("copilot")]

    def setUp(self):
        from copilot.rpc import PermissionPathsAllowedCheckResult, SandboxEnforcementStatus

        self.observation = {
            "callback": "not_requested", "callback_session": "not_requested",
            "marker": "unknown", "text_shape": "unknown",
            "allowed_directory": "not_run", "sandbox_blocked": "not_run",
        }
        self.report = {"check": "native_file_denial", "protected_read": self.observation}
        self.execute = Mock()
        self.path_check = Mock(return_value=PermissionPathsAllowedCheckResult(allowed=False))
        self.sandbox_check = Mock(return_value=SandboxEnforcementStatus(blocked=False, required=False))
        self.namespace = {
            **vars(native), "bounded": lambda result: result,
            "protected_completion": native._ProtectedReadCompletion(),
            "session_id": "owned-session", "permission_sessions": ["owned-session"],
            "protected_read_pending": True, "protected_marker": "synthetic-protected-canary",
            "root": Path("/synthetic"),
            "protected": Path("/synthetic/protected/control-plane.txt"),
            "protected_observation": self.observation, "report": self.report,
            "session": SimpleNamespace(rpc=SimpleNamespace(
                tools=SimpleNamespace(execute=self.execute),
                permissions=SimpleNamespace(paths=SimpleNamespace(
                    is_path_within_allowed_directories=self.path_check)),
                sandbox=SimpleNamespace(get_enforcement_status=self.sandbox_check),
            )),
        }
        exec(compile(ast.Module(body=self.imports, type_ignores=[]), native.__file__, "exec"),
             self.namespace)
        exec(self.inspector, self.namespace)

    def run_probe(self, result):
        self.execute.return_value = result
        exec(self.probe, self.namespace)

    def test_leaked_canary_takes_priority_over_every_result_kind(self):
        from copilot.rpc import ToolResultExpanded

        for kind in native.TOOL_RESULT_KINDS:
            wire = {"resultType": kind, "textResultForLlm": self.namespace["protected_marker"]}
            for result in (wire, ToolResultExpanded.from_dict(wire)):
                with self.subTest(kind=kind, shape=type(result).__name__):
                    with self.assertRaisesRegex(native.CheckFailure, "^protected_canary_leaked$"):
                        self.run_probe(result)
                    self.assertEqual(self.observation["marker"], "present")
                    self.assertEqual(self.observation["text_shape"], "string")
                    self.assertFalse(self.namespace["protected_read_pending"])
                    self.assertNotIn("denial_result", self.report)

    def test_canary_in_structured_output_is_not_hidden_by_safe_text(self):
        wire = {"resultType": "denied", "textResultForLlm": "",
                "structuredContent": {"content": self.namespace["protected_marker"]}}
        with self.assertRaisesRegex(native.CheckFailure, "^protected_canary_leaked$"):
            self.run_probe(wire)

    def test_generic_failure_stays_unknown_with_complete_safe_policy_diagnostic(self):
        with self.assertRaisesRegex(native.CheckFailure, "^explicit_native_denial_required$"):
            self.run_probe({"resultType": "failure", "textResultForLlm": "sensitive-native-error"})
        self.assertEqual(self.observation, {
            "callback": "not_requested", "callback_session": "not_requested",
            "marker": "absent", "text_shape": "string",
            "allowed_directory": "no", "sandbox_blocked": "no",
        })
        self.assertEqual(self.report["denial_result"], {"shape": "mapping", "kind": "failure"})
        self.assertEqual(self.path_check.call_args.args[0].to_dict(), {
            "path": str(self.namespace["protected"]),
        })
        self.sandbox_check.assert_called_once_with()
        # Plain synthetic error text is now an additive diagnostic, not denial
        # evidence. No arbitrary result fields become public with it.
        self.assertEqual(self.report["protected_error"], {
            "source": "textResultForLlm", "text": "sensitive-native-error",
        })

    def test_error_field_canary_precedes_kind_and_capture_even_beyond_text_limit(self):
        from copilot.rpc import ToolResultExpanded

        for kind in native.TOOL_RESULT_KINDS:
            for prefix in ("", "x" * native.ERROR_TEXT_LIMIT, "x" * native.ERROR_INPUT_LIMIT):
                wire = {"resultType": kind, "textResultForLlm": "Access denied",
                        "error": prefix + self.namespace["protected_marker"]}
                for result in (wire, ToolResultExpanded.from_dict(wire)):
                    with self.subTest(kind=kind, prefix_length=len(prefix),
                                      shape=type(result).__name__):
                        with self.assertRaisesRegex(native.CheckFailure, "^protected_canary_leaked$"):
                            self.run_probe(result)
                        self.assertNotIn("protected_error", self.report)
                        self.assertNotIn("denial_result", self.report)

    def test_direct_generic_error_is_explained_but_never_accepted_as_denial(self):
        with self.assertRaisesRegex(native.CheckFailure, "^explicit_native_denial_required$"):
            self.run_probe({
                "resultType": "failure", "textResultForLlm": "unused synthetic text",
                "error": "Access denied: filesystem policy rejected the synthetic read",
                "structuredContent": "not-for-output", "sessionLog": "not-for-output",
                "toolTelemetry": {"private": "not-for-output"},
            })
        self.assertEqual(self.report["protected_error"], {
            "source": "error",
            "text": "Access denied: filesystem policy rejected the synthetic read",
        })
        self.assertNotIn("not-for-output", json.dumps(self.report))
        self.assertEqual(self.report["denial_result"]["kind"], "failure")

    def test_non_generic_results_and_rpc_exceptions_never_supply_error_text(self):
        for kind in ("denied", "rejected"):
            self.run_probe({"resultType": kind, "textResultForLlm": "",
                            "error": "not-for-output"})
            self.assertNotIn("protected_error", self.report)
        for kind in ("success", "timeout", "unrecognized"):
            with self.assertRaises(native.CheckFailure):
                self.run_probe({"resultType": kind, "error": "not-for-output"})
            self.assertNotIn("protected_error", self.report)
        self.execute.side_effect = RuntimeError("not-for-output")
        with self.assertRaises(RuntimeError):
            self.run_probe(None)
        self.assertNotIn("protected_error", self.report)

    def test_callback_rejection_and_policy_flags_cannot_turn_failure_into_pass(self):
        self.observation.update(callback="rejected_exact_read", callback_session="match")
        self.sandbox_check.return_value = SimpleNamespace(blocked=True)
        with self.assertRaisesRegex(native.CheckFailure, "^explicit_native_denial_required$"):
            self.run_probe({"resultType": "failure", "textResultForLlm": ""})
        self.assertEqual(self.observation["sandbox_blocked"], "yes")

    def test_explicit_denial_without_canary_still_passes_without_extra_inspections(self):
        from copilot.rpc import ToolResultExpanded

        for kind in ("denied", "rejected"):
            wire = {"resultType": kind, "textResultForLlm": ""}
            for result in (wire, ToolResultExpanded.from_dict(wire)):
                with self.subTest(kind=kind, shape=type(result).__name__):
                    self.run_probe(result)
                    self.assertEqual(self.observation["marker"], "absent")
        self.path_check.assert_not_called()
        self.sandbox_check.assert_not_called()

    def test_malformed_timeout_success_and_unknown_results_remain_failures(self):
        for result in (None, [], {}, {"result": {"resultType": "denied"}},
                       {"resultType": "success"}, {"resultType": "timeout"},
                       {"resultType": ["denied"]}, {"resultType": "sensitive-code"},
                       {"resultType": "denied", "textResultForLlm": object()}):
            with self.subTest(result_type=type(result).__name__):
                with self.assertRaisesRegex(native.CheckFailure, "^explicit_native_denial_required$"):
                    self.run_probe(result)

    def test_policy_inspection_errors_never_replace_leak_or_native_failure(self):
        self.path_check.side_effect = TimeoutError("sensitive-error")
        self.sandbox_check.side_effect = RuntimeError("sensitive-error")
        with self.assertRaisesRegex(native.CheckFailure, "^protected_canary_leaked$"):
            self.run_probe({"resultType": "failure",
                            "textResultForLlm": self.namespace["protected_marker"]})
        self.assertEqual(self.observation["allowed_directory"], "timeout")
        self.assertEqual(self.observation["sandbox_blocked"], "operation_failed")
        self.assertNotIn("sensitive", json.dumps(self.report))

    def test_malformed_policy_booleans_are_unknown_not_denial_evidence(self):
        for value in (None, 0, 1, "false", [], {}):
            with self.subTest(value_type=type(value).__name__):
                self.path_check.return_value = SimpleNamespace(allowed=value)
                self.sandbox_check.return_value = SimpleNamespace(blocked=value)
                with self.assertRaises(native.CheckFailure):
                    self.run_probe({"resultType": "failure", "textResultForLlm": ""})
                self.assertEqual(self.observation["allowed_directory"], "unknown")
                self.assertEqual(self.observation["sandbox_blocked"], "unknown")

    def test_native_rpc_errors_close_window_and_keep_original_error_for_classification(self):
        for error in (TimeoutError("synthetic"), RuntimeError("authentication required"),
                      RuntimeError("synthetic-native-error")):
            with self.subTest(error_type=type(error).__name__):
                self.execute.side_effect = error
                self.namespace["protected_read_pending"] = True
                with self.assertRaises(type(error)) as caught:
                    self.run_probe(None)
                self.assertIs(caught.exception, error)
                self.assertFalse(self.namespace["protected_read_pending"])
                self.assertEqual(self.observation["marker"], "unknown")

    def test_outer_report_retains_only_bounded_protected_diagnostics(self):
        for reason in ("explicit_native_denial_required", "protected_canary_leaked",
                       "timeout", "authentication_required", "operation_failed"):
            with self.subTest(reason=reason):
                candidate = {**self.report, "reason": reason, "protected_read": {
                    **self.observation, "marker": "present", "text_shape": "string",
                    "allowed_directory": "no", "sandbox_blocked": "yes",
                    "raw": "sensitive-result", "path": "sensitive-path",
                }}
                safe = native.safe_failure_report(json.dumps(candidate))
                self.assertEqual(safe["protected_read"], {
                    **self.observation, "marker": "present", "text_shape": "string",
                    "allowed_directory": "no", "sandbox_blocked": "yes",
                })
                self.assertNotIn("sensitive", json.dumps(safe))

    def test_outer_report_rejects_bad_diagnostic_values_and_wrong_context(self):
        for value in (True, 1, None, [], {}, "sensitive-value"):
            with self.subTest(value_type=type(value).__name__):
                safe = native.safe_failure_report(json.dumps({
                    **self.report, "reason": "explicit_native_denial_required",
                    "protected_read": dict.fromkeys(self.observation, value),
                }))
                self.assertEqual(safe["protected_read"], {})
        for check, reason in (("native_toolset", "explicit_native_denial_required"),
                              ("bounded_cleanup", "operation_failed"),
                              ("native_file_denial", "native_file_positive_control_failed"),
                              ("native_file_denial", "sensitive-reason")):
            with self.subTest(check=check, reason=reason):
                safe = native.safe_failure_report(json.dumps({
                    "check": check, "reason": reason, "protected_read": self.observation,
                }))
                self.assertNotIn("protected_read", safe)

    def test_explicit_denial_cannot_hide_missing_or_wrong_callback_session(self):
        for sessions in ([], ["other-session"], ["owned-session", None]):
            with self.subTest(sessions=sessions):
                self.namespace["permission_sessions"] = sessions
                with self.assertRaisesRegex(native.CheckFailure, "^permission_session_mismatch$"):
                    self.run_probe({"resultType": "denied", "textResultForLlm": ""})

    def test_correlated_sandbox_remediation_does_not_accept_generic_wire_failure(self):
        completion = self.namespace["protected_completion"]

        def execute(request):
            self.assertEqual(request.tool_call_id, native.PROTECTED_READ_CALL_ID)
            completion.observe(completion_event(
                error={"message": "sensitive", "code": "sensitive",
                       "remediation": "review_sandbox_policy"}))
            return {"resultType": "failure", "textResultForLlm": ""}

        self.execute.side_effect = execute
        with self.assertRaisesRegex(native.CheckFailure, "^explicit_native_denial_required$"):
            self.run_probe(None)
        self.assertEqual(self.report["denial_result"]["kind"], "failure")
        self.assertEqual(self.report["protected_completion"]["correlation"], "match")
        self.assertEqual(self.report["protected_completion"]["remediation"], "review_sandbox_policy")
        self.assertFalse(completion.active)

    def test_completion_during_existing_inspection_is_captured_then_snapshot_is_frozen(self):
        completion = self.namespace["protected_completion"]

        def inspect_path(_request):
            completion.observe(completion_event(
                error={"message": "sensitive", "remediation": "review_sandbox_policy"}))
            return SimpleNamespace(allowed=False)

        self.path_check.side_effect = inspect_path
        with self.assertRaises(native.CheckFailure):
            self.run_probe({"resultType": "failure"})
        snapshot = dict(self.report["protected_completion"])
        completion.observe(completion_event(native.POSITIVE_READ_CALL_ID, success=True))
        completion.observe(completion_event(success=True))
        self.assertFalse(completion.active)
        self.assertEqual(self.report["protected_completion"], snapshot)
        self.assertIsNot(self.report["protected_completion"], completion.diagnostic)
        self.assertEqual(snapshot["correlation"], "match")
        self.assertIs(snapshot["success"], False)

    def test_rpc_timeout_with_no_completion_reports_unknown_not_denial(self):
        self.execute.side_effect = TimeoutError("sensitive")
        with self.assertRaises(TimeoutError):
            self.run_probe(None)
        self.assertEqual(self.report["protected_completion"], {
            "event": "not_seen", "correlation": "absent", "success": "unknown",
            "error": "unknown", "code": "unknown", "remediation": "absent",
        })
        self.assertFalse(self.namespace["protected_completion"].active)
        self.assertNotIn("sensitive", json.dumps(self.report))

    def test_late_positive_completion_during_probe_does_not_supply_protected_error(self):
        completion = self.namespace["protected_completion"]

        def execute(_request):
            completion.observe(completion_event(
                native.POSITIVE_READ_CALL_ID, error={"message": "sensitive",
                                                    "remediation": "sign_in"}))
            return {"resultType": "failure"}

        self.execute.side_effect = execute
        with self.assertRaises(native.CheckFailure):
            self.run_probe(None)
        self.assertEqual(self.report["protected_completion"]["correlation"], "mismatch")
        self.assertEqual(self.report["protected_completion"]["error"], "unknown")
        self.assertEqual(self.report["protected_completion"]["remediation"], "absent")

    def test_completion_metadata_never_changes_leak_priority_for_any_result_kind(self):
        completion = self.namespace["protected_completion"]

        def execute(_request):
            completion.observe(completion_event(
                error={"message": "sensitive", "remediation": "review_sandbox_policy"}))
            return {"resultType": kind, "textResultForLlm": self.namespace["protected_marker"]}

        self.execute.side_effect = execute
        for kind in native.TOOL_RESULT_KINDS:
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(native.CheckFailure, "^protected_canary_leaked$"):
                    self.run_probe(None)
                self.assertNotIn("denial_result", self.report)
                self.assertEqual(self.report["protected_completion"]["correlation"], "match")

    def test_successful_probe_does_not_add_completion_diagnostics(self):
        completion = self.namespace["protected_completion"]

        def execute(_request):
            completion.observe(completion_event(success=False))
            return {"resultType": "denied", "textResultForLlm": ""}

        self.execute.side_effect = execute
        self.run_probe(None)
        self.assertNotIn("protected_completion", self.report)
        self.assertFalse(completion.active)
        self.path_check.assert_not_called()
        self.sandbox_check.assert_not_called()


class NativePositiveReadDiagnosticTests(unittest.TestCase):
    def test_real_marker_is_required_in_wire_or_sdk_result_without_reporting_content(self):
        from copilot.rpc import ToolResultExpanded

        wire = {"resultType": "success", "textResultForLlm": "native-readable-canary"}
        for result in (wire, ToolResultExpanded.from_dict(wire)):
            with self.subTest(result_type=type(result).__name__):
                report = {}
                native.require_positive_read(result, ["approved"], report)
                self.assertEqual(report, {})

    def test_marker_absence_fails_with_fixed_kind_and_callback_decision_only(self):
        for kind, expected in (("rejected", "rejected"), ("success", "success"),
                               ("synthetic-sensitive-error", "unrecognized")):
            for decisions, permission in (([], "not_requested"), (["approved"], "approved"),
                                           (["rejected"], "rejected"),
                                           (["approved", "rejected"], "mixed")):
                with self.subTest(kind=expected, permission=permission):
                    report = {"check": "native_file_denial",
                              "reason": "native_file_positive_control_failed"}
                    with self.assertRaisesRegex(native.CheckFailure,
                                                "^native_file_positive_control_failed$"):
                        native.require_positive_read({
                            "resultType": kind, "textResultForLlm": "synthetic-sensitive-content",
                        }, decisions, report)
                    safe = native.safe_failure_report(json.dumps(report))
                    self.assertEqual(safe["positive_read"], {"kind": expected, "permission": permission})
                    self.assertNotIn("sensitive", json.dumps(safe))

    def test_missing_result_kind_is_reported_as_absent_not_denial(self):
        report = {}
        with self.assertRaises(native.CheckFailure):
            native.require_positive_read({}, [], report)
        self.assertEqual(report, {"positive_read": {"kind": "absent", "permission": "not_requested"}})

    def test_outer_report_filters_positive_read_keys_values_and_context(self):
        for check, reason in (("native_file_denial", "native_file_positive_control_failed"),
                              ("native_file_denial", "protected_canary_leaked"),
                              ("native_toolset", "native_file_positive_control_failed")):
            with self.subTest(check=check, reason=reason):
                report = native.safe_failure_report(json.dumps({
                    "check": check, "reason": reason, "positive_read": {
                        "kind": "rejected", "permission": "synthetic-sensitive-value",
                        "result": "synthetic-sensitive-content", "path": "synthetic-sensitive-path",
                    },
                }))
                self.assertEqual(report.get("positive_read"),
                                 {"kind": "rejected"} if reason == "native_file_positive_control_failed"
                                 and check == "native_file_denial" else None)
                self.assertNotIn("sensitive", json.dumps(report))


class NativeFileFailureDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Execute the real exception handler with synthetic errors only. No
        # coroutine, event loop or SDK runtime is needed for this report contract.
        tree = ast.parse(inspect.getsource(native.native_checks))
        checks = next(node for node in tree.body[0].body if isinstance(node, ast.Try))
        handler = ast.Try(
            body=ast.parse("raise error").body, handlers=checks.handlers,
            orelse=[], finalbody=[],
        )
        cls.handler = compile(
            ast.fix_missing_locations(ast.Module(body=[handler], type_ignores=[])),
            native.__file__, "exec",
        )

    def setUp(self):
        self.report = {
            "status": "fail", "check": "native_file_denial",
            "sdk": native.SDK_VERSION, "publisher_cli": native.CLI_VERSION,
            "runtime": native.CLI_VERSION, "protocol": 3,
            "passed": ["runtime_identity", "session_startup", "native_toolset",
                       "plan_refusal_and_exit_only"],
        }

    def test_protected_leak_assertion_precedes_result_kind_assertion(self):
        # Also runs against the original driver: its kind-first order hides leaks.
        tree = ast.parse(inspect.getsource(native.native_checks))
        checks = sorted((
            node for node in ast.walk(tree) if isinstance(node, ast.Call)
            and ((ast.unparse(node.func) == "require_denial"
                  and ast.unparse(node.args[0]) == "denied")
                 or (ast.unparse(node.func) == "require"
                     and ast.literal_eval(node.args[1]) == "protected_canary_leaked"))
        ), key=lambda node: node.lineno)
        self.assertEqual(len(checks), 2)
        statements = ast.fix_missing_locations(ast.Module(
            body=[ast.Expr(value=node) for node in checks], type_ignores=[]))
        for kind in native.TOOL_RESULT_KINDS:
            with self.subTest(kind=kind):
                namespace = {
                    **vars(native), "report": {}, "protected_observation": {},
                    "protected_marker": "synthetic-protected-canary",
                    "protected": Mock(read_text=Mock(return_value="synthetic-protected-canary")),
                    "denied": {"resultType": kind, "textResultForLlm": "synthetic-protected-canary"},
                }
                with self.assertRaisesRegex(native.CheckFailure, "^protected_canary_leaked$"):
                    exec(compile(statements, native.__file__, "exec"), namespace)

    def test_file_failure_codes_survive_inner_and_outer_reports(self):
        for code in (
            "native_file_positive_control_failed",
            "protected_canary_leaked",
            "permission_session_mismatch",
        ):
            with self.subTest(code=code):
                report = dict(self.report)
                namespace = {**vars(native), "report": report, "error": native.CheckFailure(code)}
                exec(self.handler, namespace)
                process = Mock(pid=12345, returncode=1)
                process.communicate.return_value = (json.dumps({
                    **report, "error": "synthetic-sensitive-error",
                    "result": {"textResultForLlm": "synthetic-sensitive-file-content"},
                    "path": "/synthetic-sensitive-path", "stdout": "synthetic-sensitive-output",
                    "denial_result": {"kind": "failure"}, "missing_tools": ["task"],
                }), None)
                with patch.object(native.subprocess, "Popen", return_value=process):
                    with patch.object(native, "kill_owned_group") as kill:
                        with redirect_stdout(io.StringIO()) as output:
                            status = native.run_bounded(Path("/synthetic/runtime"))
                expected = {**self.report, "reason": code}
                self.assertEqual(report, expected)
                self.assertEqual(status, 1)
                self.assertEqual(json.loads(output.getvalue()), expected)
                self.assertNotIn("sensitive", output.getvalue())
                kill.assert_called_once_with(process)

    def test_unknown_error_text_is_not_printed_by_inner_or_outer_reports(self):
        for error, reason in (
            (native.CheckFailure("ghp_synthetic_secret_not_a_token"), "assertion_failed"),
            (RuntimeError("ghp_synthetic_secret_not_a_token"), "operation_failed"),
        ):
            with self.subTest(error_type=type(error).__name__):
                report = dict(self.report)
                namespace = {**vars(native), "report": report, "error": error}
                with redirect_stdout(io.StringIO()) as output:
                    exec(self.handler, namespace)
                    self.assertEqual(output.getvalue(), "")
                    process = Mock(pid=12345, returncode=1)
                    process.communicate.return_value = (json.dumps(report), None)
                    with patch.object(native.subprocess, "Popen", return_value=process):
                        with patch.object(native, "kill_owned_group"):
                            status = native.run_bounded(Path("/synthetic/runtime"))
                expected = {**self.report, "reason": reason}
                self.assertEqual(report, expected)
                self.assertEqual(status, 1)
                self.assertEqual(json.loads(output.getvalue()), expected)
                self.assertNotIn("ghp_synthetic_secret_not_a_token", output.getvalue())

    def test_outer_report_rejects_unknown_file_failure_reason_and_raw_result(self):
        report = native.safe_failure_report(json.dumps({
            **self.report, "reason": "ghp_synthetic_secret_not_a_token",
            "error": "synthetic-sensitive-error",
            "result": {"textResultForLlm": "synthetic-sensitive-file-content"},
        }))
        self.assertEqual(report, self.report)


class NativeDenialDiagnosticTests(unittest.TestCase):
    def test_documented_sdk_kinds_and_wire_objects_keep_explicit_denial_semantics(self):
        from copilot.rpc import ToolResultExpanded, ToolResultType

        self.assertEqual(native.metadata.version("github-copilot-sdk"), native.SDK_VERSION)
        self.assertEqual(tuple(kind.value for kind in ToolResultType), native.TOOL_RESULT_KINDS)
        for kind in ToolResultType:
            wire = {"resultType": kind.value, "textResultForLlm": ""}
            for result, shape in ((wire, "mapping"),
                                  (ToolResultExpanded.from_dict(wire), "object")):
                with self.subTest(kind=kind, shape=shape):
                    report = {}
                    if kind in (ToolResultType.DENIED, ToolResultType.REJECTED):
                        native.require_denial(result, report)
                        self.assertEqual(report, {})
                    else:
                        with self.assertRaisesRegex(native.CheckFailure,
                                                    "^explicit_native_denial_required$"):
                            native.require_denial(result, report)
                        self.assertEqual(report["denial_result"],
                                         {"shape": shape, "kind": kind.value})

    def test_malformed_and_nested_results_are_not_guessed_as_denial(self):
        for result, shape, kind in (
            ({}, "mapping", "absent"),
            ({"result": {"resultType": "denied"}}, "mapping", "absent"),
            ({"result_type": "denied"}, "mapping", "absent"),
            ({"resultType": None}, "mapping", "unrecognized"),
            ({"resultType": ["denied"]}, "mapping", "unrecognized"),
            ({"resultType": {"value": "denied"}}, "mapping", "unrecognized"),
            ({"resultType": "tool_not_found"}, "mapping", "unrecognized"),
            ({"resultType": "authentication_required"}, "mapping", "unrecognized"),
            ({"resultType": "ghp_synthetic_secret_not_a_token"}, "mapping", "unrecognized"),
            (None, "other", "absent"), ([], "other", "absent"),
            ("ghp_synthetic_secret_not_a_token", "other", "absent"),
        ):
            with self.subTest(shape=shape, kind=kind):
                report = {}
                with self.assertRaisesRegex(native.CheckFailure, "^explicit_native_denial_required$"):
                    native.require_denial(result, report)
                self.assertEqual(report, {"denial_result": {"shape": shape, "kind": kind}})

    def test_canary_output_is_positive_evidence_even_when_result_claims_denial(self):
        from copilot.rpc import ToolResultExpanded

        with tempfile.TemporaryDirectory() as directory:
            canary = Path(directory) / "not-created"
            for kind in ("success", "failure", "denied", "rejected"):
                wire = {"resultType": kind, "textResultForLlm": native.SHELL_OUTPUT_MARKER}
                for result in (wire, ToolResultExpanded.from_dict(wire)):
                    with self.subTest(kind=kind, shape=type(result).__name__):
                        report = {}
                        with self.assertRaisesRegex(native.CheckFailure,
                                                    "^explicit_native_denial_required$"):
                            native.require_denial(result, report, shell_canary=canary)
                        self.assertEqual(report["denial_result"]["command_execution"], "observed")
                        self.assertEqual(report["denial_result"]["canary_file"], "absent")

    def test_created_canary_is_positive_evidence_without_returned_output(self):
        with tempfile.TemporaryDirectory() as directory:
            canary = Path(directory) / "created-by-test-not-shell"
            canary.write_text(native.SHELL_OUTPUT_MARKER, encoding="utf-8")
            report = {}
            with self.assertRaisesRegex(native.CheckFailure, "^explicit_native_denial_required$"):
                native.require_denial({"resultType": "denied"}, report, shell_canary=canary)
        self.assertEqual(report["denial_result"], {
            "shape": "mapping", "kind": "denied",
            "canary_file": "present", "command_execution": "observed",
        })

    def test_absent_canary_requires_explicit_denial_not_generic_failure_or_success(self):
        with tempfile.TemporaryDirectory() as directory:
            canary = Path(directory) / "not-created"
            for kind in native.TOOL_RESULT_KINDS:
                with self.subTest(kind=kind):
                    report = {}
                    result = {"resultType": kind, "textResultForLlm": ""}
                    if kind in ("denied", "rejected"):
                        native.require_denial(result, report, shell_canary=canary)
                        self.assertEqual(report, {})
                    else:
                        with self.assertRaises(native.CheckFailure):
                            native.require_denial(result, report, shell_canary=canary)
                        self.assertEqual(report["denial_result"]["canary_file"], "absent")
                        self.assertEqual(report["denial_result"]["command_execution"], "not_observed")

    def test_unreadable_canary_state_fails_closed_without_leaking_error(self):
        report = {}
        with patch.object(Path, "lstat", side_effect=PermissionError("synthetic-sensitive-path")):
            with self.assertRaisesRegex(native.CheckFailure, "^explicit_native_denial_required$"):
                native.require_denial({"resultType": "denied", "textResultForLlm": ""},
                                      report, shell_canary=Path("/synthetic"))
        self.assertEqual(report["denial_result"], {
            "shape": "mapping", "kind": "denied",
            "canary_file": "unknown", "command_execution": "unknown",
        })

    def test_missing_or_malformed_output_leaves_execution_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            for text in (None, [native.SHELL_OUTPUT_MARKER], {"stdout": native.SHELL_OUTPUT_MARKER}):
                with self.subTest(text_type=type(text).__name__):
                    report = {}
                    with self.assertRaises(native.CheckFailure):
                        native.require_denial(
                            {"resultType": "failure", "textResultForLlm": text},
                            report, shell_canary=Path(directory) / "absent",
                        )
                    self.assertEqual(report["denial_result"]["command_execution"], "unknown")

    def test_echoed_request_and_error_text_are_not_execution_evidence(self):
        import shlex

        tree = ast.parse(inspect.getsource(native.native_checks))
        assignments = {node.targets[0].id: node.value for node in ast.walk(tree)
                       if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)}
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            canary = eval(compile(ast.Expression(assignments["shell_canary"]), native.__file__, "eval"),
                          {"workspace": workspace, "uuid": native.uuid})
            command = eval(compile(ast.Expression(assignments["shell_command"]), native.__file__, "eval"),
                           {"shell_canary": canary, "shlex": shlex})
            self.assertEqual(canary.parent, workspace)
            self.assertRegex(canary.name, r"^\.native-shell-[0-9a-f]{32}$")
            self.assertFalse(canary.exists())
            self.assertEqual(command, "printf '%s%s' native-unexpected- shell > "
                             + shlex.quote(str(canary)) + "; printf '%s%s' native-unexpected- shell")
            self.assertNotIn(native.SHELL_OUTPUT_MARKER, command)
            # Parse only. Never execute the command, a coroutine, or an SDK client.
            self.assertIn("require_denial(shell_denied, report, shell_canary=shell_canary)",
                          ast.unparse(tree))
            self.assertIn("ToolsExecuteRequest(name='bash', arguments={'command': shell_command})",
                          ast.unparse(tree))
            report = {}
            with self.assertRaises(native.CheckFailure):
                native.require_denial({
                    "resultType": "failure", "textResultForLlm": command,
                    "error": native.SHELL_OUTPUT_MARKER, "sessionLog": native.SHELL_OUTPUT_MARKER,
                }, report, shell_canary=canary)
        self.assertEqual(report["denial_result"]["command_execution"], "not_observed")

    def test_failure_crosses_outer_boundary_with_only_fixed_labels_and_prior_checks(self):
        report = {
            "status": "fail", "check": "native_toolset", "reason": "explicit_native_denial_required",
            "sdk": native.SDK_VERSION, "publisher_cli": native.CLI_VERSION,
            "runtime": native.CLI_VERSION, "protocol": 3,
            "passed": ["runtime_identity", "session_startup"],
        }
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(native.CheckFailure):
                native.require_denial({
                    "resultType": "failure", "textResultForLlm": "ghp_synthetic_secret_not_a_token",
                    "error": "synthetic-sensitive-path", "stdout": "synthetic-sensitive-output",
                }, report, shell_canary=Path(directory) / "absent")
        expected = {**report, "denial_result": {
            "shape": "mapping", "kind": "failure",
            "canary_file": "absent", "command_execution": "not_observed",
        }}
        process = Mock(pid=12345, returncode=1)
        process.communicate.return_value = (json.dumps(report), None)
        with patch.object(native.subprocess, "Popen", return_value=process):
            with patch.object(native, "kill_owned_group") as kill:
                with redirect_stdout(io.StringIO()) as output:
                    status = native.run_bounded(Path("/synthetic/runtime"))
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(output.getvalue()), expected)
        kill.assert_called_once_with(process)

    def test_outer_boundary_filters_diagnostic_keys_values_types_and_context(self):
        for check, reason, expected in (
            ("native_toolset", "explicit_native_denial_required",
             {"shape": "mapping", "kind": "unrecognized", "canary_file": "absent"}),
            ("native_file_denial", "explicit_native_denial_required",
             {"shape": "mapping", "kind": "unrecognized"}),
            ("bounded_cleanup", "operation_failed", None),
            ("native_toolset", "native_tools_missing", None),
        ):
            for execution in ("ghp_synthetic_secret_not_a_token", True, None, ["observed"], {"x": 1}):
                with self.subTest(check=check, execution_type=type(execution).__name__):
                    report = native.safe_failure_report(json.dumps({
                        "check": check, "reason": reason, "passed": ["runtime_identity"],
                        "denial_result": {
                            "shape": "mapping", "kind": "unrecognized", "canary_file": "absent",
                            "command_execution": execution, "raw": "synthetic-sensitive-text",
                        },
                    }))
                    self.assertEqual(report.get("denial_result"), expected)
                    self.assertEqual(report["passed"], ["runtime_identity"])
        for diagnostic in (None, [], "synthetic-sensitive-text", 1):
            report = native.safe_failure_report(json.dumps({
                "check": "native_toolset", "reason": "explicit_native_denial_required",
                "denial_result": diagnostic,
            }))
            self.assertNotIn("denial_result", report)

    def test_file_denial_has_no_shell_evidence_and_keeps_original_failure(self):
        report = {"check": "native_file_denial", "reason": "explicit_native_denial_required"}
        with self.assertRaisesRegex(native.CheckFailure, "^explicit_native_denial_required$"):
            native.require_denial({"resultType": "failure"}, report)
        self.assertEqual(native.safe_failure_report(json.dumps(report)), {
            "status": "fail", "check": "native_file_denial",
            "reason": "explicit_native_denial_required", "passed": [],
            "denial_result": {"shape": "mapping", "kind": "failure"},
        })

    def test_success_stdout_still_excludes_denial_diagnostics(self):
        report = {
            "status": "pass", "check": "bounded_cleanup",
            "sdk": native.SDK_VERSION, "publisher_cli": native.CLI_VERSION,
            "runtime": native.CLI_VERSION, "protocol": 3, "passed": list(native.CHECKS),
        }
        process = Mock(pid=12345, returncode=0)
        process.communicate.return_value = (
            json.dumps({**report, "denial_result": {"kind": "failure"}}), None,
        )
        with patch.object(native.subprocess, "Popen", return_value=process):
            with patch.object(native, "kill_owned_group"):
                with redirect_stdout(io.StringIO()) as output:
                    status = native.run_bounded(Path("/synthetic/runtime"))
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue()), report)


class NativeToolDiagnosticTests(unittest.TestCase):
    def test_complete_required_inventory_adds_no_diagnostic(self):
        report = {}
        native.require_native_tools(set(native.REQUIRED_NATIVE_TOOLS), report)
        self.assertEqual(report, {})

    def test_success_stdout_shape_excludes_failure_diagnostics(self):
        report = {
            "status": "pass", "check": "bounded_cleanup",
            "sdk": native.SDK_VERSION, "publisher_cli": native.CLI_VERSION,
            "runtime": native.CLI_VERSION, "protocol": 3, "passed": list(native.CHECKS),
        }
        process = Mock(pid=12345, returncode=0)
        process.communicate.return_value = (
            json.dumps({**report, "missing_tools": ["task"]}), None,
        )
        with patch.object(native.subprocess, "Popen", return_value=process):
            with patch.object(native, "kill_owned_group"):
                with redirect_stdout(io.StringIO()) as output:
                    status = native.run_bounded(Path("/synthetic/runtime"))
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue()), report)

    def test_empty_inventory_still_requires_all_eight_capabilities(self):
        report = {}
        with self.assertRaisesRegex(native.CheckFailure, "^native_tools_missing$"):
            native.require_native_tools(set(), report)
        self.assertEqual(report["missing_tools"], [
            "ask_user", "exit_plan_mode", "list_agents", "read_agent",
            "skill", "task", "view", "write_agent",
        ])

    def test_missing_names_survive_outer_failure_with_identity_and_passed_checks(self):
        report = {
            "status": "fail", "check": "native_toolset", "reason": "native_tools_missing",
            "sdk": native.SDK_VERSION, "publisher_cli": native.CLI_VERSION,
            "runtime": native.CLI_VERSION, "protocol": 3,
            "passed": ["runtime_identity", "session_startup"],
        }
        names = set(native.REQUIRED_NATIVE_TOOLS) - {"skill", "exit_plan_mode"}
        names.add("synthetic-sensitive-runtime-name")
        with self.assertRaises(native.CheckFailure):
            native.require_native_tools(names, report)
        process = Mock(pid=12345, returncode=1)
        process.communicate.return_value = (json.dumps(report), None)
        with patch.object(native.subprocess, "Popen", return_value=process):
            with patch.object(native, "kill_owned_group") as kill:
                with redirect_stdout(io.StringIO()) as output:
                    status = native.run_bounded(Path("/synthetic/runtime"))
        self.assertEqual(status, 1)
        self.assertEqual(report["missing_tools"], ["exit_plan_mode", "skill"])
        self.assertEqual(json.loads(output.getvalue()), report)
        self.assertNotIn("sensitive", output.getvalue())
        kill.assert_called_once_with(process)

    def test_missing_names_are_allowlisted_sorted_and_deduplicated(self):
        report = native.safe_failure_report(json.dumps({
            "check": "native_toolset", "reason": "native_tools_missing",
            "missing_tools": [
                "skill", "synthetic-sensitive-name", "view", "skill", "ask_user",
                "prefix-task-suffix", None, {"task": "synthetic"}, ["task"],
            ],
        }))
        self.assertEqual(report, {
            "status": "fail", "check": "native_toolset", "reason": "native_tools_missing",
            "passed": [], "missing_tools": ["ask_user", "skill", "view"],
        })

    def test_non_list_diagnostic_does_not_infer_names_or_lose_passed_checks(self):
        for missing in (None, 1, "task skill", {"task": True}):
            with self.subTest(missing=missing):
                report = native.safe_failure_report(json.dumps({
                    "check": "native_toolset", "reason": "native_tools_missing",
                    "missing_tools": missing, "passed": ["runtime_identity"],
                }))
                self.assertEqual(report, {
                    "status": "fail", "check": "native_toolset",
                    "reason": "native_tools_missing", "passed": ["runtime_identity"],
                })

    def test_diagnostic_is_omitted_for_other_stages_or_reasons(self):
        for check, reason in (
            ("bounded_cleanup", "operation_failed"),
            ("session_startup", "native_tools_missing"),
            ("native_toolset", "operation_failed"),
        ):
            with self.subTest(check=check, reason=reason):
                report = native.safe_failure_report(json.dumps({
                    "check": check, "reason": reason, "missing_tools": ["task"],
                }))
                self.assertEqual(report, {
                    "status": "fail", "check": check, "reason": reason, "passed": [],
                })

    def test_diagnostic_cannot_make_malformed_child_report_valid(self):
        for candidate in (None, [], "task", {"missing_tools": ["task"]}):
            with self.subTest(candidate=candidate):
                self.assertEqual(native.safe_failure_report(json.dumps(candidate)), {
                    "status": "fail", "check": "invalid_child_report",
                })


class NativeFileComparisonTests(unittest.TestCase):
    """Execute the coroutine with immediate typed RPC doubles, never an event loop."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        (self.root / "workspace").mkdir()
        (self.root / "protected").mkdir()
        self.target = self.root / "workspace" / "comparison.txt"
        self.marker = "invented-comparison-marker"
        self.target.write_text(self.marker, encoding="utf-8")
        (self.root / "protected" / "control-plane.txt").write_text(
            "invented-protected-marker", encoding="utf-8")
        self.report = {"status": "fail", "check": "native_file_denial",
                       "reason": "explicit_native_denial_required"}
        self.options = []
        self.calls = []
        self.decisions = {}
        self.in_bound = False
        self.fault = None
        self.overrides = {}
        self.noise = None
        self.native_callback = False
        self.callback_control_requests = True
        self.allowed = True
        self.on_event = Mock()
        self.client = SimpleNamespace(create_session=self.create_session,
                                      delete_session=self.delete_session)

    async def bounded(self, awaitable):
        self.assertFalse(self.in_bound)
        self.in_bound = True
        try:
            return await awaitable
        finally:
            self.in_bound = False

    def record(self, case, operation, value=None):
        self.assertTrue(self.in_bound, f"unbounded RPC: {operation}")
        self.calls.append((case, operation, value))
        if self.fault == (case, operation):
            raise TimeoutError("invented timeout, never relay")

    async def delete_session(self, session_id):
        case = next(native.COMPARISON_CASES[i] for i, options in enumerate(self.options)
                    if options["session_id"] == session_id)
        self.record(case, "delete", session_id)

    async def create_session(self, **options):
        from copilot import CopilotClient
        from copilot.rpc import (
            ModeSetRequest, PermissionDecisionReject, PermissionPathsAllowedCheckParams,
            PermissionPathsAllowedCheckResult, PermissionsConfigureParams,
            PermissionsGetModeResult, ToolResultExpanded, ToolsExecuteRequest,
        )
        from copilot.session_events import PermissionMode, PermissionRequestRead, SessionMode

        inspect.signature(CopilotClient.create_session).bind(None, **options)
        case = native.COMPARISON_CASES[len(self.options)]
        self.options.append(options)
        self.record(case, "create", options["session_id"])
        callback = options["on_permission_request"]
        context = {"session_id": options["session_id"]}

        async def configure(request):
            self.assertIs(type(request), PermissionsConfigureParams)
            self.record(case, "configure", request.to_dict())

        async def set_mode(request):
            self.assertIs(type(request), ModeSetRequest)
            self.record(case, "set_mode", request.to_dict())

        async def mode():
            self.record(case, "get_mode")
            return SessionMode.PLAN

        async def permission_mode():
            self.record(case, "get_permission_mode")
            return PermissionsGetModeResult(mode=PermissionMode.MANUAL)

        async def allowed(request):
            self.assertIs(type(request), PermissionPathsAllowedCheckParams)
            self.record(case, "allowed", request.to_dict())
            return PermissionPathsAllowedCheckResult(allowed=self.allowed)

        async def initialize():
            self.record(case, "initialize")
            # Requests outside execution must never get a grant.
            result = callback(PermissionRequestRead(intention="fixture", path=str(self.target)), context)
            self.assertIs(type(result), PermissionDecisionReject)

        async def execute(request):
            self.assertIs(type(request), ToolsExecuteRequest)
            self.record(case, "execute", request.to_dict())
            if self.noise is not None:
                self.noise(case, callback, context, request)
            if ((case != "native_deny" or self.native_callback)
                    and (case != "callback_deny" or self.callback_control_requests)):
                decision = callback(PermissionRequestRead(
                    intention="fixture", path=request.arguments["path"]), context)
                self.decisions[case] = decision.to_dict()
            wire = self.overrides.get(case, {
                "permit": {"resultType": "success", "textResultForLlm": self.marker},
                "native_deny": {"resultType": "failure", "textResultForLlm": "",
                                "error": "Is a sandbox denied path."},
                "missing": {"resultType": "failure", "textResultForLlm": "",
                            "error": "Synthetic file does not exist"},
                "callback_deny": {"resultType": "denied", "textResultForLlm": "",
                                  "error": "Synthetic callback refusal"},
            }[case])
            # Canonical wire JSON is what pinned ToolsApi.execute actually returns.
            if isinstance(wire, dict) and wire.get("resultType") in native.TOOL_RESULT_KINDS:
                return ToolResultExpanded.from_dict(wire).to_dict()
            return wire

        async def abort():
            self.record(case, "abort")

        async def disconnect():
            self.record(case, "disconnect")
            result = callback(PermissionRequestRead(intention="fixture", path=str(self.target)), context)
            self.assertIs(type(result), PermissionDecisionReject)

        return SimpleNamespace(
            session_id=options["session_id"], abort=abort, disconnect=disconnect,
            rpc=SimpleNamespace(
                permissions=SimpleNamespace(
                    configure=configure, get_mode=permission_mode,
                    paths=SimpleNamespace(is_path_within_allowed_directories=allowed)),
                mode=SimpleNamespace(set=set_mode, get=mode),
                tools=SimpleNamespace(initialize_and_validate=initialize, execute=execute)),
        )

    def run_comparison(self):
        coroutine = native.compare_native_file_policy(
            self.client, self.root, self.report, self.bounded, self.on_event)
        try:
            coroutine.send(None)
        except StopIteration as completed:
            return completed.value
        finally:
            coroutine.close()
        self.fail("offline doubles must not suspend or create an event loop")

    def public_report(self):
        return native.safe_failure_report(
            json.dumps(self.report), root=self.root, protected_marker="invented-protected-marker",
            comparison_marker=self.marker)

    def test_same_file_and_bytes_with_only_denied_paths_policy_difference(self):
        self.native_callback = True
        self.run_comparison()
        self.assertEqual(self.target.read_text(encoding="utf-8"), self.marker)
        permit, deny = self.options[:2]
        self.assertNotEqual(permit["session_id"], deny["session_id"])
        comparable = lambda options: {
            key: value.to_dict() if callable(getattr(value, "to_dict", None)) else
            value.to_list() if key == "available_tools" else value
            for key, value in options.items()
            if key not in ("session_id", "on_permission_request")
        }
        a, b = comparable(permit), comparable(deny)
        self.assertEqual(a["sandbox_config"]["userPolicy"]["filesystem"]["deniedPaths"], [])
        self.assertEqual(b["sandbox_config"]["userPolicy"]["filesystem"]["deniedPaths"],
                         [str(self.target)])
        b["sandbox_config"]["userPolicy"]["filesystem"]["deniedPaths"] = []
        self.assertEqual(a, b)
        requests = [value for _, operation, value in self.calls if operation == "execute"]
        self.assertEqual(requests[0], requests[1])
        self.assertEqual(self.decisions["permit"], {"kind": "approve-once"})
        self.assertEqual(self.decisions["native_deny"], self.decisions["permit"])
        configured = [value for _, operation, value in self.calls if operation == "configure"]
        self.assertEqual(configured, [configured[0]] * 4)
        self.assertEqual(self.report["file_comparison"]["permit"]["allowed_directory"], "yes")
        self.assertEqual(self.report["file_comparison"]["native_deny"]["allowed_directory"], "yes")

    def test_missing_and_callback_controls_are_separate_and_do_not_claim_native_denial(self):
        self.run_comparison()
        cases = self.report["file_comparison"]
        self.assertEqual(cases["native_deny"]["callback"], "not_requested")
        self.assertTrue(cases["native_deny"]["sandbox_error_exact"])
        self.assertEqual(cases["missing"]["target"], "absent_file")
        self.assertEqual(cases["missing"]["callback"], "approved")
        self.assertFalse(cases["missing"]["sandbox_error_exact"])
        self.assertEqual(cases["callback_deny"]["callback"], "rejected")
        self.assertEqual(self.decisions["callback_deny"], {
            "kind": "reject", "feedback": "native_check_denied",
        })
        self.assertFalse(cases["callback_deny"]["sandbox_error_exact"])
        self.assertEqual(self.options[2]["sandbox_config"], self.options[0]["sandbox_config"])
        self.assertEqual(self.options[3]["sandbox_config"], self.options[0]["sandbox_config"])
        self.assertFalse((self.root / "workspace" / "comparison-missing.txt").exists())
        self.assertNotIn(self.marker, json.dumps(self.public_report()))
        self.assertNotIn(str(self.root), json.dumps(self.public_report()))

    def test_all_controls_finish_but_original_generic_failure_gate_still_fails(self):
        self.overrides["native_deny"] = {
            "resultType": "failure", "textResultForLlm": "", "error": "Unrelated synthetic failure",
        }
        result = self.run_comparison()
        self.assertEqual(list(self.report["file_comparison"]), list(native.COMPARISON_CASES))
        self.assertFalse(self.report["file_comparison"]["native_deny"]["sandbox_error_exact"])
        with self.assertRaisesRegex(native.CheckFailure, "explicit_native_denial_required"):
            native.require_denial(result)
        self.assertEqual(self.public_report()["status"], "fail")

    def test_comparison_is_wired_before_old_tool_and_file_gates(self):
        source = inspect.getsource(native.native_checks)
        self.assertLess(source.index("await compare_native_file_policy("),
                        source.index('report["check"] = "native_toolset"'))
        self.assertLess(source.index("await compare_native_file_policy("),
                        source.index("require_positive_read("))
        self.assertLess(source.index("await compare_native_file_policy("),
                        source.index("require_denial(comparison_result, report)"))
        self.assertLess(source.index("require_denial(comparison_result, report)"),
                        source.index('report["check"] = "native_toolset"'))
        self.assertIn("await asyncio.wait_for(awaitable, RPC_TIMEOUT)", source)

    def test_all_owned_sessions_are_aborted_disconnected_deleted_on_completion(self):
        self.run_comparison()
        for case in native.COMPARISON_CASES:
            with self.subTest(case=case):
                operations = [operation for name, operation, _ in self.calls if name == case]
                self.assertEqual(operations[-3:], ["abort", "disconnect", "delete"])
        self.assertEqual(self.report["comparison_cleanup"], "complete")

    def test_native_leak_has_priority_over_every_result_kind_and_stops_controls(self):
        for kind in native.TOOL_RESULT_KINDS:
            with self.subTest(kind=kind):
                self.options.clear()
                self.calls.clear()
                self.overrides["native_deny"] = {
                    "resultType": kind, "textResultForLlm": "", "error": self.marker,
                }
                with self.assertRaisesRegex(native.CheckFailure, "^comparison_canary_leaked$"):
                    self.run_comparison()
                self.assertEqual(len(self.options), 2)
                self.assertEqual([op for case, op, _ in self.calls if case == "native_deny"][-3:],
                                 ["abort", "disconnect", "delete"])
                self.assertNotIn(self.marker, json.dumps(self.report))

    def test_missing_positive_and_malformed_results_stop_fail_closed(self):
        for wire in (
            {"resultType": "failure", "textResultForLlm": "", "error": "not readable"},
            {"resultType": "success", "textResultForLlm": "not the marker"},
            {"resultType": "unknown"}, None,
        ):
            with self.subTest(wire=wire):
                self.options.clear()
                self.overrides["permit"] = wire
                with self.assertRaises(native.CheckFailure):
                    self.run_comparison()
                self.assertEqual(len(self.options), 1)

    def test_timeout_at_every_new_rpc_still_deletes_owned_id_and_stops(self):
        for operation in ("create", "configure", "set_mode", "get_mode",
                          "get_permission_mode", "initialize", "allowed", "execute"):
            with self.subTest(operation=operation):
                self.options.clear()
                self.calls.clear()
                self.fault = ("permit", operation)
                with self.assertRaises(TimeoutError):
                    self.run_comparison()
                self.assertEqual(len(self.options), 1)
                self.assertEqual(self.calls[-1][:2], ("permit", "delete"))
                if operation != "create":
                    self.assertEqual([op for _, op, _ in self.calls][-3:],
                                     ["abort", "disconnect", "delete"])

    def run_wire_comparison(self, case, wire):
        # ToolsApi.execute returns raw wire data. Preserve the existing typed
        # fixture's callback/bookkeeping, but bypass its result normalization.
        self.options.clear()
        self.calls.clear()

        async def create_session(**options):
            session = await self.create_session(**options)
            current_case = native.COMPARISON_CASES[len(self.options) - 1]
            execute = session.rpc.tools.execute

            async def execute_wire(request):
                result = await execute(request)
                return wire if current_case == case else result

            session.rpc.tools.execute = execute_wire
            return session

        with patch.object(self.client, "create_session", side_effect=create_session):
            return self.run_comparison()

    def assert_wire_failure(self, case, wire, reason):
        with self.assertRaisesRegex(native.CheckFailure, f"^{reason}$"):
            self.run_wire_comparison(case, wire)
        completed_cases = native.COMPARISON_CASES[:native.COMPARISON_CASES.index(case) + 1]
        self.assertEqual(list(self.report["file_comparison"]), list(completed_cases))
        self.assertEqual(len(self.options), len(completed_cases))
        self.assertEqual(
            [(name, op) for name, op, _ in self.calls
             if op in ("abort", "disconnect", "delete")],
            [(name, op) for name in completed_cases for op in ("abort", "disconnect", "delete")])
        self.assertNotIn("kind", self.report["file_comparison"][case])
        self.assertNotIn("error", self.report["file_comparison"][case])
        self.assertEqual(self.report["comparison_cleanup"],
                         "failed" if self.fault is not None else "complete")

    def test_malformed_wire_fields_fail_closed_in_every_control(self):
        invalid_fields = (
            [(field, value) for field in ("textResultForLlm", "resultType")
             for value in (None, [], {}, False, 7)]
            + [("resultType", "unknown")]
            + [("error", value) for value in ([], {"unexpected": "shape"}, False, 7)]
        )
        for case in native.COMPARISON_CASES:
            for field, value in invalid_fields:
                with self.subTest(case=case, field=field, value=value):
                    wire = {"resultType": "success" if case == "permit" else "failure",
                            "textResultForLlm": self.marker if case == "permit" else "",
                            field: value}
                    self.assert_wire_failure(case, wire, "comparison_malformed_result")

    def test_missing_required_wire_fields_fail_closed_in_every_control(self):
        for case in native.COMPARISON_CASES:
            for field in ("resultType", "textResultForLlm"):
                with self.subTest(case=case, field=field):
                    wire = {"resultType": "success" if case == "permit" else "failure",
                            "textResultForLlm": self.marker if case == "permit" else ""}
                    del wire[field]
                    self.assert_wire_failure(case, wire, "comparison_malformed_result")

    def test_explicit_denied_malformed_wire_cannot_reach_denial_gate(self):
        for case in native.COMPARISON_CASES:
            for fields in ({"textResultForLlm": []}, {"error": {"unexpected": "shape"}}):
                with self.subTest(case=case, fields=fields):
                    wire = {"resultType": "denied", "textResultForLlm": "", **fields}
                    # Demonstrate why comparison validation must precede the
                    # unchanged classification-only qualification predicate.
                    native.require_denial(wire)
                    self.assert_wire_failure(case, wire, "comparison_malformed_result")

    def test_comparison_canary_in_malformed_wire_precedes_validation(self):
        for case in ("native_deny", "missing", "callback_deny"):
            for field in ("textResultForLlm", "error", "resultType", "structuredContent"):
                with self.subTest(case=case, field=field):
                    wire = {"resultType": "denied", "textResultForLlm": [],
                            field: {"nested": [self.marker]}}
                    self.assert_wire_failure(case, wire, "comparison_canary_leaked")

    def test_protected_canary_in_malformed_wire_precedes_validation_in_every_control(self):
        for case in native.COMPARISON_CASES:
            for field in ("textResultForLlm", "error", "resultType", "structuredContent"):
                with self.subTest(case=case, field=field):
                    wire = {"resultType": "denied", "textResultForLlm": [],
                            field: {"nested": ["invented-protected-marker", self.marker]}}
                    self.assert_wire_failure(case, wire, "protected_canary_leaked")

    def test_optional_wire_error_absent_null_or_string_is_valid_in_every_control(self):
        from copilot.rpc import ToolResultExpanded

        self.assertEqual(native.metadata.version("github-copilot-sdk"), native.SDK_VERSION)
        for case in native.COMPARISON_CASES:
            for fields in ({}, {"error": None}, {"error": ""}, {"error": "Synthetic failure"}):
                with self.subTest(case=case, fields=fields):
                    kind = ("success" if case == "permit" else
                            "denied" if case == "callback_deny" else "failure")
                    wire = {"resultType": kind,
                            "textResultForLlm": self.marker if case == "permit" else "", **fields}
                    parsed = ToolResultExpanded.from_dict(wire)
                    self.assertEqual(parsed.error, fields.get("error"))
                    self.run_wire_comparison(case, wire)
                    self.assertEqual(list(self.report["file_comparison"]), list(native.COMPARISON_CASES))
                    self.assertEqual(self.report["file_comparison"][case]["kind"], kind)
                    self.assertEqual(self.report["comparison_cleanup"], "complete")

    def test_malformed_wire_failure_survives_cleanup_timeouts_in_every_control(self):
        for case in native.COMPARISON_CASES:
            for operation in ("abort", "disconnect", "delete"):
                with self.subTest(case=case, operation=operation):
                    self.fault = (case, operation)
                    self.assert_wire_failure(
                        case, {"resultType": "denied", "textResultForLlm": [],
                               "error": {"unexpected": "shape"}}, "comparison_malformed_result")

    def test_cleanup_timeout_attempts_remaining_cleanup_and_is_not_success(self):
        for operation in ("abort", "disconnect", "delete"):
            with self.subTest(operation=operation):
                self.options.clear()
                self.calls.clear()
                self.fault = ("permit", operation)
                with self.assertRaisesRegex(native.CheckFailure, "^comparison_cleanup_failed$"):
                    self.run_comparison()
                self.assertEqual([op for _, op, _ in self.calls][-3:],
                                 ["abort", "disconnect", "delete"])
                self.assertEqual(self.report["comparison_cleanup"], "failed")
                self.assertEqual(len(self.options), 1)

    def test_absent_callback_cannot_masquerade_as_callback_denial(self):
        self.callback_control_requests = False
        with self.assertRaisesRegex(native.CheckFailure, "^comparison_control_failed$"):
            self.run_comparison()
        self.assertEqual(self.report["file_comparison"]["callback_deny"]["callback"], "not_requested")
        self.assertEqual(self.calls[-1][:2], ("callback_deny", "delete"))

    def test_allowed_directory_mismatch_stops_before_read(self):
        self.allowed = False
        with self.assertRaisesRegex(native.CheckFailure, "^comparison_control_failed$"):
            self.run_comparison()
        self.assertNotIn("execute", [op for _, op, _ in self.calls])

    def test_late_cross_phase_callback_is_rejected_without_contaminating_next_case(self):
        from copilot.session_events import PermissionRequestRead

        def late(case, _callback, _context, _request):
            if case == "native_deny":
                previous = self.options[0]
                decision = previous["on_permission_request"](
                    PermissionRequestRead(intention="late", path=str(self.target)),
                    {"session_id": previous["session_id"]})
                self.assertEqual(decision.to_dict()["kind"], "reject")
        self.noise = late
        self.run_comparison()
        self.assertEqual(self.report["file_comparison"]["permit"]["callback"], "approved")
        self.assertEqual(self.report["file_comparison"]["native_deny"]["callback"], "not_requested")

    def test_active_wrong_session_noise_is_rejected_and_separately_recorded(self):
        from copilot.session_events import PermissionRequestRead

        def noise(_case, callback, _context, request):
            decision = callback(PermissionRequestRead(
                intention="noise", path=request.arguments["path"]), {"session_id": "unowned"})
            self.assertEqual(decision.to_dict()["kind"], "reject")
        self.noise = noise
        with self.assertRaisesRegex(native.CheckFailure, "^comparison_control_failed$"):
            self.run_comparison()
        case = self.report["file_comparison"]["permit"]
        self.assertEqual(case["callback"], "approved")
        self.assertTrue(case["callback_other"])
        self.assertTrue(case["callback_session_mismatch"])

    def test_bypass_grants_and_non_target_requests_are_never_approved(self):
        from copilot.session_events import PermissionRequestRead

        for overrides in (
            {"path": str(self.root)}, {"resolved_path": str(self.root)},
            {"request_sandbox_bypass": True}, {"managed_approval_required": True},
            {"request_sandbox_bypass_reason": "invented"},
            {"sandbox_path_grant": {}}, {"request_sandbox_bypass": 0},
        ):
            with self.subTest(overrides=overrides):
                self.options.clear()
                def noise(_case, callback, context, _request):
                    decision = callback(PermissionRequestRead(**{
                        "intention": "noise", "path": str(self.target), **overrides,
                    }), context)
                    self.assertEqual(decision.to_dict()["kind"], "reject")
                self.noise = noise
                with self.assertRaisesRegex(native.CheckFailure, "^comparison_control_failed$"):
                    self.run_comparison()

    def test_synthetic_errors_are_redacted_bounded_and_rescanned_by_parent(self):
        self.overrides["native_deny"] = {
            "resultType": "failure", "textResultForLlm": "",
            "error": str(self.target) + "\n::error::" + "x" * 2500,
        }
        self.run_comparison()
        error = self.public_report()["file_comparison"]["native_deny"]["error"]
        self.assertEqual(len(error["text"]), native.ERROR_TEXT_LIMIT)
        self.assertNotIn(str(self.root), error["text"])
        self.assertNotIn("::", error["text"])
        self.report["file_comparison"]["native_deny"]["error"] = {
            "source": "error", "text": "x" * 2045 + "invented-parent-only-value",
        }
        with patch.dict(native.os.environ, {"GITHUB_TOKEN": "invented-parent-only-value"}):
            self.assertEqual(self.public_report()["file_comparison"]["native_deny"]["error"],
                             {"suppressed": "credential_material"})

    def test_parent_original_marker_cannot_be_replaced_by_child_report(self):
        self.run_comparison()
        self.report["file_comparison"]["native_deny"]["error"] = {
            "source": "error", "text": self.marker,
        }
        self.report["comparison_marker"] = "invented-replacement"
        public = self.public_report()
        self.assertEqual(public["reason"], "comparison_canary_leaked")
        self.assertNotIn(self.marker, json.dumps(public))
        self.assertNotIn("comparison_marker", public)

    def test_parent_rejects_malformed_and_unknown_diagnostic_values(self):
        self.report["file_comparison"] = {
            "permit": {"kind": [], "marker_present": 1, "read_success": "true",
                       "callback": "raw", "denied_paths": [str(self.target)],
                       "error": {"source": "raw", "text": "never relay"}, "raw": self.marker},
            "unexpected": {"error": self.marker},
        }
        self.assertEqual(self.public_report()["file_comparison"], {
            "permit": {"error": {"suppressed": "malformed"}},
        })

    def test_leaks_in_text_and_nested_result_fields_stop_before_kind_checks(self):
        for field in ("textResultForLlm", "sessionLog", "structuredContent", "toolTelemetry"):
            with self.subTest(field=field):
                self.options.clear()
                self.overrides["native_deny"] = {
                    "resultType": "failure", "textResultForLlm": "",
                    field: self.marker if field in ("textResultForLlm", "sessionLog")
                    else {"nested": [self.marker]},
                }
                with self.assertRaisesRegex(native.CheckFailure, "^comparison_canary_leaked$"):
                    self.run_comparison()
                self.assertEqual(len(self.options), 2)

    def test_present_missing_fixture_is_not_an_io_error_control(self):
        (self.root / "workspace" / "comparison-missing.txt").write_text(
            "invented fixture", encoding="utf-8")
        with self.assertRaisesRegex(native.CheckFailure, "^comparison_control_failed$"):
            self.run_comparison()
        self.assertEqual(self.options, [])

    def test_explicit_missing_path_denial_is_not_an_ordinary_io_failure_control(self):
        self.overrides["missing"] = {"resultType": "denied", "textResultForLlm": ""}
        with self.assertRaisesRegex(native.CheckFailure, "^comparison_control_failed$"):
            self.run_comparison()
        self.assertEqual(len(self.options), 3)
        self.assertEqual(self.calls[-1][:2], ("missing", "delete"))

    def test_new_sessions_have_no_ambient_sources_hooks_or_bypass_permissions(self):
        self.run_comparison()
        for options in self.options:
            with self.subTest(session=len(options)):
                self.assertFalse(options["enable_config_discovery"])
                self.assertFalse(options["enable_skills"])
                self.assertEqual(options["available_tools"].to_list(), ["builtin:view"])
                self.assertEqual(options["mcp_servers"], {})
                self.assertEqual(options["disabled_mcp_servers"], ["*"])
                for key in ("plugin_directories", "agent_directories", "skill_directories",
                            "instruction_directories", "hook_directories"):
                    self.assertEqual(options[key], [])
                for key in ("hooks", "github_token", "github_token_provider", "provider", "tools"):
                    self.assertNotIn(key, options)
                self.assertFalse(options["sandbox_config"].allow_bypass)
                self.assertFalse(options["sandbox_config"].allow_dev_tool_access)
                self.assertFalse(options["sandbox_config"].user_policy.network.allow_outbound)
                self.assertFalse(options["sandbox_config"].user_policy.network.allow_local_network)
                permissions = options["managed_settings"].permissions
                self.assertEqual(permissions.disable_bypass_permissions_mode, "disable")
                self.assertTrue(permissions.disable_assisted_permissions_mode)
                self.assertEqual(permissions.limit_to, [])

    def test_parent_keeps_original_comparison_marker_even_if_fixture_changes(self):
        originals = []

        def launch(_arguments, **kwargs):
            fixture = kwargs["cwd"] / "comparison.txt"
            original = fixture.read_text(encoding="utf-8")
            originals.append(original)
            fixture.write_text("invented-replacement", encoding="utf-8")
            self.assertNotIn(original, kwargs["env"].values())
            self.assertNotIn("GITHUB_TOKEN", kwargs["env"])
            process = Mock(pid=12345, returncode=1)
            process.communicate.return_value = (json.dumps({
                "status": "fail", "check": "native_file_denial",
                "reason": "explicit_native_denial_required",
                "file_comparison": {"native_deny": {
                    "error": {"source": "error", "text": original},
                }},
            }), None)
            return process

        with patch.object(native.subprocess, "Popen", side_effect=launch):
            with patch.object(native, "kill_owned_group") as kill:
                with redirect_stdout(io.StringIO()) as output:
                    status = native.run_bounded(Path("/synthetic/runtime"))
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(output.getvalue())["reason"], "comparison_canary_leaked")
        self.assertNotIn(originals[0], output.getvalue())
        kill.assert_called_once()

    def test_comparison_diagnostics_are_omitted_from_success_stdout(self):
        expected = {"status": "pass", "check": "bounded_cleanup",
                    "sdk": native.SDK_VERSION, "publisher_cli": native.CLI_VERSION,
                    "runtime": native.CLI_VERSION, "protocol": 3, "passed": list(native.CHECKS)}
        process = Mock(pid=12345, returncode=0)
        process.communicate.return_value = (json.dumps({
            **expected, "file_comparison": {"permit": {"marker_present": True}},
            "comparison_cleanup": "complete",
        }), None)
        with patch.object(native.subprocess, "Popen", return_value=process):
            with patch.object(native, "kill_owned_group"):
                with redirect_stdout(io.StringIO()) as output:
                    status = native.run_bounded(Path("/synthetic/runtime"))
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue()), expected)


if __name__ == "__main__":
    unittest.main()

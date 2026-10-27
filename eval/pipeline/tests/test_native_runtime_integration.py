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
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import native_runtime_integration as native


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


if __name__ == "__main__":
    unittest.main()

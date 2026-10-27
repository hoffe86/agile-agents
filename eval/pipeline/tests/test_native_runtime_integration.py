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
            "session_id": "owned-session", "permission_sessions": ["owned-session"],
            "protected_read_pending": True, "protected_marker": "synthetic-protected-canary",
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
        self.assertNotIn("sensitive", json.dumps(self.report))

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


if __name__ == "__main__":
    unittest.main()

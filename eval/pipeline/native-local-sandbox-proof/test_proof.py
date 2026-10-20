"""Pure infrastructure tests: never start Copilot or require Linux."""

import copy
import json
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from proof import (
    check_boundaries, cleanup, native, parse_probe, permitted, policy,
    sandbox_applied, verify_effective_policy,
)
from setup_runtime import require_hosted, verify


class ProofTests(unittest.TestCase):
    def setUp(self):
        self.host = {
            "uid": 1001, "namespaces": {"user": "u1", "mnt": "m1", "net": "n1"},
            **{k: True for k in ("workspace_read", "workspace_write", "command",
                                "outside_read", "outside_write", "outbound", "localhost")},
        }
        self.child = copy.deepcopy(self.host)
        self.child.update(namespaces={"user": "u2", "mnt": "m2", "net": "n2"},
                          outside_read=False, outside_write=False, outbound=False, localhost=False)

    def test_positive_isolation(self):
        self.assertTrue(all(check_boundaries(self.host, self.child, {"123"}).values()))

    def test_unsandboxed_execution_cannot_pass(self):
        self.assertFalse(all(check_boundaries(self.host, self.host, set()).values()))

    def test_each_leak_fails(self):
        for field in ("outside_read", "outside_write", "outbound", "localhost"):
            with self.subTest(field=field):
                child = dict(self.child, **{field: True})
                self.assertFalse(all(check_boundaries(self.host, child, {"123"}).values()))

    def test_failed_positive_control_cannot_prove_denial(self):
        host = dict(self.host, outbound=False)
        self.assertFalse(check_boundaries(host, self.child, {"123"})["outbound_denied"])

    def test_no_backend_observation_fails(self):
        self.assertFalse(check_boundaries(self.host, self.child, set())["native_bwrap_observed"])

    def test_root_execution_fails(self):
        self.assertFalse(check_boundaries(self.host, dict(self.child, uid=0), {"1"})["non_root"])

    def test_same_namespace_fails(self):
        for name in ("user", "mnt", "net"):
            child = copy.deepcopy(self.child)
            child["namespaces"][name] = self.host["namespaces"][name]
            self.assertFalse(check_boundaries(self.host, child, {"1"})["private_namespaces"])

    def test_probe_marker_is_required_and_unique(self):
        line = "NATIVE_PROBE=" + json.dumps(self.child)
        self.assertEqual(parse_probe("tool output\n" + line + "\n"), self.child)
        for text in ("", "command echoed NATIVE_PROBE={}", line + "\n" + line):
            with self.subTest(text=text):
                with self.assertRaises(AssertionError):
                    parse_probe(text)

    def test_policy_explicitly_denies_network_and_bypass(self):
        sandbox = policy(PurePosixPath("/work"), PurePosixPath("/outside"))["sandbox"]
        self.assertTrue(sandbox["enabled"])
        for key in ("allowBypass", "allowDevToolAccess"):
            self.assertFalse(sandbox[key])
        self.assertEqual(sandbox["userPolicy"]["filesystem"]["deniedPaths"], ["/outside"])
        self.assertEqual(sandbox["userPolicy"]["network"],
                         {"allowOutbound": False, "allowLocalNetwork": False})
        self.assertEqual(sandbox["auth"], {"git": False, "gh": False})

    def test_only_exact_command_permission(self):
        data = {"kind": "shell", "fullCommandText": "synthetic"}
        self.assertTrue(permitted(data, "synthetic"))
        self.assertFalse(permitted(data, "different"))
        self.assertFalse(permitted(dict(data, kind="read"), "synthetic"))

    def test_no_bypass_or_policy_escalation(self):
        data = {"kind": "shell", "fullCommandText": "synthetic"}
        for key in ("requestSandboxBypass", "requestSandboxPermissive",
                    "sandboxPathGrant", "managedApprovalRequired"):
            with self.subTest(key=key):
                self.assertFalse(permitted(dict(data, **{key: True}), "synthetic"))

    def test_archive_integrity_rejects_bad_bytes(self):
        with self.assertRaisesRegex(RuntimeError, "integrity"):
            verify(b"not-a-cli")

    def test_lock_hashes_have_sha256_shape(self):
        for line in Path(__file__).with_name("requirements.txt").read_text().splitlines():
            if line and not line.startswith("#"):
                self.assertRegex(line, r"^[\w-]+==[\w.]+ --hash=sha256:[0-9a-f]{64}$")

    def test_local_execution_refused(self):
        with patch("setup_runtime.platform.system", return_value="Windows"):
            with self.assertRaisesRegex(RuntimeError, "GitHub-hosted"):
                require_hosted()

    def test_harness_has_no_model_send_or_sampling(self):
        import ast
        tree = ast.parse(Path(__file__).with_name("proof.py").read_text())
        forbidden = {"send", "send_and_wait", "execute_sampling", "compact"}
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n, ast.Call)
                          and isinstance(n.func, ast.Attribute) and n.func.attr in forbidden])

    def test_effective_policy_requires_native_text_and_all_restrictions(self):
        requested = policy(PurePosixPath("/work"), PurePosixPath("/outside"))["sandbox"]
        effective = requested["userPolicy"]
        result = {"kind": "text", "text": "Effective policy:\n```json\n" + json.dumps(effective) + "\n```"}
        self.assertEqual(verify_effective_policy(result, requested), effective)
        for invalid in (
            {"kind": "prompt", "text": result["text"]},
            {"kind": "text", "text": "Sandbox disabled"},
            {"kind": "text", "text": '{"success":true}'},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(AssertionError):
                verify_effective_policy(invalid, requested)
        for area, key, value in (
            ("filesystem", "deniedPaths", []),
            ("filesystem", "readwritePaths", []),
            ("filesystem", "readonlyPaths", []),
            ("network", "allowOutbound", True),
            ("network", "allowLocalNetwork", True),
            ("network", "allowOutbound", None),
        ):
            altered = copy.deepcopy(effective)
            altered[area][key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                verify_effective_policy({"kind": "text", "text": json.dumps(altered)}, requested)

    def test_telemetry_must_explicitly_confirm_sandbox_and_no_opt_out(self):
        self.assertFalse(sandbox_applied({}))
        for applied, bypass, expected in (
            ("true", "false", True), (True, False, True),
            ("false", "false", False), ("true", "true", False),
            ("true", None, False), (None, "false", False),
        ):
            with self.subTest(applied=applied, bypass=bypass):
                self.assertEqual(sandbox_applied({"toolTelemetry": {"properties": {
                    "sandboxApplied": applied, "sandboxOptOutRequested": bypass,
                }}}), expected)


class CleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_then_stop_without_destroy(self):
        session = SimpleNamespace(disconnect=AsyncMock())
        client = SimpleNamespace(stop=AsyncMock(return_value=[]))
        evidence = {"native_result": {"resultType": "success"}}
        await cleanup(session, client, evidence)
        session.disconnect.assert_awaited_once()
        client.stop.assert_awaited_once()
        self.assertEqual(evidence["cleanup_errors"], [])
        self.assertEqual(evidence["native_result"], {"resultType": "success"})

    async def test_disconnect_failure_still_stops_and_preserves_execution_exception(self):
        session = SimpleNamespace(disconnect=AsyncMock(side_effect=RuntimeError("disconnect failed")))
        client = SimpleNamespace(stop=AsyncMock(return_value=[]))
        original = AssertionError("original boundary failure")
        evidence = {"native_result": {"resultType": "failure", "error": "original"}}
        with self.assertRaises(AssertionError) as caught:
            try:
                raise original
            finally:
                await cleanup(session, client, evidence)
        self.assertIs(caught.exception, original)
        client.stop.assert_awaited_once()
        self.assertIn("disconnect failed", evidence["cleanup_errors"][0])
        self.assertEqual(evidence["native_result"]["error"], "original")

    async def test_stop_failure_recorded_even_without_session(self):
        for stop in (AsyncMock(side_effect=RuntimeError("stop failed")),
                     AsyncMock(return_value=[RuntimeError("stop failed")])):
            evidence = {}
            await cleanup(None, SimpleNamespace(stop=stop), evidence)
            self.assertIn("stop failed", evidence["cleanup_errors"][0])


class NativeLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, readback_valid=True, execute_error=None):
        """Mock only the SDK transport; exercise actual orchestration and cleanup."""
        def response(data):
            return SimpleNamespace(to_dict=lambda: data, **data)

        config = policy(PurePosixPath("/work"), PurePosixPath("/outside"))
        effective = config["sandbox"]["userPolicy"]
        result = {"resultType": "success", "textResultForLlm": "synthetic"}
        session = SimpleNamespace(disconnect=AsyncMock(), rpc=SimpleNamespace(
            options=SimpleNamespace(update=AsyncMock(return_value=response({"success": True}))),
            commands=SimpleNamespace(invoke=AsyncMock(return_value=response({
                "kind": "text", "text": json.dumps(effective) if readback_valid else "disabled",
            }))),
            tools=SimpleNamespace(
                initialize_and_validate=AsyncMock(),
                get_current_metadata=AsyncMock(return_value=response({})),
                execute=AsyncMock(return_value=response(result), side_effect=execute_error),
            ),
        ))
        client = SimpleNamespace(start=AsyncMock(), stop=AsyncMock(return_value=[]),
                                 create_session=AsyncMock(return_value=session),
                                 rpc=SimpleNamespace(sandbox=SimpleNamespace(
                                     get_host_support=AsyncMock(return_value=response({
                                         "supported": True, "capabilities": [
                                             {"name": n, "supported": True}
                                             for n in ("network", "denied_paths", "shell")],
                                     })))))
        sdk = SimpleNamespace(CopilotClient=lambda **_: client,
                              RuntimeConnection=SimpleNamespace(for_stdio=lambda **_: None))
        rpc = SimpleNamespace(
            CommandsInvokeRequest=SimpleNamespace, PermissionDecisionApproveOnce=SimpleNamespace,
            PermissionDecisionReject=SimpleNamespace, ToolsExecuteRequest=SimpleNamespace,
            SandboxConfig=SimpleNamespace(from_dict=lambda value: value),
            SandboxConfigSource=SimpleNamespace(SESSION_FLAG="session_flag"),
            SessionUpdateOptionsParams=SimpleNamespace,
        )
        evidence = {"policy": config}
        with patch.dict("sys.modules", {"copilot": sdk, "copilot.rpc": rpc}):
            try:
                await native(Path("/cli"), Path("/base"), Path("/work"), "synthetic",
                             evidence, 1234, False)
            except Exception as error:
                evidence["caught"] = error
        session.disconnect.assert_awaited_once()
        client.stop.assert_awaited_once()
        self.assertEqual(evidence["cleanup_errors"], [])
        update = session.rpc.options.update.await_args.args[0]
        self.assertEqual(update.sandbox_config, config["sandbox"])
        return evidence, session

    async def test_native_result_survives_cleanup(self):
        evidence, session = await self.exercise()
        self.assertNotIn("caught", evidence)
        self.assertEqual(evidence["native_result"]["resultType"], "success")
        session.rpc.tools.execute.assert_awaited_once()

    async def test_policy_readback_failure_prevents_negative_execution(self):
        evidence, session = await self.exercise(readback_valid=False)
        self.assertIsInstance(evidence["caught"], AssertionError)
        session.rpc.tools.execute.assert_not_awaited()

    async def test_execution_failure_not_masked_by_cleanup(self):
        original = RuntimeError("sandbox backend unavailable")
        evidence, _ = await self.exercise(execute_error=original)
        self.assertIs(evidence["caught"], original)


if __name__ == "__main__":
    unittest.main()

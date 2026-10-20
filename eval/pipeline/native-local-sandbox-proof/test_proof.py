"""Pure infrastructure tests: never start Copilot or require Linux."""

import copy
import json
from pathlib import Path, PurePosixPath
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from proof import (
    check_boundaries, check_host_integrity, check_unavailable, cleanup, native, parse_probe, permitted, policy,
    sandbox_applied, verify_effective_policy,
)
from setup_runtime import require_hosted, verify


def native_policy_report():
    """Renderer observed on CLI 1.0.98, hosted run 39400508772."""
    return (
        "Effective sandbox policy for /work\n\n"
        "\x1b[1mUser-configured paths:\x1b[22m\n"
        "  Read-only paths (4):\n    /bin\n    /lib\n    /lib64\n    /usr\n"
        "  Denied paths (1):\n    /outside\n\n"
        "\x1b[1mWorking directory:\x1b[22m\n"
        "  Read-write paths (1):\n    /work\n\n"
        "\x1b[1mDev tools:\x1b[22m\n  Not granted.\n\n"
        "\x1b[1mNetwork:\x1b[22m\n  Outbound: blocked\n  Local network: blocked\n\n"
        "\x1b[1mCapabilities:\x1b[22m\n"
        "  Allow sandbox bypass: no\n  Sandbox MCP servers: sandboxed\n"
        "  Sandbox LSP servers: sandboxed\n"
        "  Authenticate git (sandbox setting): off\n"
        "  Authenticate gh (sandbox setting): off\n  Denial capture: off\n"
    )


class ProofTests(unittest.TestCase):
    def setUp(self):
        self.host = {
            "uid": 1001, "namespaces": {"user": "u1", "mnt": "m1", "net": "n1"},
            **{k: True for k in ("workspace_read", "workspace_write", "command",
                                "outside_read", "outside_directory_write",
                                "outside_sentinel_write", "outbound", "localhost")},
        }
        self.child = copy.deepcopy(self.host)
        self.child.update(namespaces={"user": "u2", "mnt": "m2", "net": "n2"},
                          outside_read=False, outside_directory_write=False,
                          outside_sentinel_write=False, outbound=False, localhost=False)

    def test_positive_isolation(self):
        self.assertTrue(all(check_boundaries(self.host, self.child, {"123"}).values()))

    def test_unsandboxed_execution_cannot_pass(self):
        self.assertFalse(all(check_boundaries(self.host, self.host, set()).values()))

    def test_each_leak_fails(self):
        for field in ("outside_read", "outbound", "localhost"):
            with self.subTest(field=field):
                child = dict(self.child, **{field: True})
                self.assertFalse(all(check_boundaries(self.host, child, {"123"}).values()))

    def test_private_writes_pass_only_with_unchanged_host(self):
        with tempfile.TemporaryDirectory() as temp:
            denied = Path(temp)
            (denied / "sentinel").write_bytes(b"synthetic-not-a-secret")
            child = dict(self.child, outside_directory_write=True, outside_sentinel_write=True)
            checks = check_boundaries(self.host, child, {"123"})
            checks.update(check_host_integrity(denied))
            self.assertTrue(all(checks.values()))
            (denied / "write-marker").write_text("synthetic")
            checks.update(check_host_integrity(denied))
            self.assertFalse(all(checks.values()))

    def test_host_sentinel_mutation_or_removal_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            denied = Path(temp)
            sentinel = denied / "sentinel"
            sentinel.write_text("synthetic-overwrite")
            self.assertFalse(check_host_integrity(denied)["host_sentinel_unchanged"])
            sentinel.unlink()
            self.assertFalse(check_host_integrity(denied)["host_sentinel_unchanged"])
            sentinel.mkdir()
            self.assertFalse(check_host_integrity(denied)["host_sentinel_unchanged"])

    def test_any_added_host_directory_entry_fails(self):
        for name in ("write-marker", "unexpected-file", "unexpected-directory"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                denied = Path(temp)
                (denied / "sentinel").write_bytes(b"synthetic-not-a-secret")
                if name == "unexpected-directory":
                    (denied / name).mkdir()
                else:
                    (denied / name).write_text("synthetic")
                self.assertFalse(check_host_integrity(denied)["host_denied_directory_unchanged"])

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
        result = {"kind": "text", "text": native_policy_report()}
        effective = verify_effective_policy(result, requested)
        self.assertEqual(effective["filesystem"]["deniedPaths"], ["/outside"])
        self.assertFalse(effective["allowBypass"])
        self.assertEqual(effective["network"], requested["userPolicy"]["network"])
        for invalid in (
            {"kind": "prompt", "text": result["text"]},
            {"kind": "text", "text": "Sandbox disabled"},
            {"kind": "text", "text": '{"success":true}'},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(AssertionError):
                verify_effective_policy(invalid, requested)
        for original, replacement in (
            ("    /outside", "    /different"),
            ("    /work", "    /different"),
            ("    /lib64", "    /different"),
            ("Outbound: blocked", "Outbound: allowed"),
            ("Local network: blocked", "Local network: allowed"),
            ("  Outbound: blocked\n", ""),
            ("Allow sandbox bypass: no", "Allow sandbox bypass: yes"),
            ("Not granted.", "Granted."),
            ("Sandbox MCP servers: sandboxed", "Sandbox MCP servers: unsandboxed"),
            ("Sandbox LSP servers: sandboxed", "Sandbox LSP servers: unsandboxed"),
            ("Authenticate git (sandbox setting): off", "Authenticate git (sandbox setting): on"),
            ("Authenticate gh (sandbox setting): off", "Authenticate gh (sandbox setting): on"),
            ("Read-only paths (4)", "Read-only paths (5)"),
            ("policy for /work", "policy for /different"),
            ("Network:", "Unknown network:"),
        ):
            with self.subTest(original=original), self.assertRaises(AssertionError):
                verify_effective_policy({
                    "kind": "text", "text": result["text"].replace(original, replacement),
                }, requested)

    def test_conflicting_duplicate_policy_sections_fail(self):
        requested = policy(PurePosixPath("/work"), PurePosixPath("/outside"))["sandbox"]
        for extra in ("\n\nNetwork:\n  Outbound: allowed\n",
                      "  Allow sandbox bypass: yes\n"):
            with self.subTest(extra=extra), self.assertRaises(AssertionError):
                verify_effective_policy({"kind": "text", "text": native_policy_report() + extra}, requested)

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


class UnavailableTests(unittest.TestCase):
    def setUp(self):
        # Shape observed on CLI 1.0.98 / SDK 1.0.22, hosted run 39401092928.
        error = (
            "<error: GenericFailure, Sandboxing is enabled but not supported on this platform: "
            "Bubblewrap (bwrap) is unavailable. (Neither LXC nor Bubblewrap is available on this system "
            "(Bubblewrap (bwrap) is not installed or not on PATH. Install it via your package manager "
            "(e.g., apt install bubblewrap). Version 0.5.0 or newer is required.))>\n")
        self.result = {
            "resultType": "success",
            "textResultForLlm": error + "<shellId: 0 completed with exit code 1>",
            "toolTelemetry": {"metrics": {"exit_code": 1.0}},
            "contents": [{"type": "shell_exit", "shellId": "0", "exitCode": 1,
                          "outputPreview": error}],
        }
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.marker = Path(self.temp.name) / "UNSANDBOXED"

    def test_transport_success_with_explicit_command_failure_passes(self):
        self.assertTrue(all(check_unavailable(self.result, self.marker).values()))

    def test_exit_zero_cannot_pass_even_with_unavailable_error(self):
        self.result["contents"][0]["exitCode"] = 0
        self.result["toolTelemetry"]["metrics"]["exit_code"] = 0.0
        self.result["textResultForLlm"] = self.result["textResultForLlm"].replace("exit code 1", "exit code 0")
        self.assertFalse(check_unavailable(self.result, self.marker)["unavailable_command_failed"])

    def test_execution_marker_fails_even_with_nonzero_unavailable_result(self):
        self.marker.write_text("synthetic")
        self.assertFalse(check_unavailable(self.result, self.marker)["no_unsandboxed_marker"])
        self.assertFalse(all(check_unavailable(self.result, self.marker).values()))

    def test_generic_command_failure_without_sandbox_error_fails(self):
        for output in ("permission denied", "echo sandbox unavailable", ""):
            with self.subTest(output=output):
                self.result["contents"][0]["outputPreview"] = output
                self.assertFalse(check_unavailable(self.result, self.marker)["unavailable_sandbox_error"])

    def test_transport_failure_alone_is_not_command_failure_evidence(self):
        result = {"resultType": "failure", "error": "sandbox bwrap unavailable"}
        self.assertFalse(all(check_unavailable(result, self.marker).values()))

    def test_missing_ambiguous_or_invalid_shell_exit_fails(self):
        for exits in ([], self.result["contents"] * 2,
                      [{"type": "shell_exit", "exitCode": "1"}],
                      [{"type": "shell_exit", "exitCode": True}]):
            with self.subTest(exits=exits):
                result = dict(self.result, contents=exits)
                self.assertFalse(check_unavailable(result, self.marker)["unavailable_command_failed"])

    def test_conflicting_or_missing_exit_evidence_fails(self):
        for field, value in (("toolTelemetry", {}), ("toolTelemetry", {"metrics": {"exit_code": 0}}),
                             ("textResultForLlm", "<shellId: 0 completed with exit code 0>"),
                             ("textResultForLlm", "")):
            with self.subTest(field=field, value=value):
                result = dict(self.result, **{field: value})
                self.assertFalse(check_unavailable(result, self.marker)["unavailable_command_failed"])

    def test_duplicate_rendered_completion_fails(self):
        self.result["textResultForLlm"] += "\n<shellId: 0 completed with exit code 1>"
        self.assertFalse(check_unavailable(self.result, self.marker)["unavailable_command_failed"])

    def test_contradictory_rendered_completions_fail_in_either_order(self):
        for codes in ((0, 1), (1, 0), (2, 1), (1, 2)):
            with self.subTest(codes=codes):
                result = dict(self.result, textResultForLlm="\n".join(
                    f"<shellId: 0 completed with exit code {code}>" for code in codes))
                checks = check_unavailable(result, self.marker)
                self.assertTrue(checks["unavailable_sandbox_error"])
                self.assertTrue(checks["no_unsandboxed_marker"])
                self.assertFalse(checks["unavailable_command_failed"])
                self.assertFalse(all(checks.values()))

    def test_rendered_shell_id_must_match_structured_shell_exit(self):
        for text in (
            "<shellId: 1 completed with exit code 1>",
            "<shellId: 1 completed with exit code 1>\n<shellId: 0 completed with exit code 1>",
            "<shellId: 0 completed with exit code 1>\n<shellId: 1 completed with exit code 1>",
        ):
            with self.subTest(text=text):
                result = dict(self.result, textResultForLlm=text)
                self.assertFalse(check_unavailable(result, self.marker)["unavailable_command_failed"])

    def test_missing_or_invalid_structured_shell_id_fails(self):
        for shell_id in (None, "", 0):
            with self.subTest(shell_id=shell_id):
                result = copy.deepcopy(self.result)
                if shell_id is None:
                    del result["contents"][0]["shellId"]
                else:
                    result["contents"][0]["shellId"] = shell_id
                result["textResultForLlm"] = f"<shellId: {shell_id} completed with exit code 1>"
                self.assertFalse(check_unavailable(result, self.marker)["unavailable_command_failed"])

    def test_matching_non_default_shell_id_passes(self):
        self.result["contents"][0]["shellId"] = "7"
        self.result["textResultForLlm"] = self.result["textResultForLlm"].replace("shellId: 0", "shellId: 7")
        self.assertTrue(all(check_unavailable(self.result, self.marker).values()))


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
        result = {"resultType": "success", "textResultForLlm": "synthetic"}
        session = SimpleNamespace(disconnect=AsyncMock(), rpc=SimpleNamespace(
            options=SimpleNamespace(update=AsyncMock(return_value=response({"success": True}))),
            commands=SimpleNamespace(invoke=AsyncMock(return_value=response({
                "kind": "text", "text": native_policy_report() if readback_valid else "disabled",
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

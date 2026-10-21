"""Callback/configuration UNIT tests, never native runtime/isolation evidence."""
from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import MappingProxyType
import unittest
from unittest.mock import patch

EVAL = Path(__file__).resolve().parents[2]
ROOT = EVAL.parent
sys.path.insert(0, str(EVAL / "python"))

from agile_eval.authorization import BLOCKERS, MAX_JSON_BYTES, Decision, InvalidRecord, sha256  # noqa: E402
from agile_eval.native_controller import (  # noqa: E402
    NativeController, PermissionRejection, sanitized_runtime_spec,
    sdk_callbacks, start_native_runtime,
)
from test_authorization import NOW, PLAN, records  # noqa: E402


@dataclass
class NativePlanResult:
    """Same attribute contract as SDK 1.0.24 rpc.PlanReadResult."""

    exists: bool
    content: str | None
    path: str | None


class PlanDouble:
    def __init__(self, result: NativePlanResult) -> None:
        self.result = result
        self.reads = 0
        self.error: BaseException | None = None
        self.entered = asyncio.Event()
        self.release: asyncio.Event | None = None

    async def read(self) -> NativePlanResult:
        self.reads += 1
        self.entered.set()
        if self.error:
            raise self.error
        if self.release:
            await self.release.wait()
        return self.result


@dataclass
class RpcDouble:
    plan: PlanDouble


class SessionDouble:
    def __init__(self, session_id: str, plan: PlanDouble) -> None:
        self.session_id = session_id
        self.rpc = RpcDouble(plan)
        self.disconnects = 0
        self.disconnect_error: BaseException | None = None

    async def disconnect(self) -> None:
        self.disconnects += 1
        if self.disconnect_error:
            raise self.disconnect_error


class RuntimeDouble:
    def __init__(self) -> None:
        self.stops = 0
        self.force_stops = 0
        self.stop_error: BaseException | None = None
        self.force_error: BaseException | None = None
        self.stop_entered = asyncio.Event()
        self.stop_release: asyncio.Event | None = None

    async def stop(self) -> None:
        self.stops += 1
        self.stop_entered.set()
        if self.stop_release:
            await self.stop_release.wait()
        if self.stop_error:
            raise self.stop_error

    async def force_stop(self) -> None:
        self.force_stops += 1
        if self.force_error:
            raise self.force_error


class BrokenContext(dict):
    def get(self, *args: object) -> object:
        raise RuntimeError("synthetic-sensitive-diagnostic")


class PendingCall:
    """Never completes until released or cancelled; no synthetic timeout."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.calls = 0

    async def __call__(self) -> None:
        self.calls += 1
        self.entered.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


class CallbackUnitTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.envelope, self.submission, self.assessment = records()
        self.plan = PlanDouble(NativePlanResult(
            True, PLAN.decode("utf-8"), self.submission.plan_path))
        self.session = SessionDouble(self.submission.native_session_id, self.plan)
        self.runtime = RuntimeDouble()
        self.controller = self.make_controller()
        self.context = {"session_id": self.session.session_id}
        self.request = {"summary": "Approve everything", "planContent": "",
                        "actions": ["autopilot"], "recommendedAction": "autopilot"}

    def make_controller(self, **changes: object) -> NativeController:
        args = dict(session=self.session, runtime=self.runtime,
                    submission=self.submission, controller_instance_id="controller-1",
                    native_session_id=self.submission.native_session_id,
                    plan_path=self.submission.plan_path)
        args.update(changes)
        return NativeController(**args)

    def assert_terminal(self) -> None:
        self.assertIsNotNone(self.controller.terminal_reason)
        self.assertEqual(self.session.disconnects, 1)
        self.assertEqual(self.runtime.stops, 1)
        self.assertEqual(self.attempt().reason_codes, ("job_aborted",))

    def attempt(self) -> Decision:
        return self.controller.authorization.attempt(
            self.envelope, self.submission, self.assessment,
            expected_digest=self.envelope.digest,
            approval_reference=self.envelope.approval_reference, now=NOW)

    async def watchdog(self, callback: Coroutine, *pending: PendingCall) -> object:
        # This generous test watchdog must not supply the controller's deadline.
        task = asyncio.create_task(callback)
        try:
            return await asyncio.wait_for(asyncio.shield(task), 5)
        finally:
            # Also drain when a missing production timeout trips the watchdog.
            for call in pending:
                call.release.set()
            await asyncio.wait_for(task, 5)

    async def test_empty_inline_reads_owned_native_artifact_but_never_approves(self) -> None:
        result = await self.controller.on_exit_plan_mode_request(self.request, self.context)
        self.assertEqual(self.plan.reads, 1)
        self.assertEqual(result, {"approved": False,
                                 "feedback": "stage4_plan_provenance_unverified"})
        self.assertNotIn("selectedAction", result)
        self.assertIsNone(self.controller.terminal_reason)
        self.assertEqual(self.controller.authorization.state, "UNAUTHORIZED")
        self.assertEqual(self.controller.authorization.attempts, 0)

    async def test_nonempty_inline_and_summary_are_not_authority(self) -> None:
        self.request["planContent"] = "different inline plan"
        result = await self.controller.on_exit_plan_mode_request(self.request, self.context)
        self.assertEqual(result["feedback"], "stage4_plan_provenance_unverified")
        self.assertEqual(self.plan.reads, 1)

    async def test_stale_bytes_including_newlines_refuse_and_abort(self) -> None:
        self.plan.result.content = PLAN.decode().replace("\n", "\r\n")
        result = await self.controller.on_exit_plan_mode_request(self.request, self.context)
        self.assertEqual(result["feedback"], "native_plan_binding_mismatch")
        self.assert_terminal()

    async def test_exact_utf8_without_whitespace_normalization(self) -> None:
        content = "Grüße 東京\r\n  description\n"
        self.submission = replace(self.submission, plan_sha256=sha256(content.encode("utf-8")))
        self.controller = self.make_controller()
        self.plan.result.content = content
        result = await self.controller.on_exit_plan_mode_request(self.request, self.context)
        self.assertEqual(result["feedback"], "stage4_plan_provenance_unverified")

    async def test_stale_path_refuses(self) -> None:
        self.plan.result.path += ".other"
        result = await self.controller.on_exit_plan_mode_request(self.request, self.context)
        self.assertFalse(result["approved"])
        self.assert_terminal()

    async def test_missing_artifact_never_uses_summary(self) -> None:
        self.plan.result = NativePlanResult(False, None, None)
        result = await self.controller.on_exit_plan_mode_request(self.request, self.context)
        self.assertEqual(result["feedback"], "native_plan_binding_mismatch")
        self.assert_terminal()

    async def test_malformed_plan_result_refuses(self) -> None:
        self.plan.result = {"exists": True, "content": PLAN.decode()}
        result = await self.controller.on_exit_plan_mode_request(self.request, self.context)
        self.assertFalse(result["approved"])
        self.assert_terminal()

    async def test_wrong_callback_session_never_reads_plan(self) -> None:
        result = await self.controller.on_exit_plan_mode_request(
            self.request, {"session_id": "other"})
        self.assertFalse(result["approved"])
        self.assertEqual(self.plan.reads, 0)
        self.assert_terminal()

    async def test_replaced_native_session_never_reads_plan(self) -> None:
        self.session.session_id = "replaced"
        result = await self.controller.on_exit_plan_mode_request(self.request, self.context)
        self.assertFalse(result["approved"])
        self.assertEqual(self.plan.reads, 0)
        self.assert_terminal()

    async def test_read_failure_refuses_without_leaking_exception(self) -> None:
        self.plan.error = OSError("synthetic-sensitive-diagnostic")
        result = await self.controller.on_exit_plan_mode_request(self.request, self.context)
        self.assertEqual(result, {"approved": False, "feedback": "native_plan_read_failed"})
        self.assert_terminal()

    async def test_read_timeout_is_terminal(self) -> None:
        pending = PendingCall()
        self.controller = self.make_controller(timeout_seconds=0.02)
        with patch.object(self.plan, "read", pending):
            result = await self.watchdog(
                self.controller.on_exit_plan_mode_request(self.request, self.context), pending)
        self.assertFalse(result["approved"])
        self.assertEqual(result["feedback"], "native_plan_read_failed")
        self.assertTrue(pending.entered.is_set())
        self.assertTrue(pending.cancelled.is_set())
        self.assertEqual(pending.calls, 1)
        self.assert_terminal()

    async def test_cleanup_deadlines_cancel_pending_calls_and_force_stop(self) -> None:
        disconnect, stop, force_stop = PendingCall(), PendingCall(), PendingCall()
        self.controller = self.make_controller(timeout_seconds=0.02)
        with (patch.object(self.session, "disconnect", disconnect),
              patch.object(self.runtime, "stop", stop),
              patch.object(self.runtime, "force_stop", force_stop)):
            result = await self.watchdog(
                self.controller.on_exit_plan_mode_request(self.request, {"session_id": "wrong"}),
                disconnect, stop, force_stop)
            await self.controller.on_disconnect()
        self.assertFalse(result["approved"])
        self.assertEqual(result["feedback"], "native_plan_read_failed")
        self.assertEqual(self.controller.terminal_reason, "native_plan_read_failed")
        self.assertEqual(self.controller.cleanup_failures, (
            "session_disconnect_failed", "runtime_stop_failed", "runtime_force_stop_failed"))
        for call in (disconnect, stop, force_stop):
            self.assertTrue(call.entered.is_set())
            self.assertTrue(call.cancelled.is_set())
            self.assertEqual(call.calls, 1)
        self.assertEqual(self.attempt().reason_codes, ("job_aborted",))
        self.assertEqual(await self.controller.on_exit_plan_mode_request(
            self.request, self.context),
            {"approved": False, "feedback": "controller_terminal"})

    async def test_stop_deadline_falls_back_to_successful_force_stop(self) -> None:
        stop = PendingCall()
        self.controller = self.make_controller(timeout_seconds=0.02)
        with patch.object(self.runtime, "stop", stop):
            await self.watchdog(self.controller.on_disconnect(), stop)
        self.assertTrue(stop.entered.is_set())
        self.assertTrue(stop.cancelled.is_set())
        self.assertEqual(stop.calls, 1)
        self.assertEqual(self.session.disconnects, 1)
        self.assertEqual(self.runtime.force_stops, 1)
        self.assertEqual(self.controller.terminal_reason, "native_disconnected")
        self.assertEqual(self.controller.cleanup_failures, ("runtime_stop_failed",))
        self.assertEqual(self.attempt().reason_codes, ("job_aborted",))

    async def test_callback_cancellation_cleans_up_then_propagates(self) -> None:
        self.plan.release = asyncio.Event()
        task = asyncio.create_task(
            self.controller.on_exit_plan_mode_request(self.request, self.context))
        await self.plan.entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assert_terminal()
        result = await self.controller.on_exit_plan_mode_request(self.request, self.context)
        self.assertEqual(result["feedback"], "controller_terminal")
        self.assertEqual(self.plan.reads, 1)

    async def test_disconnect_during_read_is_terminal_no_retry(self) -> None:
        self.plan.release = asyncio.Event()
        task = asyncio.create_task(
            self.controller.on_exit_plan_mode_request(self.request, self.context))
        await self.plan.entered.wait()
        await self.controller.on_disconnect()
        self.plan.release.set()
        result = await task
        self.assertEqual(result["feedback"], "controller_terminal")
        await self.controller.on_disconnect()
        self.assert_terminal()

    async def test_native_session_replacement_during_read_aborts(self) -> None:
        self.plan.release = asyncio.Event()
        task = asyncio.create_task(
            self.controller.on_exit_plan_mode_request(self.request, self.context))
        await self.plan.entered.wait()
        self.session.session_id = "replaced"
        self.plan.release.set()
        result = await task
        self.assertFalse(result["approved"])
        self.assert_terminal()

    async def test_cancellation_during_cleanup_waits_for_owned_stop(self) -> None:
        self.runtime.stop_release = asyncio.Event()
        task = asyncio.create_task(self.controller.on_disconnect())
        await self.runtime.stop_entered.wait()
        task.cancel()
        self.runtime.stop_release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assert_terminal()

    async def test_cleanup_faults_still_force_stop_and_remain_terminal(self) -> None:
        self.session.disconnect_error = OSError("synthetic-sensitive-diagnostic")
        self.runtime.stop_error = OSError("synthetic-sensitive-diagnostic")
        self.runtime.force_error = OSError("synthetic-sensitive-diagnostic")
        await self.controller.on_disconnect()
        await self.controller.on_disconnect()
        self.assertEqual(self.runtime.force_stops, 1)
        self.assertEqual(self.controller.cleanup_failures, (
            "session_disconnect_failed", "runtime_stop_failed", "runtime_force_stop_failed"))
        self.assert_terminal()

    async def test_terminal_abort_preserves_used_attempt_without_refund(self) -> None:
        self.assertEqual(self.attempt().outcome, "eligible")
        await self.controller.on_disconnect()
        self.assertEqual(self.controller.authorization.state, "ABORTED")
        self.assertEqual(self.controller.authorization.attempts, 1)
        self.assertEqual(self.controller.authorization.reserved_budget, self.submission.budget)
        self.assert_terminal()

    async def test_invalid_job_control_record_stops_owned_runtime_on_every_callback(self) -> None:
        for callback in ("on_exit_plan_mode_request", "on_pre_tool_use",
                         "on_permission_request", "on_user_input_request"):
            with self.subTest(callback=callback):
                self.session = SessionDouble(self.submission.native_session_id, self.plan)
                self.runtime = RuntimeDouble()
                self.controller = self.make_controller()
                decision = self.controller.authorization.attempt(
                    self.envelope, self.submission, {},
                    expected_digest=self.envelope.digest,
                    approval_reference=self.envelope.approval_reference, now=NOW)
                self.assertEqual(decision.outcome, "abort_batch")
                await getattr(self.controller, callback)({}, self.context)
                self.assertEqual(self.controller.terminal_reason, "invalid_control_record")
                self.assert_terminal()
        self.assertEqual(self.plan.reads, 0)

    async def test_replacement_controller_cannot_inherit_used_or_aborted_state(self) -> None:
        self.assertEqual(self.attempt().outcome, "eligible")
        await self.controller.abort()
        replacement = self.make_controller()
        self.assertEqual(replacement.authorization.state, "UNAUTHORIZED")
        self.assertEqual(replacement.authorization.attempts, 0)
        self.assertIsNone(replacement.authorization.reserved_budget)
        with self.assertRaises(TypeError):
            replacement.authorization.attempt(
                self.envelope, self.submission, self.assessment, now=NOW)
        result = await replacement.on_exit_plan_mode_request(self.request, self.context)
        self.assertFalse(result["approved"])
        self.assertEqual(replacement.authorization.state, "UNAUTHORIZED")

    async def test_invalid_abort_reason_still_stops_owned_runtime(self) -> None:
        await self.controller.abort("synthetic-sensitive\ninvalid")
        self.assertEqual(self.controller.terminal_reason, "invalid_control_record")
        self.assert_terminal()

    async def test_ordinary_hook_failure_returns_deny_and_aborts(self) -> None:
        result = await self.controller.on_pre_tool_use({}, BrokenContext())
        self.assertEqual(result, {"permissionDecision": "deny",
                                 "permissionDecisionReason": "pre_tool_hook_failed"})
        self.assert_terminal()

    async def test_hook_failure_still_returns_deny_when_cleanup_also_fails(self) -> None:
        self.runtime.stop_error = OSError("synthetic-sensitive-diagnostic")
        self.runtime.force_error = OSError("synthetic-sensitive-diagnostic")
        result = await self.controller.on_pre_tool_use({}, BrokenContext())
        self.assertEqual(result["permissionDecision"], "deny")
        self.assertIn("runtime_force_stop_failed", self.controller.cleanup_failures)
        self.assert_terminal()

    async def test_hook_cancellation_while_waiting_cleans_up_and_propagates(self) -> None:
        self.plan.release = asyncio.Event()
        plan_task = asyncio.create_task(
            self.controller.on_exit_plan_mode_request(self.request, self.context))
        await self.plan.entered.wait()  # the session lock is now held by the plan read
        entered = asyncio.Event()

        async def hook():
            entered.set()
            return await self.controller.on_pre_tool_use({}, self.context)

        task = asyncio.create_task(hook())
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.plan.release.set()
        self.assertFalse((await plan_task)["approved"])
        self.assert_terminal()

    async def test_terminal_hook_and_permission_remain_denied(self) -> None:
        await self.controller.on_disconnect()
        result = await self.controller.on_pre_tool_use({}, self.context)
        self.assertEqual(result, {"permissionDecision": "deny",
                                 "permissionDecisionReason": "controller_terminal"})
        self.assertEqual(await self.controller.on_permission_request(
            {"approved": True}, self.context), PermissionRejection())
        permission = await self.controller.on_permission_request({"approved": True}, self.context)
        self.assertEqual((permission.kind, permission.feedback), ("reject", "execution_not_ready"))

    async def test_hook_callback_session_mismatch_aborts(self) -> None:
        result = await self.controller.on_pre_tool_use(
            {"sessionId": "other"}, self.context)
        self.assertEqual(result["permissionDecision"], "deny")
        self.assert_terminal()

    async def test_unattributed_operation_denies_without_guessing_delegate(self) -> None:
        result = await self.controller.on_pre_tool_use(
            {"sessionId": self.session.session_id, "toolName": "view"}, self.context)
        self.assertEqual(result["permissionDecisionReason"], "operation_unattributed")
        self.assertEqual(result["permissionDecision"], "deny")

    async def test_all_native_delegate_mcp_and_expanded_scope_routes_denied(self) -> None:
        for name in ("view", "create", "bash", "task", "remote-mcp/tool", "unknown"):
            with self.subTest(tool=name):
                result = await self.controller.on_pre_tool_use({
                    "sessionId": self.session.session_id, "toolName": name,
                    "agentId": "writer", "toolArgs": {"path": "/outside/secret"},
                }, self.context)
                self.assertEqual(result["permissionDecision"], "deny")
                self.assertEqual(result["permissionDecisionReason"], "operation_route_unverified")

    async def test_permission_independently_rejects_without_plan_or_hook(self) -> None:
        result = await self.controller.on_permission_request(
            {"kind": "write", "approved": True}, BrokenContext())
        self.assertEqual(result, PermissionRejection())
        self.assertEqual((result.kind, result.feedback), ("reject", "execution_not_ready"))

    async def test_arbitrary_ask_user_approval_is_refused(self) -> None:
        result = await self.controller.on_user_input_request(
            {"question": "Approve?", "choices": ["Approve and run autonomously"],
             "approved": True}, self.context)
        self.assertEqual(result, {"answer": "REFUSE: execution_not_ready", "wasFreeform": True})

    def test_constructor_rejects_mismatched_controller_session_path(self) -> None:
        for changes in ({"controller_instance_id": "wrong"},
                        {"native_session_id": "wrong"}, {"plan_path": "/wrong"},
                        {"timeout_seconds": float("nan")}):
            with self.subTest(changes=changes), self.assertRaises(InvalidRecord):
                self.make_controller(**changes)


class SdkCallbacksContractTests(unittest.IsolatedAsyncioTestCase):
    """Actual pinned SDK types, offline; no client, transport or model calls."""

    def setUp(self) -> None:
        from importlib.metadata import PackageNotFoundError, version

        install = (
            "Install eval/deepeval/requirements.lock.txt with "
            "python -m pip install --require-hashes --only-binary=:all: -r "
            "eval/deepeval/requirements.lock.txt"
        )
        try:
            self.assertEqual(version("github-copilot-sdk"), "1.0.24", install)
        except PackageNotFoundError:
            self.fail(install)
        # The event loop's wakeup sockets already exist. Imports and callbacks
        # must not create a transport or process, even with opt_in=True.
        for target in ("socket.socket.__init__", "subprocess.Popen"):
            blocker = patch(target, side_effect=AssertionError("offline contract forbids startup"))
            mock = blocker.start()
            self.addCleanup(blocker.stop)
            self.addCleanup(mock.assert_not_called)
        # Local imports leave this module's shared doubles usable in -S children.
        try:
            from copilot._cli_version import CLI_VERSION
            from copilot.rpc import PlanReadResult
        except ImportError as exc:
            self.fail(f"{install}: {exc}")
        self.assertEqual(CLI_VERSION, "1.0.101")
        blocker = patch("copilot.CopilotClient",
                        side_effect=AssertionError("offline contract forbids startup"))
        mock = blocker.start()
        self.addCleanup(blocker.stop)
        self.addCleanup(mock.assert_not_called)
        _, submission, _ = records()
        self.plan = PlanDouble(PlanReadResult(
            exists=True, content=PLAN.decode(), path=submission.plan_path))
        self.session = SessionDouble(submission.native_session_id, self.plan)
        self.runtime = RuntimeDouble()
        self.controller = NativeController(
            session=self.session, runtime=self.runtime, submission=submission,
            controller_instance_id=submission.controller_instance_id,
            native_session_id=submission.native_session_id, plan_path=submission.plan_path)
        self.context = {"session_id": submission.native_session_id}
        self.callbacks = sdk_callbacks(self.controller, opt_in=True)

    async def test_factory_wires_handlers_and_returns_real_permission_rejection(self) -> None:
        from copilot.generated.session_events import PermissionRequestShell
        from copilot.rpc import PermissionDecisionReject

        self.assertEqual(set(self.callbacks), {
            "on_exit_plan_mode_request", "on_user_input_request", "on_permission_request", "hooks"})
        self.assertEqual(self.callbacks["on_exit_plan_mode_request"],
                         self.controller.on_exit_plan_mode_request)
        self.assertEqual(self.callbacks["on_user_input_request"],
                         self.controller.on_user_input_request)
        self.assertEqual(self.callbacks["hooks"],
                         {"on_pre_tool_use": self.controller.on_pre_tool_use})
        request = PermissionRequestShell(
            can_offer_session_approval=False, commands=[], full_command_text="not-executed",
            has_write_file_redirection=False, intention="offline contract",
            possible_paths=[], possible_urls=[])
        for terminal in (False, True):
            with self.subTest(terminal=terminal):
                if terminal:
                    await self.controller.abort()
                result = await self.callbacks["on_permission_request"](request, self.context)
                self.assertIs(type(result), PermissionDecisionReject)
                self.assertEqual((result.kind, result.feedback), ("reject", "execution_not_ready"))
        self.assertEqual(self.runtime.stops, 1)

    async def test_real_plan_result_stays_held_and_other_callbacks_deny(self) -> None:
        result = await self.callbacks["on_exit_plan_mode_request"]({}, self.context)
        self.assertEqual(result, {"approved": False,
                                 "feedback": "stage4_plan_provenance_unverified"})
        denial = await self.callbacks["hooks"]["on_pre_tool_use"](
            {"sessionId": self.session.session_id, "agentId": "writer"}, self.context)
        self.assertEqual(denial["permissionDecision"], "deny")
        answer = await self.callbacks["on_user_input_request"](
            {"approved": True, "question": "Approve?"}, self.context)
        self.assertEqual(answer, {"answer": "REFUSE: execution_not_ready", "wasFreeform": True})
        self.assertEqual(self.controller.authorization.state, "UNAUTHORIZED")
        self.assertEqual(self.runtime.stops, 0)

    async def test_real_oversized_plan_result_aborts_and_stops(self) -> None:
        from copilot.rpc import PlanReadResult

        self.plan.result = PlanReadResult(
            exists=True, content="é" * MAX_JSON_BYTES, path=self.plan.result.path)
        result = await self.callbacks["on_exit_plan_mode_request"]({}, self.context)
        self.assertEqual(result, {"approved": False, "feedback": "native_plan_binding_mismatch"})
        self.assertEqual(self.controller.authorization.state, "ABORTED")
        self.assertEqual(self.session.disconnects, 1)
        self.assertEqual(self.runtime.stops, 1)


class SdkConfigurationContractTests(unittest.TestCase):
    def test_runtime_options_bind_to_selected_sdk_without_startup(self) -> None:
        import inspect

        with (
            patch("socket.socket.__init__",
                  side_effect=AssertionError("offline contract")) as socket_start,
            patch("subprocess.Popen",
                  side_effect=AssertionError("offline contract")) as process_start,
        ):
            from copilot.client import CopilotClient, RuntimeConnection

            base = Path(tempfile.gettempdir()) / "not-created-sdk-contract"
            spec = sanitized_runtime_spec(
                {}, home=base / "home", config=base / "config", temp=base / "tmp",
                workspace=base / "workspace", trusted_path=(base / "bin",))
            # Bind against the real keyword-only API, not a permissive test double.
            inspect.signature(CopilotClient.create_session).bind(
                None, **spec.session_options())
            connection = RuntimeConnection.for_stdio(
                path=str(base / "bin" / "copilot-runtime"), args=spec.cli_args)
            self.assertEqual(connection.path, str(base / "bin" / "copilot-runtime"))
            self.assertEqual(connection.args, spec.cli_args)
            inspect.signature(CopilotClient).bind(
                connection=connection, env=dict(spec.environment),
                base_directory=spec.base_directory, working_directory=spec.working_directory,
                use_logged_in_user=False)
            socket_start.assert_not_called()
            process_start.assert_not_called()


class RuntimeConfigurationUnitTests(unittest.IsolatedAsyncioTestCase):
    def spec(self, parent: dict[str, str]):
        base = Path(tempfile.gettempdir()) / "not-created-held-runtime"
        return sanitized_runtime_spec(
            MappingProxyType(parent), home=base / "home", config=base / "config",
            temp=base / "tmp", workspace=base / "workspace", trusted_path=(base / "bin",))

    def test_allowlist_removes_synthetic_credentials_and_startup_injection(self) -> None:
        parent = {name: "synthetic-secret-marker" for name in (
            "PATH", "HOME", "GH_TOKEN", "GITHUB_TOKEN", "COPILOT_GITHUB_TOKEN",
            "COPILOT_SDK_AUTH_TOKEN", "OPENAI_API_KEY", "AZURE_CLIENT_SECRET",
            "AWS_ACCESS_KEY_ID", "SSH_AUTH_SOCK", "GIT_CONFIG_GLOBAL", "GIT_ASKPASS",
            "HTTPS_PROXY", "ALL_PROXY", "NODE_OPTIONS", "NODE_PATH", "PYTHONPATH",
            "PYTHONSTARTUP", "PYTHONHOME", "BASH_ENV", "ENV", "LD_PRELOAD",
            "DYLD_INSERT_LIBRARIES", "SSL_CERT_FILE", "COPILOT_CONNECTION_TOKEN",
        )}
        parent["LANG"] = "C.UTF-8"
        before = dict(parent)
        ambient = dict(os.environ)
        spec = self.spec(parent)
        self.assertEqual(parent, before)
        self.assertEqual(dict(os.environ), ambient)
        self.assertNotIn("synthetic-secret-marker", spec.environment.values())
        self.assertEqual(spec.environment["LANG"], "C.UTF-8")
        self.assertFalse(spec.use_logged_in_user)
        self.assertEqual(spec.environment["COPILOT_DISABLE_KEYTAR"], "1")
        with self.assertRaises(TypeError):
            spec.environment["GH_TOKEN"] = "synthetic-secret-marker"

    def test_untrusted_locale_cannot_smuggle_parent_value(self) -> None:
        self.assertEqual(self.spec({"LANG": "synthetic-injection"}).environment["LANG"], "C")

    def test_no_discovery_hooks_host_git_mcp_or_auto_update(self) -> None:
        spec = self.spec({})
        self.assertEqual(spec.cli_args, ("--no-auto-update", "--no-auto-login", "--sandbox"))
        self.assertEqual(spec.session_options(), {
            "working_directory": spec.working_directory,
            "config_directory": spec.base_directory,
            "skip_custom_instructions": True, "enable_config_discovery": False,
            "enable_on_demand_instruction_discovery": False,
            "enable_file_hooks": False, "enable_host_git_operations": False,
            "enable_session_store": False, "enable_session_telemetry": False,
            "skip_embedding_retrieval": True, "enable_skills": False,
            "plugin_directories": [], "mcp_servers": {}, "available_tools": [],
        })
        changed = spec.session_options()
        changed["mcp_servers"]["remote"] = "not-authority"
        self.assertEqual(spec.session_options()["mcp_servers"], {})

    async def test_launcher_always_not_ready(self) -> None:
        result = await start_native_runtime(self.spec({}))
        self.assertFalse(result.execution_ready)
        self.assertEqual(result.blocker_codes, BLOCKERS)

    async def test_client_token_rejected_before_start_including_empty(self) -> None:
        for token in ("", "synthetic-secret-marker"):
            with self.subTest(token_present=bool(token)), self.assertRaisesRegex(
                    InvalidRecord, "^invalid_record$"):
                await start_native_runtime(self.spec({}), github_token=token)

    def test_relative_or_injected_paths_are_rejected(self) -> None:
        base = Path(tempfile.gettempdir())
        for path in (Path("relative"), base / ".." / "outside", Path(str(base) + "\n")):
            with self.subTest(path=path), self.assertRaises(InvalidRecord):
                sanitized_runtime_spec({}, home=path, config=base, temp=base,
                                       workspace=base, trusted_path=(base,))

    def test_sdk_boundary_requires_explicit_opt_in(self) -> None:
        with self.assertRaises(InvalidRecord):
            sdk_callbacks(None)

    def test_trusted_path_cannot_add_an_extra_search_entry(self) -> None:
        base = Path(tempfile.gettempdir())
        with self.assertRaises(InvalidRecord):
            sanitized_runtime_spec({}, home=base, config=base, temp=base,
                                   workspace=base,
                                   trusted_path=(Path(str(base) + os.pathsep + "other"),))

    def test_import_readiness_and_launcher_without_sdk_deepeval_or_io(self) -> None:
        # -S removes site-packages. Audit fails on process/network/filesystem
        # mutations; import reads are allowed, credential discovery is not invoked.
        code = f"""
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, {str(EVAL / "python")!r})
# Create asyncio's own wakeup socketpair before forbidding all socket activity.
# Nothing in the module/launcher/readiness is allowed to create another socket.
loop = asyncio.new_event_loop()
def audit(event, args):
    if event.startswith(('socket.', 'subprocess.', 'os.mkdir', 'sqlite3.connect')):
        raise AssertionError(event)
sys.addaudithook(audit)
from agile_eval import native_controller
from agile_eval.authorization import live_readiness
assert 'copilot' not in sys.modules and 'deepeval' not in sys.modules
base = Path({str(EVAL)!r}) / 'not-created-runtime'
spec = native_controller.sanitized_runtime_spec(
    {{}}, home=base / 'home', config=base / 'config', temp=base / 'tmp',
    workspace=base / 'work', trusted_path=(base / 'bin',))
assert not loop.run_until_complete(native_controller.start_native_runtime(spec)).execution_ready
loop.close()
print(live_readiness().canonical_bytes().decode('ascii'))
"""
        result = subprocess.run([sys.executable, "-B", "-S", "-c", code],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["execution_ready"])
        cli = subprocess.run(
            [sys.executable, "-B", "-S", str(EVAL / "authorization.py"), "check-readiness"],
            capture_output=True, text=True, timeout=20)
        self.assertEqual(cli.returncode, 2, cli.stderr)
        self.assertEqual(json.loads(cli.stdout)["blocker_codes"], list(BLOCKERS))


class HeldEntrypointUnitTests(unittest.TestCase):
    """Diagnostic doubles target Python, which now owns the unconditional hold.

    Actual shell/startup/missing-interpreter coverage lives in test_native_scoring.
    Mocking shell `python` used to mock only diagnostics; it now replaces the
    entire entrypoint and cannot test that entrypoint's safety.
    """

    def run_held(self, diagnostic: str) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            output = base / "must-not-stage"
            script = """
import sys
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
from agile_eval import run_eval
def diagnostic(*args, **kwargs):
    assert args[0][1:4] == ['-I', '-S', '-B']
    if sys.argv[3] == 'missing':
        raise OSError('diagnostic missing')
    if sys.argv[3] == 'error':
        raise run_eval.subprocess.TimeoutExpired('diagnostic', 10)
    print('diagnostic-called')
    return run_eval.subprocess.CompletedProcess(args[0], 0)
def deny(event, args):
    if event.startswith(('socket.', 'os.mkdir', 'subprocess.')):
        raise AssertionError(event)
sys.addaudithook(deny)
with patch.object(run_eval.subprocess, 'run', diagnostic):
    code = run_eval.main(['--suite', 'custom-eval', '--output-root', sys.argv[2], '--no-isolation'])
assert not any(n.startswith(('copilot', 'deepeval', 'yaml')) for n in sys.modules)
raise SystemExit(code)
"""
            result = subprocess.run(
                [sys.executable, "-I", "-S", "-B", "-c", script,
                 str(EVAL / "python"), str(output), diagnostic], capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("live evaluation is disabled", (result.stdout + result.stderr).lower())
            self.assertFalse(output.exists())
            if diagnostic == "success":
                self.assertIn("diagnostic-called", result.stdout)
            else:
                self.assertIn("Readiness diagnostic unavailable", result.stderr)

    def test_nondry_runner_always_exits_two_before_staging_despite_diagnostic_status(self) -> None:
        for diagnostic in ("success", "error", "missing"):
            with self.subTest(diagnostic=diagnostic):
                self.run_held(diagnostic)


if __name__ == "__main__":
    unittest.main()

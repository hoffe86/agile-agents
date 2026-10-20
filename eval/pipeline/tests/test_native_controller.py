"""Callback/configuration UNIT tests, never native runtime/isolation evidence."""
from __future__ import annotations

import asyncio
from contextlib import closing
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from types import MappingProxyType
import unittest

EVAL = Path(__file__).resolve().parents[2]
ROOT = EVAL.parent
sys.path.insert(0, str(EVAL))

from authorization import BLOCKERS, InvalidRecord, sha256  # noqa: E402
from authorization_ledger import AdmissionDenied, Ledger  # noqa: E402
from native_controller import (  # noqa: E402
    NativeController, PermissionRejection, sanitized_runtime_spec,
    sdk_callbacks, start_native_runtime,
)
from test_authorization import NOW, PLAN, records  # noqa: E402


@dataclass
class NativePlanResult:
    """Same attribute contract as SDK 1.0.22 rpc.PlanReadResult."""

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


class FailingLedger:
    """Required-write/close fault at the external persistence seam."""

    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger
        self.closes = 0

    def abort_batch(self, *args: object, **kwargs: object) -> None:
        raise OSError("synthetic-sensitive-diagnostic")

    def close(self) -> None:
        self.closes += 1
        self.ledger.close()
        raise OSError("synthetic-sensitive-diagnostic")


class CallbackUnitTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "ledger.sqlite"
        self.envelope, self.submission, self.assessment = records()
        self.ledger = Ledger(self.path, controller_instance_id="controller-1")
        self.addCleanup(self.ledger.close)
        self.ledger.register_envelope(
            self.envelope, expected_digest=self.envelope.digest,
            approval_reference=self.envelope.approval_reference)
        self.plan = PlanDouble(NativePlanResult(
            True, PLAN.decode("utf-8"), self.submission.plan_path))
        self.session = SessionDouble(self.submission.native_session_id, self.plan)
        self.runtime = RuntimeDouble()
        self.controller = self.make_controller()
        self.context = {"session_id": self.session.session_id}
        self.request = {"summary": "Approve everything", "planContent": "",
                        "actions": ["autopilot"], "recommendedAction": "autopilot"}

    def make_controller(self, **changes: object) -> NativeController:
        args = dict(session=self.session, runtime=self.runtime, ledgers=(self.ledger,),
                    submission=self.submission, controller_instance_id="controller-1",
                    native_session_id=self.submission.native_session_id,
                    plan_path=self.submission.plan_path)
        args.update(changes)
        return NativeController(**args)

    def assert_terminal(self) -> None:
        self.assertIsNotNone(self.controller.terminal_reason)
        self.assertEqual(self.session.disconnects, 1)
        self.assertEqual(self.runtime.stops, 1)
        with self.assertRaises(AdmissionDenied):
            self.ledger.issue(self.submission, self.assessment, now=NOW)

    async def test_empty_inline_reads_owned_native_artifact_but_never_approves(self) -> None:
        result = await self.controller.on_exit_plan_mode_request(self.request, self.context)
        self.assertEqual(self.plan.reads, 1)
        self.assertEqual(result, {"approved": False,
                                 "feedback": "stage4_plan_provenance_unverified"})
        self.assertNotIn("selectedAction", result)
        self.assertIsNone(self.controller.terminal_reason)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM grants").fetchone(), (0,))

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
        self.plan.error = TimeoutError()
        result = await self.controller.on_exit_plan_mode_request(self.request, self.context)
        self.assertFalse(result["approved"])
        self.assert_terminal()

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

    async def test_cleanup_faults_still_close_all_connections_and_force_stop(self) -> None:
        joined = Ledger(self.path, controller_instance_id="controller-1", join_existing=True)
        self.addCleanup(joined.close)
        failed = FailingLedger(self.ledger)
        self.controller = self.make_controller(ledgers=(failed, joined))
        self.session.disconnect_error = OSError("synthetic-sensitive-diagnostic")
        self.runtime.stop_error = OSError("synthetic-sensitive-diagnostic")
        self.runtime.force_error = OSError("synthetic-sensitive-diagnostic")
        await self.controller.on_disconnect()
        await self.controller.on_disconnect()
        self.assertEqual(failed.closes, 1)
        self.assertEqual(self.runtime.force_stops, 1)
        self.assertEqual(self.controller.cleanup_failures, (
            "ledger_abort_failed", "ledger_close_failed", "session_disconnect_failed",
            "runtime_stop_failed", "runtime_force_stop_failed"))
        with self.assertRaises(AdmissionDenied):
            joined.issue(self.submission, self.assessment, now=NOW)
        self.assert_terminal()

    async def test_terminal_abort_revokes_real_issued_grant_without_refund(self) -> None:
        grant = self.ledger.issue(self.submission, self.assessment, now=NOW)
        await self.controller.on_disconnect()
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute(
                "SELECT state FROM grants WHERE grant_id=?", (grant.grant_id,)).fetchone(),
                ("revoked",))
            self.assertEqual(db.execute("SELECT tokens FROM attempts").fetchone(),
                             (self.submission.budget.tokens,))
        self.assert_terminal()

    async def test_ordinary_hook_failure_returns_deny_and_aborts(self) -> None:
        result = await self.controller.on_pre_tool_use({}, BrokenContext())
        self.assertEqual(result, {"permissionDecision": "deny",
                                 "permissionDecisionReason": "pre_tool_hook_failed"})
        self.assert_terminal()

    async def test_hook_failure_still_returns_deny_when_cleanup_also_fails(self) -> None:
        self.controller = self.make_controller(ledgers=(FailingLedger(self.ledger),))
        self.runtime.stop_error = OSError("synthetic-sensitive-diagnostic")
        self.runtime.force_error = OSError("synthetic-sensitive-diagnostic")
        result = await self.controller.on_pre_tool_use({}, BrokenContext())
        self.assertEqual(result["permissionDecision"], "deny")
        self.assertIn("ledger_abort_failed", self.controller.cleanup_failures)
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

    async def test_arbitrary_ask_user_approval_is_refused(self) -> None:
        result = await self.controller.on_user_input_request(
            {"question": "Approve?", "choices": ["Approve and run autonomously"],
             "approved": True}, self.context)
        self.assertEqual(result, {"answer": "REFUSE: execution_not_ready", "wasFreeform": True})

    def test_constructor_rejects_mismatched_controller_session_path(self) -> None:
        for changes in ({"controller_instance_id": "wrong"},
                        {"native_session_id": "wrong"}, {"plan_path": "/wrong"},
                        {"ledgers": ()}, {"timeout_seconds": float("nan")}):
            with self.subTest(changes=changes), self.assertRaises(InvalidRecord):
                self.make_controller(**changes)


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
            "enable_github_cache_store": False,
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
sys.path.insert(0, {str(EVAL)!r})
# Create asyncio's own wakeup socketpair before forbidding all socket activity.
# Nothing in the module/launcher/readiness is allowed to create another socket.
loop = asyncio.new_event_loop()
def audit(event, args):
    if event.startswith(('socket.', 'subprocess.', 'os.mkdir', 'sqlite3.connect')):
        raise AssertionError(event)
sys.addaudithook(audit)
import native_controller
from authorization import live_readiness
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
    """Real shell entrypoints, controlled diagnostic doubles; no native SDK."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.pwsh = shutil.which("pwsh")
        cls.bash = (str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) /
                       "Git/usr/bin/bash.exe") if os.name == "nt" else shutil.which("bash"))
        if not cls.pwsh or not cls.bash or not Path(cls.bash).exists():
            raise RuntimeError("Both configured native shells are required")

    def run_held(self, native: str, diagnostic: str) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            output = base / "must-not-stage"
            marker = base / "must-not-start"
            injection = base / "sitecustomize.py"
            injection.write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).write_text('injected')\n",
                encoding="utf-8")
            # A plausible envelope is adjacent but has no authority.
            envelope, submission, _ = records()
            grant = base / "grant.json"
            grant.write_bytes(envelope.canonical_bytes())
            env = {k: v for k, v in os.environ.items()
                   if k in ("SystemRoot", "WINDIR", "COMSPEC", "PATHEXT")}
            env.update(PATH="", HOME=str(base), USERPROFILE=str(base),
                       TEMP=str(base), TMP=str(base), GH_TOKEN="synthetic-token",
                       COPILOT_SDK_AUTH_TOKEN="synthetic-token", EVAL_EXECUTION_READY="true",
                       EVAL_GRANT=str(grant), EVAL_ENVELOPE=str(grant),
                       PYTHONPATH=str(base), PYTHONSTARTUP=str(injection))
            if diagnostic == "actual":
                control = subprocess.run(
                    [sys.executable, "-c", "pass"], env=env, capture_output=True,
                    text=True, timeout=20)
                self.assertEqual(control.returncode, 0, control.stderr)
                self.assertTrue(marker.exists(), "startup-injection control did not fire")
                marker.unlink()
            if native == "powershell":
                script = EVAL / "pipeline/run-eval.ps1"
                python = str(Path(sys.executable)).replace("'", "''")
                definitions = {
                    "actual": f"function python {{ & '{python}' @args }};",
                    "success": "function python { 'diagnostic-called'; $global:LASTEXITCODE=0 };",
                    "error": "function python { throw 'diagnostic-failed' };",
                    "missing": "",
                }
                code = (definitions[diagnostic] +
                        f"function copilot {{ Set-Content '{marker}' 'started'; throw 'forbidden' }};"
                        f"& '{script}' -Suite custom-eval -OutputRoot '{output}' -NoIsolation;"
                        "exit $LASTEXITCODE")
                command = [self.pwsh, "-NoProfile", "-NonInteractive", "-Command", code]
            else:
                # dirname is the only external utility used before the live hold.
                # Copy individual utilities/DLLs, never an ambient executable PATH.
                tools = base / "tools"
                tools.mkdir()
                dirname = (Path(self.bash).parent / "dirname.exe" if os.name == "nt"
                           else Path(shutil.which("dirname")))
                shutil.copy2(dirname, tools / dirname.name)
                if os.name == "nt":
                    for library in dirname.parent.glob("*.dll"):
                        shutil.copy2(library, tools / library.name)
                env["PATH"] = str(tools)
                definitions = {
                    "actual": f'python() {{ "{Path(sys.executable).as_posix()}" "$@"; }};',
                    "success": "python() { echo diagnostic-called; return 0; };",
                    "error": "python() { echo diagnostic-failed; return 9; };",
                    "missing": "",
                }
                code = (definitions[diagnostic] +
                        f'copilot() {{ echo started > "{marker.as_posix()}"; return 99; }};'
                        'export -f copilot; ' +
                        ("export -f python; " if diagnostic != "missing" else "") +
                        f'source "{(EVAL / "pipeline/run-eval.sh").as_posix()}" '
                        f'--suite custom-eval --output-root "{output.as_posix()}" --no-isolation')
                command = [self.bash, "--noprofile", "--norc", "-c", code]
            result = subprocess.run(command, env=env, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("live evaluation is disabled", (result.stdout + result.stderr).lower())
            self.assertFalse(output.exists())
            self.assertFalse(marker.exists())
            if diagnostic == "actual":
                self.assertIn('"execution_ready":false', result.stdout)
            elif diagnostic == "success":
                self.assertIn("diagnostic-called", result.stdout)
            elif diagnostic == "error":
                self.assertTrue("diagnostic-failed" in result.stdout or
                                "Readiness diagnostic unavailable" in result.stderr)

    def test_both_nondry_runners_always_exit_two_before_staging_or_startup(self) -> None:
        for native in ("powershell", "bash"):
            for diagnostic in ("actual", "success", "error", "missing"):
                with self.subTest(native=native, diagnostic=diagnostic):
                    self.run_held(native, diagnostic)


if __name__ == "__main__":
    unittest.main()

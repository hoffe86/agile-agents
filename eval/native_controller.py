"""Held native callback boundary. No SDK import, discovery or startup on import.

Protocols mirror public SDK 1.0.22 surfaces, not its private dispatch machinery.
Callback unit tests are NOT native mediation, Stage 4 or OS isolation evidence.
There is deliberately no approved/exit_only branch, grant consumption or resume.
"""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
import math
import os
from pathlib import Path
from types import MappingProxyType
from typing import Protocol, TypedDict

from authorization import (
    InvalidRecord, MAX_JSON_BYTES, PlanSubmission, Readiness, identifier,
    live_readiness, sha256,
)
from authorization_ledger import Ledger


class PlanReadResult(Protocol):
    exists: bool
    content: str | None
    path: str | None


class NativePlan(Protocol):
    async def read(self) -> PlanReadResult: ...


class NativeRpc(Protocol):
    plan: NativePlan


class NativeSession(Protocol):
    session_id: str
    rpc: NativeRpc

    async def disconnect(self) -> None: ...


class OwnedRuntime(Protocol):
    """Only a dedicated, controller-owned client, never a shared/remote runtime."""

    async def stop(self) -> None: ...
    async def force_stop(self) -> None: ...


class PlanRefusal(TypedDict):
    approved: bool
    feedback: str


class ToolDenial(TypedDict):
    permissionDecision: str
    permissionDecisionReason: str


class UserRefusal(TypedDict):
    answer: str
    wasFreeform: bool


@dataclass(frozen=True)
class PermissionRejection:
    """Internal decision; sdk_callbacks translates to the SDK's native type."""

    kind: str = "reject"
    feedback: str = "execution_not_ready"


class NativeController:
    """One immutable submission and owned session; all routes remain denied.

    All owned ledger connections must be supplied, including join_existing ones.
    Ownership is a trusted construction precondition, not a workspace assertion.
    A session lock serializes callbacks, NOT native plan-read-to-tool execution.
    """

    def __init__(
        self, *, session: NativeSession, runtime: OwnedRuntime,
        ledgers: tuple[Ledger, ...], submission: PlanSubmission,
        controller_instance_id: str, native_session_id: str, plan_path: str,
        timeout_seconds: float = 5.0,
    ) -> None:
        submission.__post_init__()
        if (submission.controller_instance_id != identifier(controller_instance_id) or
                submission.native_session_id != identifier(native_session_id) or
                submission.plan_path != plan_path or not ledgers or
                not math.isfinite(timeout_seconds) or timeout_seconds <= 0):
            raise InvalidRecord()
        self._session, self._runtime = session, runtime
        self._ledgers = tuple(ledgers)
        self._submission = submission
        self._session_id, self._plan_path = native_session_id, plan_path
        self._timeout = timeout_seconds
        self._lock = asyncio.Lock()
        self._terminal_reason: str | None = None
        self._cleanup_task: asyncio.Task[None] | None = None
        self._cleanup_failures: list[str] = []

    @property
    def terminal_reason(self) -> str | None:
        return self._terminal_reason

    @property
    def cleanup_failures(self) -> tuple[str, ...]:
        return tuple(self._cleanup_failures)

    def _check_session(self, context: Mapping[str, object]) -> None:
        if (self._session.session_id != self._session_id or
                context.get("session_id") != self._session_id):
            raise InvalidRecord()

    async def _cleanup(self) -> None:
        # Persistence can fail: still close EVERY owned connection and stop the
        # owned runtime. Never echo exceptions, which can contain credentials.
        for ledger in self._ledgers:
            try:
                ledger.abort_batch(self._submission.batch_id,
                                   reason=self._terminal_reason)
            except Exception:
                self._cleanup_failures.append("ledger_abort_failed")
            finally:
                try:
                    ledger.close()
                except Exception:
                    self._cleanup_failures.append("ledger_close_failed")
        try:
            await asyncio.wait_for(self._session.disconnect(), self._timeout)
        except (Exception, asyncio.CancelledError):
            self._cleanup_failures.append("session_disconnect_failed")
        try:
            await asyncio.wait_for(self._runtime.stop(), self._timeout)
        except (Exception, asyncio.CancelledError):
            self._cleanup_failures.append("runtime_stop_failed")
            try:
                await asyncio.wait_for(self._runtime.force_stop(), self._timeout)
            except (Exception, asyncio.CancelledError):
                self._cleanup_failures.append("runtime_force_stop_failed")

    async def abort(self, reason: str = "controller_aborted") -> None:
        """Latch before any await; finish cleanup before propagating cancellation.

        Repeated aborts await the same cleanup, never retry/resume/refund. If even
        force-stop fails, cleanup_failures exposes uncertainty; state stays terminal.
        """
        if self._cleanup_task is None:
            self._terminal_reason = identifier(reason)
            self._cleanup_task = asyncio.create_task(self._cleanup())
        cancelled = False
        while not self._cleanup_task.done():
            try:
                await asyncio.shield(self._cleanup_task)
            except asyncio.CancelledError:
                cancelled = True
        self._cleanup_task.result()
        if cancelled:
            raise asyncio.CancelledError()

    async def on_disconnect(self) -> None:
        await self.abort("native_disconnected")

    async def on_exit_plan_mode_request(
        self, request: Mapping[str, object], context: Mapping[str, object],
    ) -> PlanRefusal:
        try:
            async with self._lock:
                if self._terminal_reason:
                    return {"approved": False, "feedback": "controller_terminal"}
                self._check_session(context)
                # Neither inline planContent (even nonempty) nor summary is authority.
                result = await asyncio.wait_for(
                    self._session.rpc.plan.read(), self._timeout)
                self._check_session(context)  # a disconnect/replacement during read
                if self._terminal_reason:
                    return {"approved": False, "feedback": "controller_terminal"}
                if (result.exists is not True or type(result.content) is not str or
                        result.path != self._plan_path or
                        len(result.content) > MAX_JSON_BYTES):
                    await self.abort("native_plan_binding_mismatch")
                    return {"approved": False, "feedback": "native_plan_binding_mismatch"}
                exact_bytes = result.content.encode("utf-8")
                if (len(exact_bytes) > MAX_JSON_BYTES or
                        sha256(exact_bytes) != self._submission.plan_sha256):
                    await self.abort("native_plan_binding_mismatch")
                    return {"approved": False, "feedback": "native_plan_binding_mismatch"}
                # An exact native artifact is still not semantic dev-lead Stage 4.
                return {"approved": False, "feedback": "stage4_plan_provenance_unverified"}
        except asyncio.CancelledError:
            await self.abort("callback_cancelled")
            raise
        except Exception:
            await self.abort("native_plan_read_failed")
            return {"approved": False, "feedback": "native_plan_read_failed"}

    async def on_pre_tool_use(
        self, request: Mapping[str, object], context: Mapping[str, object],
    ) -> ToolDenial:
        reason = "execution_not_ready"
        try:
            async with self._lock:
                if self._terminal_reason:
                    reason = "controller_terminal"
                else:
                    self._check_session(context)
                    if request.get("sessionId") != self._session_id:
                        raise InvalidRecord()
                    if not request.get("agentId"):
                        reason = "operation_unattributed"
                    else:
                        # No route, including native/delegate/MCP, has complete
                        # verified mediation. Never infer scope from tool arguments.
                        reason = "operation_route_unverified"
        except asyncio.CancelledError:
            await self.abort("callback_cancelled")
            raise
        except Exception:
            await self.abort("pre_tool_hook_failed")
            reason = "pre_tool_hook_failed"
        # SDK hook exceptions fail open: ordinary failures MUST return explicit deny.
        return {"permissionDecision": "deny", "permissionDecisionReason": reason}

    async def on_permission_request(
        self, request: object, context: Mapping[str, object],
    ) -> PermissionRejection:
        # Independent of pre-tool hooks, plan callbacks, and arbitrary request text.
        return PermissionRejection()

    async def on_user_input_request(
        self, request: Mapping[str, object], context: Mapping[str, object],
    ) -> UserRefusal:
        return {"answer": "REFUSE: execution_not_ready", "wasFreeform": True}


def sdk_callbacks(controller: NativeController, *, opt_in: bool = False) -> dict[str, object]:
    """Explicit integration-only SDK import; no client creation or startup.

    Not invoked by readiness or runners. This does not certify native routes.
    """
    if opt_in is not True:
        raise InvalidRecord()
    from copilot.rpc import PermissionDecisionReject

    async def permission(request: object, context: Mapping[str, object]) -> object:
        result = await controller.on_permission_request(request, context)
        return PermissionDecisionReject(feedback=result.feedback)

    return {
        "on_exit_plan_mode_request": controller.on_exit_plan_mode_request,
        "on_user_input_request": controller.on_user_input_request,
        "on_permission_request": permission,
        "hooks": {"on_pre_tool_use": controller.on_pre_tool_use},
    }


@dataclass(frozen=True)
class RuntimeSpec:
    """Sanitized configuration only, not OS isolation or a launch capability."""

    environment: Mapping[str, str]
    base_directory: str
    working_directory: str
    use_logged_in_user: bool = False
    cli_args: tuple[str, ...] = ("--no-auto-update", "--no-auto-login", "--sandbox")

    def session_options(self) -> dict[str, object]:
        """Fresh defensive config, not a claim these flags enforce isolation.

        No plugins/MCP/tools are enabled in the held candidate. In particular,
        an empty tool list is not used as revocation of an existing runtime.
        """
        return {
            "working_directory": self.working_directory,
            "config_directory": self.base_directory,
            "skip_custom_instructions": True, "enable_config_discovery": False,
            "enable_on_demand_instruction_discovery": False,
            "enable_file_hooks": False, "enable_host_git_operations": False,
            "enable_session_store": False, "enable_session_telemetry": False,
            "enable_github_cache_store": False,
            "skip_embedding_retrieval": True, "enable_skills": False,
            "plugin_directories": [], "mcp_servers": {}, "available_tools": [],
        }


def _absolute(path: Path) -> str:
    path = Path(path)
    if (not path.is_absolute() or ".." in path.parts or
            str(path).startswith(("\\\\", "//")) or
            any(ord(c) < 32 for c in str(path))):
        raise InvalidRecord()
    return str(path)


def sanitized_runtime_spec(
    parent_environment: Mapping[str, str], *, home: Path, config: Path, temp: Path,
    workspace: Path, trusted_path: tuple[Path, ...],
) -> RuntimeSpec:
    """No discovery/mkdir; callers must supply private paths and trusted binaries.

    The only inherited allowlist item is a constrained locale. No user PATH,
    Git/SSH/proxy/keychain/cloud/model variables or Python/Node startup settings.
    Paths/ACLs, SDK-added environment and actual OS isolation remain unverified.
    """
    if not trusted_path:
        raise InvalidRecord()
    home_s, config_s, temp_s = _absolute(home), _absolute(config), _absolute(temp)
    if any(os.pathsep in str(item) for item in trusted_path):
        raise InvalidRecord()
    path = os.pathsep.join(_absolute(item) for item in trusted_path)
    environment = {
        "PATH": path, "HOME": home_s, "USERPROFILE": home_s,
        "XDG_CONFIG_HOME": str(Path(home_s) / ".config"),
        "XDG_CACHE_HOME": str(Path(home_s) / ".cache"),
        "APPDATA": str(Path(home_s) / "appdata"),
        "LOCALAPPDATA": str(Path(home_s) / "localappdata"),
        "COPILOT_HOME": config_s,
        "TMPDIR": temp_s, "TMP": temp_s, "TEMP": temp_s,
        "COPILOT_DISABLE_KEYTAR": "1", "COPILOT_TELEMETRY_DISABLED": "1",
        "DO_NOT_TRACK": "1", "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
        "LANG": "C",
    }
    if parent_environment.get("LANG") in ("C", "C.UTF-8"):
        environment["LANG"] = parent_environment["LANG"]
    return RuntimeSpec(MappingProxyType(environment), config_s, _absolute(workspace))


async def start_native_runtime(
    spec: RuntimeSpec, *, github_token: str | None = None,
) -> Readiness:
    """Held launcher: no SDK import/client, token discovery, files or process.

    SDK 1.0.22 injects client github_token into COPILOT_SDK_AUTH_TOKEN *after*
    env replacement. Reject that option, including empty strings, before startup.
    No per-session token/proxy workaround. No caller-supplied readiness switch.
    """
    if github_token is not None:
        raise InvalidRecord()
    return live_readiness()

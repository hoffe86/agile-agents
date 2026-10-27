"""Opt-in, pre-model integration checks for SDK 1.0.24 / publisher CLI 1.0.101.

Hosted Ubuntu only; never collected as a unittest/pytest test module. Provision
the existing hash lock, then `python -m copilot download-runtime` in a trusted
step. Pass the resulting copilot-runtime executable explicitly:

    python eval/pipeline/tests/native_runtime_integration.py --run-native \
        --runtime-path /absolute/path/to/copilot-runtime

No prompts, login, tokens, downloads, production admission, or evaluation removal.
Public RPCs below are version-specific (some SDK RPC groups are experimental).
Passing these primitives is NOT worker attribution, Stage 4, model provenance,
an atomic plan-digest transaction, or permission to remove the live safety hold.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import uuid


SDK_VERSION = "1.0.24"
CLI_VERSION = "1.0.101"
RPC_TIMEOUT = 15
OUTER_TIMEOUT = 180
CANARY_NAME = "AGILE_NATIVE_AMBIENT_CANARY"
SHELL_OUTPUT_MARKER = "native-unexpected-shell"
# SDK 1.0.24 generated/rpc.py: ToolResultType (not all kinds are denials).
TOOL_RESULT_KINDS = ("denied", "failure", "rejected", "success", "timeout")
PLAN = "# Synthetic plan\n\nDo not execute anything. Exit plan mode only.\n"
REQUIRED_NATIVE_TOOLS = (
    "ask_user", "exit_plan_mode", "list_agents", "read_agent",
    "skill", "task", "view", "write_agent",
)
TRUSTED_SKILL_DIRECTORY = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "agile-agents-core" / "skills" / "trade-off-reporting"
)


class CheckFailure(Exception):
    """Only fixed, non-sensitive failure codes cross the subprocess boundary."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise CheckFailure(code)


def require_native_tools(names: set[str], report: dict) -> None:
    # Only fixed expected names enter the report, never the runtime inventory.
    missing = [name for name in REQUIRED_NATIVE_TOOLS if name not in names]
    if missing:
        report["missing_tools"] = missing
        raise CheckFailure("native_tools_missing")


def refuse_user_input(_request: object, _context: object) -> dict:
    """Expose native ask_user without accepting approval from question/choice text."""
    return {"answer": "REFUSE: native_check_refused", "wasFreeform": True}


def require_trusted_skill(skills: list) -> None:
    """Require native discovery, not just a skill tool name or supplied metadata."""
    require(len(skills) == 1, "unexpected_skill_inventory")
    skill = skills[0]
    require(skill.name == TRUSTED_SKILL_DIRECTORY.name and skill.enabled is True
            and bool(skill.path)
            and Path(skill.path).resolve() == TRUSTED_SKILL_DIRECTORY / "SKILL.md"
            and not skill.plugin_name, "trusted_skill_not_discovered")


def check_prerequisites(runtime: Path) -> None:
    require(sys.platform == "linux", "hosted_linux_required")
    try:
        distribution = metadata.distribution("github-copilot-sdk")
    except metadata.PackageNotFoundError:
        raise CheckFailure("sdk_not_installed") from None
    require(distribution.version == SDK_VERSION, "sdk_version_mismatch")
    # Read publisher metadata, not a private runtime API; never call --version.
    source = distribution.locate_file("copilot/_cli_version.py").read_text("utf-8")
    pins = [
        ast.literal_eval(node.value)
        for node in ast.parse(source).body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name) and node.target.id == "CLI_VERSION"
    ]
    require(pins == [CLI_VERSION], "publisher_cli_pin_mismatch")
    require(runtime.is_absolute() and runtime.is_file()
            and os.access(runtime, os.X_OK), "provisioned_runtime_required")
    require((runtime.parent / "runtime.node").is_file(),
            "provisioned_runtime_bundle_required")


def isolated_environment(root: Path) -> dict[str, str]:
    """Hygiene only: effective process/file/network restrictions are tested below."""
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(root / "home"),
        "XDG_CONFIG_HOME": str(root / "home" / ".config"),
        "XDG_CACHE_HOME": str(root / "home" / ".cache"),
        "XDG_DATA_HOME": str(root / "home" / ".local" / "share"),
        "TMPDIR": str(root / "tmp"),
        "COPILOT_HOME": str(root / "state"),
        "COPILOT_SKIP_CLI_DOWNLOAD": "1",
        "COPILOT_DISABLE_KEYTAR": "1",
        "COPILOT_TELEMETRY_ENABLED": "false",
        "COPILOT_OTEL_ENABLED": "false",
        "DEEPEVAL_TELEMETRY_OPT_OUT": "1",
        "LANG": "C.UTF-8",
    }


def require_denial(result: object, report: dict | None = None, *,
                   shell_canary: Path | None = None) -> None:
    # 1.0.24 ToolsApi.execute is annotated as a dataclass but returns wire JSON.
    # Normalize the documented result shape, not arbitrary errors into success.
    missing = object()
    kind = (result.get("resultType", missing) if isinstance(result, dict)
            else getattr(result, "result_type", missing))
    kind = getattr(kind, "value", kind)
    diagnostic = {
        "shape": ("mapping" if isinstance(result, dict) else
                  "object" if hasattr(result, "result_type") else "other"),
        "kind": (kind if kind in TOOL_RESULT_KINDS else
                 "absent" if kind is missing else "unrecognized"),
    }
    denied = kind in ("denied", "rejected")
    if shell_canary is not None:
        # Never serialize the result or search error/log text for execution proof.
        text = (result.get("textResultForLlm") if isinstance(result, dict)
                else getattr(result, "text_result_for_llm", None))
        try:
            shell_canary.lstat()
            canary_file = "present"
        except FileNotFoundError:
            canary_file = "absent"
        except OSError:
            canary_file = "unknown"
        output_observed = isinstance(text, str) and SHELL_OUTPUT_MARKER in text
        diagnostic.update(
            canary_file=canary_file,
            command_execution=(
                "observed" if output_observed or canary_file == "present" else
                "not_observed" if isinstance(text, str) and canary_file == "absent"
                else "unknown"),
        )
        # Absence alone is NOT proof. Still require explicit denial, and fail on
        # positive execution evidence even if the result claims denial.
        denied = denied and canary_file == "absent" and not output_observed
    if not denied and report is not None:
        report["denial_result"] = diagnostic
    require(denied, "explicit_native_denial_required")


def require_positive_read(result: object, decisions: list[str], report: dict) -> None:
    wire = result if isinstance(result, dict) else result.to_dict()
    if "native-readable-canary" in json.dumps(wire):
        return
    kind = wire.get("resultType")
    report["positive_read"] = {
        "kind": (kind if kind in TOOL_RESULT_KINDS else
                 "absent" if "resultType" not in wire else "unrecognized"),
        "permission": ("not_requested" if not decisions else
                       decisions[0] if len(set(decisions)) == 1 else "mixed"),
    }
    raise CheckFailure("native_file_positive_control_failed")


def protected_canary_present(result: object, marker: str, observation: dict) -> bool:
    """Inspect all returned fields before judging the outcome; never report content."""
    wire = (result.to_dict() if callable(getattr(result, "to_dict", None)) else result)
    text = wire.get("textResultForLlm") if isinstance(wire, dict) else None
    observation["text_shape"] = (
        "string" if isinstance(text, str) else "absent" if text is None else "other")
    try:
        present = marker in json.dumps(wire)
    except (TypeError, ValueError):
        observation["marker"] = "unknown"
        raise CheckFailure("explicit_native_denial_required") from None
    observation["marker"] = "present" if present else "absent"
    return present


def kill_owned_group(process: subprocess.Popen) -> None:
    """The child is a new session leader; no process enumeration or name kills."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def run_bounded(runtime: Path) -> int:
    with tempfile.TemporaryDirectory(prefix="agile-native-") as directory:
        root = Path(directory)
        for name in ("home", "tmp", "state", "workspace", "protected"):
            (root / name).mkdir()
        env = isolated_environment(root)
        env[CANARY_NAME] = uuid.uuid4().hex  # synthetic; intentionally NOT in SDK env
        process = subprocess.Popen(
            [sys.executable, "-I", str(Path(__file__).resolve()), "--run-native",
             "--runtime-path", str(runtime), "--child-root", str(root)],
            cwd=root / "workspace", env=env, start_new_session=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        )
        try:
            output, _ = process.communicate(timeout=OUTER_TIMEOUT)
        except subprocess.TimeoutExpired:
            print('{"status":"fail","check":"outer_timeout"}')
            return 1
        finally:
            # Also remove descendants if the check process exited before its SDK.
            kill_owned_group(process)
            process.communicate(timeout=5)
        try:
            report = json.loads(output)
            # Never relay arbitrary stdout/tracebacks, even on malformed child output.
            require(isinstance(report, dict), "invalid_child_report")
            require(process.returncode == 0 and report.get("status") == "pass"
                    and report.get("passed") == list(CHECKS)
                    and report.get("check") == "bounded_cleanup"
                    and report.get("sdk") == SDK_VERSION
                    and report.get("publisher_cli") == CLI_VERSION
                    and report.get("runtime") == CLI_VERSION
                    and type(report.get("protocol")) is int and report["protocol"] > 0,
                    "native_check_failed")
        except (ValueError, CheckFailure):
            # A failed child already uses fixed stage/reason codes; retain only
            # allowlisted diagnostics, not its raw output.
            report = safe_failure_report(output)
            print(json.dumps(report, sort_keys=True))
            return 1
        print(json.dumps({key: report[key] for key in (
            "status", "check", "sdk", "publisher_cli", "runtime", "protocol", "passed",
        )}, sort_keys=True))
        return 0


CHECKS = (
    "runtime_identity", "session_startup", "native_toolset",
    "plan_refusal_and_exit_only", "native_file_denial", "native_process_sandbox",
    "bounded_cleanup",
)
FAILURE_REASONS = (
    "assertion_failed", "operation_failed", "authentication_required", "timeout",
    "sandbox_host_support_required", "effective_native_process_boundary_required",
    "native_tools_missing", "bypass_request_not_denied",
    "native_hook_session_attribution_missing", "explicit_native_denial_required",
    "unexpected_authentication",
    "native_file_positive_control_failed", "protected_canary_leaked",
    "permission_session_mismatch",
)


def safe_failure_report(output: str) -> dict:
    report = {"status": "fail", "check": "invalid_child_report"}
    try:
        candidate = json.loads(output)
        if isinstance(candidate, dict) and candidate.get("check") in (
            *CHECKS, "sdk_api_prerequisite_failed", "integration_prerequisite_failed",
        ):
            report["check"] = candidate["check"]
            if candidate.get("reason") in FAILURE_REASONS:
                report["reason"] = candidate["reason"]
            if (candidate.get("check") == "native_toolset"
                    and candidate.get("reason") == "native_tools_missing"
                    and isinstance(candidate.get("missing_tools"), list)):
                report["missing_tools"] = [
                    name for name in REQUIRED_NATIVE_TOOLS
                    if name in candidate["missing_tools"]
                ]
            if (candidate.get("check") in ("native_toolset", "native_file_denial")
                    and candidate.get("reason") == "explicit_native_denial_required"
                    and isinstance(candidate.get("denial_result"), dict)):
                diagnostic = candidate["denial_result"]
                allowed = {
                    "shape": ("mapping", "object", "other"),
                    "kind": (*TOOL_RESULT_KINDS, "absent", "unrecognized"),
                }
                if candidate["check"] == "native_toolset":
                    allowed.update(
                        canary_file=("present", "absent", "unknown"),
                        command_execution=("observed", "not_observed", "unknown"),
                    )
                report["denial_result"] = {
                    key: diagnostic[key] for key, values in allowed.items()
                    if diagnostic.get(key) in values
                }
            if (candidate.get("check") == "native_file_denial"
                    and candidate.get("reason") == "native_file_positive_control_failed"
                    and isinstance(candidate.get("positive_read"), dict)):
                diagnostic = candidate["positive_read"]
                report["positive_read"] = {
                    key: diagnostic[key] for key, values in {
                        "kind": (*TOOL_RESULT_KINDS, "absent", "unrecognized"),
                        "permission": ("not_requested", "approved", "rejected", "mixed"),
                    }.items() if diagnostic.get(key) in values
                }
            if (candidate.get("check") == "native_file_denial"
                    and candidate.get("reason") in (
                        "explicit_native_denial_required", "protected_canary_leaked",
                        "permission_session_mismatch", "timeout",
                        "authentication_required", "operation_failed", "assertion_failed",
                    )
                    and isinstance(candidate.get("protected_read"), dict)):
                diagnostic = candidate["protected_read"]
                report["protected_read"] = {
                    key: diagnostic[key] for key, values in {
                        "callback": ("not_requested", "rejected_exact_read",
                                     "rejected_other", "mixed"),
                        "callback_session": ("not_requested", "match", "mismatch"),
                        "marker": ("present", "absent", "unknown"),
                        "text_shape": ("string", "absent", "other", "unknown"),
                        "allowed_directory": ("yes", "no", "unknown", "not_run",
                                              "timeout", "operation_failed"),
                        "sandbox_blocked": ("yes", "no", "unknown", "not_run",
                                            "timeout", "operation_failed"),
                    }.items() if diagnostic.get(key) in values
                }
            report["passed"] = [item for item in CHECKS
                                if item in candidate.get("passed", [])]
            if candidate.get("sdk") == SDK_VERSION and candidate.get("publisher_cli") == CLI_VERSION:
                report.update(sdk=SDK_VERSION, publisher_cli=CLI_VERSION)
            if (candidate.get("runtime") == CLI_VERSION
                    and type(candidate.get("protocol")) is int and candidate["protocol"] > 0):
                report.update(runtime=CLI_VERSION, protocol=candidate["protocol"])
    except (ValueError, TypeError):
        pass
    return report


async def native_checks(runtime: Path, root: Path) -> dict:
    # Deliberately lazy: import/ordinary test discovery never starts an SDK/loop.
    import asyncio
    import shlex
    import socket

    from copilot import BUILTIN_TOOLS_ISOLATED, CopilotClient, RuntimeConnection, ToolSet
    from copilot.client import ManagedSettings, ManagedSettingsPermissions
    from copilot.rpc import (
        ModeSetRequest, PermissionDecisionApproveOnce, PermissionDecisionReject,
        PermissionPathsAllowedCheckParams, PermissionPathsConfig,
        PermissionsConfigureParams, PermissionsSetModeRequest,
        PlanUpdateRequest, SandboxConfig, SandboxConfigUserPolicy,
        SandboxConfigUserPolicyFilesystem, SandboxConfigUserPolicyNetwork,
        ShellExecuteUserRequestedRequest, ToolsExecuteRequest,
    )
    from copilot.session_events import PermissionMode, PermissionRequestRead, SessionMode

    report = {"status": "fail", "sdk": SDK_VERSION, "publisher_cli": CLI_VERSION,
              "check": CHECKS[0], "passed": []}
    client = None
    session = None
    callback_results = []
    permission_sessions = []
    positive_read_pending = False
    positive_read_decisions = []
    protected_read_pending = False
    protected_observation = {
        "callback": "not_requested", "callback_session": "not_requested",
        "marker": "unknown", "text_shape": "unknown",
        "allowed_directory": "not_run", "sandbox_blocked": "not_run",
    }
    hook_sessions = []
    model_activity = asyncio.Event()
    plan_phase = False
    unexpected_plan_tools = []
    approve = False
    consumed = False
    binding = None

    async def bounded(awaitable):
        return await asyncio.wait_for(awaitable, RPC_TIMEOUT)

    def permission(request, context):
        permission_sessions.append(context.get("session_id"))
        decision = PermissionDecisionReject(feedback="native_check_denied")
        # SDK 1.0.24 permissions.paths.add grants directories, not individual files.
        # Approve only this typed, single-path request, never toolArgs or agentId.
        if (positive_read_pending and context.get("session_id") == session_id
                and type(request) is PermissionRequestRead
                and type(request.path) is str and request.path == str(readable_path)
                and request.resolved_path in (None, str(readable_path))
                and (request.managed_approval_required is None
                     or request.managed_approval_required is False)
                and (request.request_sandbox_bypass is None
                     or request.request_sandbox_bypass is False)
                and request.request_sandbox_bypass_reason is None
                and request.sandbox_path_grant is None):
            try:
                # The host-created fixture must still be a regular file at the
                # same canonical path, not a replacement symlink or directory.
                if readable_path.resolve(strict=True) == readable_path and readable_path.is_file():
                    decision = PermissionDecisionApproveOnce()
            except (OSError, RuntimeError):
                pass  # An unreadable/unresolvable fixture does not authorize access.
        if positive_read_pending:
            positive_read_decisions.append(
                "approved" if isinstance(decision, PermissionDecisionApproveOnce) else "rejected")
        if protected_read_pending:
            # Observation of this callback, NOT proof the runtime applied its answer.
            exact = (type(request) is PermissionRequestRead
                     and type(request.path) is str and request.path == str(protected)
                     and request.resolved_path in (None, str(protected)))
            observed = "rejected_exact_read" if exact else "rejected_other"
            previous = protected_observation["callback"]
            protected_observation["callback"] = (
                observed if previous in ("not_requested", observed) else "mixed")
            if context.get("session_id") != session_id:
                protected_observation["callback_session"] = "mismatch"
            elif protected_observation["callback_session"] == "not_requested":
                protected_observation["callback_session"] = "match"
        return decision

    async def inspect_protected_policy():
        # Public, read-only SDK 1.0.24 inspections. Neither is a per-tool denial
        # verdict. Keep each bounded and never replace the original probe failure.
        for key, operation, field in (
            ("allowed_directory",
             lambda: session.rpc.permissions.paths.is_path_within_allowed_directories(
                 PermissionPathsAllowedCheckParams(path=str(protected))), "allowed"),
            ("sandbox_blocked", session.rpc.sandbox.get_enforcement_status, "blocked"),
        ):
            try:
                result = await bounded(operation())
                value = getattr(result, field, None)
                protected_observation[key] = (
                    "yes" if value is True else "no" if value is False else "unknown")
            except Exception as exc:
                protected_observation[key] = (
                    "timeout" if isinstance(exc, TimeoutError) else "operation_failed")

    def pre_tool(data, context):
        hook_sessions.append((data.get("sessionId"), context.get("session_id")))
        if plan_phase and data.get("toolName") != "exit_plan_mode":
            unexpected_plan_tools.append(data.get("toolName"))
            return {"permissionDecision": "deny",
                    "permissionDecisionReason": "native_check_denied"}
        return None  # Never a blanket approval or command-prefix allowlist.

    def on_event(event):
        kind = getattr(event.type, "value", event.type)
        if kind in ("assistant.turn_start", "assistant.message", "assistant.message_delta"):
            model_activity.set()

    async def exit_plan(_request, context):
        nonlocal consumed
        actual = await bounded(session.rpc.plan.read())
        actual_binding = (
            context.get("session_id"), actual.path,
            hashlib.sha256((actual.content or "").encode("utf-8")).hexdigest(),
        )
        allowed = (approve and not consumed and actual.exists
                   and actual_binding == binding
                   and "exit_only" in _request.get("actions", []))
        callback_results.append(bool(allowed))
        if allowed:
            consumed = True
            return {"approved": True, "selectedAction": "exit_only"}
        return {"approved": False, "feedback": "native_check_refused"}

    try:
        workspace = root / "workspace"
        protected = root / "protected" / "control-plane.txt"
        protected_marker = uuid.uuid4().hex
        protected.write_text(protected_marker, encoding="utf-8")
        (workspace / "readable.txt").write_text("native-readable-canary", encoding="utf-8")
        readable_path = (workspace / "readable.txt").resolve(strict=True)
        client = CopilotClient(
            connection=RuntimeConnection.for_stdio(path=str(runtime)),
            mode="empty", env=isolated_environment(root), github_token=None,
            use_logged_in_user=False, base_directory=str(root / "state"),
            builtin_plugin_directories=[], working_directory=str(workspace),
            log_level="error",
        )
        await bounded(client.start())
        identity = await bounded(client.get_status())
        require(identity.version == CLI_VERSION, "runtime_version_mismatch")
        require(type(identity.protocol_version) is int and identity.protocol_version > 0,
                "runtime_protocol_missing")
        report.update(runtime=identity.version, protocol=identity.protocol_version)
        report["passed"].append(report["check"])

        report["check"] = "session_startup"
        auth = await bounded(client.get_auth_status())
        require(not auth.isAuthenticated, "unexpected_authentication")
        session_id = str(uuid.uuid4())
        session = await bounded(client.create_session(
            session_id=session_id, working_directory=str(workspace),
            config_directory=str(root / "state"), enable_config_discovery=False,
            mcp_servers={}, disabled_mcp_servers=["*"],
            plugin_directories=[], agent_directories=[],
            # SDK 1.0.24 customization-locations: a direct SKILL.md bundle is
            # supported. Trust only this directory, not the core plugin/skills root.
            skill_directories=[str(TRUSTED_SKILL_DIRECTORY)],
            instruction_directories=[], hook_directories=[], enable_skills=True,
            available_tools=ToolSet().add_builtin([*BUILTIN_TOOLS_ISOLATED, "view"]),
            on_permission_request=permission, hooks={"on_pre_tool_use": pre_tool},
            on_user_input_request=refuse_user_input,
            on_exit_plan_mode_request=exit_plan, on_event=on_event,
            managed_settings=ManagedSettings(permissions=ManagedSettingsPermissions(
                disable_bypass_permissions_mode="disable",
                disable_assisted_permissions_mode=True, limit_to=[],
            )),
            sandbox_config=SandboxConfig(
                enabled=True, allow_bypass=False, allow_dev_tool_access=False,
                user_policy=SandboxConfigUserPolicy(
                    filesystem=SandboxConfigUserPolicyFilesystem(
                        denied_paths=[str(root / "protected")]),
                    network=SandboxConfigUserPolicyNetwork(
                        allow_outbound=False, allow_local_network=False),
                ),
            ),
        ))
        require(session.session_id == session_id, "session_identity_mismatch")
        await bounded(session.rpc.permissions.configure(PermissionsConfigureParams(
            approve_all_read_permission_requests=False,
            approve_all_tool_permission_requests=False,
            paths=PermissionPathsConfig(
                unrestricted=False, include_temp_directory=False,
                workspace_path=str(workspace)),
        )))
        report["passed"].append(report["check"])

        report["check"] = "native_toolset"
        # exit_plan_mode is mode-dependent; query a PLAN snapshot, not the
        # initial interactive tool set. No prompt or automatic continuation.
        await bounded(session.rpc.mode.set(ModeSetRequest(mode=SessionMode.PLAN)))
        require(await bounded(session.rpc.mode.get()) == SessionMode.PLAN,
                "native_plan_mode_required")
        await bounded(session.rpc.skills.ensure_loaded())
        await bounded(session.rpc.tools.initialize_and_validate())
        metadata_result = await bounded(session.rpc.tools.get_current_metadata())
        names = {tool.name for tool in metadata_result.tools or []}
        # ToolSet is a filter, not registration; metadata is the current snapshot.
        require_native_tools(names, report)
        require(names <= set(BUILTIN_TOOLS_ISOLATED) | {"view"},
                "unexpected_worker_capability")
        require(all(not tool.mcp_server_name for tool in metadata_result.tools),
                "ambient_mcp_tools")
        skills = await bounded(session.rpc.skills.list())
        require_trusted_skill(skills.skills)
        # Unsupported RPC/auth/timeout is a failure, never a substitute for denial.
        bypass = await bounded(session.rpc.permissions.set_mode(
            PermissionsSetModeRequest(mode=PermissionMode.ALLOW_ALL)))
        require(not bypass.success and bypass.mode == PermissionMode.MANUAL,
                "bypass_request_not_denied")
        mode = await bounded(session.rpc.permissions.get_mode())
        require(mode.mode == PermissionMode.MANUAL, "bypass_mode_not_denied")
        # Probe the direct host RPC; ToolSet filtering is not a permission
        # guarantee. An unsupported-tool/auth failure is NOT explicit denial.
        shell_canary = workspace / f".native-shell-{uuid.uuid4().hex}"
        require(not shell_canary.exists(), "shell_canary_not_fresh")
        # Split the fixed output marker so an echoed command is not execution
        # evidence. Write at most one small file in the owned temporary workspace.
        shell_command = (
            "printf '%s%s' native-unexpected- shell > " + shlex.quote(str(shell_canary))
            + "; printf '%s%s' native-unexpected- shell"
        )
        shell_denied = await bounded(session.rpc.tools.execute(ToolsExecuteRequest(
            name="bash", arguments={"command": shell_command})))
        require_denial(shell_denied, report, shell_canary=shell_canary)
        report["passed"].append(report["check"])

        report["check"] = "plan_refusal_and_exit_only"
        plan_phase = True
        await bounded(session.rpc.mode.set(ModeSetRequest(mode=SessionMode.PLAN)))
        await bounded(session.rpc.plan.update(PlanUpdateRequest(content=PLAN)))
        actual = await bounded(session.rpc.plan.read())
        require(actual.exists and actual.content == PLAN and bool(actual.path),
                "native_plan_roundtrip_failed")
        binding = (session_id, actual.path, hashlib.sha256(PLAN.encode("utf-8")).hexdigest())
        request = ToolsExecuteRequest(name="exit_plan_mode", arguments={
            "summary": "Synthetic pre-model check. Do not execute.",
        })
        await bounded(session.rpc.tools.execute(request))
        require(callback_results == [False], "native_refusal_callback_missing")
        require(await bounded(session.rpc.mode.get()) == SessionMode.PLAN,
                "refusal_left_plan_mode")
        approve = True
        await bounded(session.rpc.plan.update(PlanUpdateRequest(content=PLAN + "Changed.\n")))
        await bounded(session.rpc.tools.execute(request))
        require(callback_results == [False, False], "changed_plan_not_refused")
        require(await bounded(session.rpc.mode.get()) == SessionMode.PLAN,
                "changed_plan_left_plan_mode")
        await bounded(session.rpc.plan.update(PlanUpdateRequest(content=PLAN)))
        await bounded(session.rpc.tools.execute(request))
        require(callback_results == [False, False, True] and consumed,
                "exit_only_callback_missing")
        require(await bounded(session.rpc.mode.get()) == SessionMode.INTERACTIVE,
                "exit_only_mode_not_interactive")
        try:
            await asyncio.wait_for(model_activity.wait(), timeout=1)
        except TimeoutError:
            pass
        require(not model_activity.is_set() and not unexpected_plan_tools,
                "automatic_execution_observed")
        require(hook_sessions and all(pair == (session_id, session_id)
                                     for pair in hook_sessions),
                "native_hook_session_attribution_missing")
        plan_phase = False
        report["passed"].append(report["check"])

        report["check"] = "native_file_denial"
        positive_read_pending = True
        try:
            readable = await bounded(session.rpc.tools.execute(ToolsExecuteRequest(
                name="view", arguments={"path": str(readable_path)})))
        finally:
            positive_read_pending = False
        require_positive_read(readable, positive_read_decisions, report)
        report["protected_read"] = protected_observation
        protected_read_pending = True
        try:
            try:
                denied = await bounded(session.rpc.tools.execute(ToolsExecuteRequest(
                    name="view", arguments={"path": str(protected)})))
            finally:
                protected_read_pending = False
            # A leaked marker is a hard failure even for failure/denied/rejected.
            # Use the original marker, not a possibly changed file after execution.
            require(not protected_canary_present(denied, protected_marker, protected_observation),
                    "protected_canary_leaked")
            require_denial(denied, report)
            require(permission_sessions and all(value == session_id for value in permission_sessions),
                    "permission_session_mismatch")
        except Exception:
            await inspect_protected_policy()
            raise
        report["passed"].append(report["check"])

        report["check"] = "native_process_sandbox"
        support = await bounded(client.rpc.sandbox.get_host_support())
        capabilities = {item.name: item.supported for item in support.capabilities}
        require(support.supported and capabilities.get("shell") is True
                and capabilities.get("denied_paths") is True,
                "sandbox_host_support_required")
        # This is a trusted host RPC, NOT a worker shell grant. Actual denial of
        # readable synthetic host data + a reachable host listener falsifies a
        # sandbox option silently being ignored. No public Internet is contacted.
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(4)
            port = listener.getsockname()[1]
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                pass
            probe = (
                "import os,pathlib,socket\n"
                f"assert {CANARY_NAME!r} not in os.environ\n"
                f"p=pathlib.Path({str(protected)!r})\n"
                "try:\n p.read_bytes()\n"
                "except (PermissionError,FileNotFoundError):\n pass\n"
                "else:\n raise AssertionError('file_boundary')\n"
                f"try:\n s=socket.create_connection(('127.0.0.1',{port}),timeout=1)\n"
                "except OSError:\n pass\n"
                "else:\n s.close(); raise AssertionError('network_boundary')\n"
                "print('native-sandbox-check-ok')\n"
            )
            result = await bounded(session.rpc.shell.execute_user_requested(
                ShellExecuteUserRequestedRequest(
                    command="/usr/bin/python3 -I -c " + shlex.quote(probe),
                    request_id=str(uuid.uuid4()))))
            require(result.success and result.exit_code == 0
                    and "native-sandbox-check-ok" in result.output,
                    "effective_native_process_boundary_required")
        require(not model_activity.is_set(), "unexpected_model_activity")
        report["passed"].append(report["check"])
        report["status"] = "pass"
    except Exception as exc:
        reason = "assertion_failed" if isinstance(exc, CheckFailure) else "operation_failed"
        if isinstance(exc, CheckFailure) and str(exc) in FAILURE_REASONS:
            reason = str(exc)
        if isinstance(exc, TimeoutError):
            reason = "timeout"
        elif not isinstance(exc, CheckFailure) and any(
            word in str(exc).lower() for word in ("authentication", "not logged in", "unauthorized")
        ):
            reason = "authentication_required"
        report["reason"] = reason
    finally:
        cleanup_failed = False
        if session is not None:
            for operation in (session.abort, session.disconnect):
                try:
                    await bounded(operation())
                except Exception:
                    cleanup_failed = True
        if client is not None:
            try:
                await bounded(client.stop())
            except Exception:
                cleanup_failed = True
                try:
                    await bounded(client.force_stop())
                except Exception:
                    pass  # The outer process group deadline remains authoritative.
        if cleanup_failed:
            report.update(status="fail", check="bounded_cleanup", reason="operation_failed")
        elif report["status"] == "pass":
            report["check"] = "bounded_cleanup"
            report["passed"].append("bounded_cleanup")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-native", action="store_true")
    parser.add_argument("--runtime-path", type=Path)
    parser.add_argument("--child-root", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not args.run_native or args.runtime_path is None:
        parser.error("explicit --run-native and --runtime-path are required; no SDK started")
    try:
        check_prerequisites(args.runtime_path)
        if args.child_root is None:
            return run_bounded(args.runtime_path)
        import asyncio
        report = asyncio.run(native_checks(args.runtime_path, args.child_root))
        print(json.dumps(report, sort_keys=True))
        return 0 if report["status"] == "pass" else 1
    except CheckFailure as exc:
        print(json.dumps({"status": "fail", "check": str(exc)}))
        return 1
    except ImportError:
        print('{"status":"fail","check":"sdk_api_prerequisite_failed"}')
        return 1
    except Exception:
        print('{"status":"fail","check":"integration_prerequisite_failed"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

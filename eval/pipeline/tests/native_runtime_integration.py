"""Opt-in, pre-model integration checks for SDK 1.0.28 / publisher CLI 1.0.105.

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
from dataclasses import dataclass
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import unicodedata
import uuid


SDK_VERSION = "1.0.28"
CLI_VERSION = "1.0.105"
RPC_TIMEOUT = 15
PROCESS_TIMEOUT = 30
PROCESS_PHASE_TIMEOUT = 100
PROCESS_READY_TIMEOUT = 5
PROCESS_DEATH_TIMEOUT = 5
PROCESS_CANCEL_DELAY = 1
PROCESS_CANCEL_TIMEOUT = 2
OUTER_TIMEOUT = 180
CANARY_NAME = "AGILE_NATIVE_AMBIENT_CANARY"
SHELL_OUTPUT_MARKER = "native-unexpected-shell"
# SDK 1.0.28 generated/rpc.py: ToolResultType (not all kinds are denials).
TOOL_RESULT_KINDS = ("denied", "failure", "rejected", "success", "timeout")
POSITIVE_READ_CALL_ID = "native-positive-read"
PROTECTED_READ_CALL_ID = "native-protected-read"
COMPARISON_CASES = ("permit", "native_deny", "missing", "callback_deny")
# Deliberately independent of the operating pins: upgrades need new qualification.
FILE_POLICY_PIN = ("1.0.28", "1.0.105", 3)
FILE_POLICY_ERROR = "Is a sandbox denied path."
MISSING_FILE_ERROR = "Path does not exist"
ERROR_INPUT_LIMIT = 4096
ERROR_TEXT_LIMIT = 2048
CHILD_REPORT_LIMIT = 32768
ERROR_SUPPRESSIONS = (
    "context_missing", "malformed", "oversized", "empty",
    "credential_material", "unrecognized_path",
)
# Defense in depth, NOT a complete secret detector. The primary constraint is
# the credential-free child environment and host-owned synthetic fixtures.
CREDENTIAL_ENV_NAME = re.compile(
    r"token|secret|password|passwd|credential|api_?key|private_?key|access_?key|"
    r"(?:^|_)key(?:$|_)|authorization|connection_?string|sas", re.IGNORECASE)
CREDENTIAL_MATERIAL = re.compile(
    r"\b(?:bearer|basic)\s+\S+|"
    r"\b[\w-]*(?:token|secret|password|passwd|credential|api[_-]?key|"
    r"access[_-]?key|account[_-]?key|private[_-]?key|authorization|signature|sig)"
    r"[\w-]*[\"']?\s*[:=]\s*\S+|"
    r"[a-z][a-z0-9+.-]*://[^\s/]+@|"
    r"-----BEGIN [^\r\n]*PRIVATE KEY-----|"
    r"\b(?:gh[pousr]_|github_pat_|sk-|xox[baprs]-|AKIA|ASIA|AIza)[a-z0-9_-]+|"
    r"\beyJ[a-z0-9_-]+\.[a-z0-9_-]+\.[a-z0-9_-]+",
    re.IGNORECASE,
)
ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))")
# SDK 1.0.28 session_events.RemediationAction; codes are open strings, not enums.
COMPLETION_REMEDIATIONS = (
    "sign_in", "switch_account", "show_account", "review_sandbox_policy",
    "allow_sandbox_outbound", "rewind_conversation",
)
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
    """Only fixed, non-sensitive failure codes are used as exception messages."""


def _event_field(value: object, name: str, wire_name: str | None = None) -> object:
    # Read individual public fields; never serialize an event or retain its payload.
    return (value.get(wire_name or name) if isinstance(value, dict)
            else getattr(value, name, None))


class _ProtectedReadCompletion:
    """One bounded summary, never an event collection or an authorization verdict."""

    __slots__ = ("active", "diagnostic")

    def __init__(self) -> None:
        self.active = False
        self.diagnostic = {
            "event": "not_seen", "correlation": "absent", "success": "unknown",
            "error": "unknown", "code": "unknown", "remediation": "absent",
        }

    def observe(self, event: object) -> None:
        kind = _event_field(event, "type")
        kind = getattr(kind, "value", kind)
        if (not self.active or kind != "tool.execution_complete"
                or self.diagnostic["correlation"] == "match"):
            return
        self.diagnostic["event"] = "seen"
        data = _event_field(event, "data")
        call_id = _event_field(data, "tool_call_id", "toolCallId")
        if type(call_id) is str and call_id == PROTECTED_READ_CALL_ID:
            correlation = "match"
        elif call_id is None or (type(call_id) is str and not call_id):
            correlation = "absent"
        else:
            correlation = "mismatch" if type(call_id) is str else "unrecognized"
        # A match supersedes other observations; unrelated/uncorrelated errors
        # never become protected-read details. First match wins, including late
        # duplicates. Nonmatches have deterministic precedence, not last-wins.
        ranks = ("absent", "unrecognized", "mismatch", "match")
        if ranks.index(correlation) > ranks.index(self.diagnostic["correlation"]):
            self.diagnostic["correlation"] = correlation
        if correlation != "match":
            return
        success = _event_field(data, "success")
        error = _event_field(data, "error")
        remediation = _event_field(error, "remediation")
        remediation = getattr(remediation, "value", remediation)
        self.diagnostic.update(
            success=success if type(success) is bool else "unknown",
            error="absent" if error is None else "present",
            code="absent" if _event_field(error, "code") is None else "present",
            remediation=(
                remediation if type(remediation) is str
                and remediation in COMPLETION_REMEDIATIONS else
                "absent" if remediation is None else "unrecognized"),
        )


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


def _scrub_native_error(text: object, *, root: Path | None,
                        protected_marker: str | None) -> dict:
    """One synthetic error string, rechecked by the parent; never stringify objects."""
    if root is None or not protected_marker:
        return {"suppressed": "context_missing"}
    if type(text) is not str:
        return {"suppressed": "malformed"}
    if len(text) > ERROR_INPUT_LIMIT:
        return {"suppressed": "oversized"}
    # Scan before normalization, path replacement or truncation, then scan again
    # after removing controls so split tokens/canaries cannot be reconstructed.
    clean = "".join(char for char in ANSI_ESCAPE.sub("", text)
                    if unicodedata.category(char)[0] != "C" and char not in "\u2028\u2029")
    secrets = tuple(value for name, value in os.environ.items()
                    if value and CREDENTIAL_ENV_NAME.search(name))
    for candidate in (text, clean):
        require(protected_marker not in candidate, "protected_canary_leaked")
        if (any(value in candidate for value in secrets)
                or CREDENTIAL_MATERIAL.search(candidate)):
            return {"suppressed": "credential_material"}
    paths = [
        (str(root), "[synthetic]"),
        (str(Path(__file__).resolve().parents[3]), "[repo]"),
        (tempfile.gettempdir(), "[temp]"),
    ]
    for name, label in (
        ("GITHUB_WORKSPACE", "[repo]"), ("RUNNER_WORKSPACE", "[runner]"),
        ("RUNNER_TEMP", "[temp]"), ("HOME", "[home]"), ("USERPROFILE", "[home]"),
        ("TMPDIR", "[temp]"), ("TEMP", "[temp]"), ("TMP", "[temp]"),
    ):
        value = os.environ.get(name)
        if value and Path(value).is_absolute():
            paths.append((value, label))
    # Longest first so /tmp does not consume the more specific synthetic root.
    for path, label in sorted(paths, key=lambda item: len(item[0]), reverse=True):
        clean = clean.replace(path, label).replace(path.replace("\\", "/"), label)
    # Unrecognized absolute paths are not assumed safe runner paths.
    if re.search(r"(?<![\w\]/])/(?!/)[\w.]|[a-zA-Z]:[\\/]|\\\\", clean):
        return {"suppressed": "unrecognized_path"}
    clean = clean.replace("::", ": :").strip()
    if not clean:
        return {"suppressed": "empty"}
    if len(clean) > ERROR_INPUT_LIMIT:
        return {"suppressed": "oversized"}
    # Keep the bounded candidate intact across the private pipe: the parent
    # must scan its own credential values BEFORE any truncation could split one.
    return {"text": clean}


def _protected_error(result: object, *, root: Path, protected_marker: str) -> dict:
    # Pinned ToolsApi.execute returns raw wire JSON, not an arbitrary SDK object.
    # Never inspect/serialize content, metadata, events, arguments or session logs.
    if type(result) is not dict or result.get("resultType") != "failure":
        return {"suppressed": "malformed"}
    return _result_error(result, root=root, protected_marker=protected_marker)


def _result_error(result: dict, *, root: Path, protected_marker: str) -> dict:
    """Scrub only the two pinned error fields, never any successful read contents."""
    error, fallback = result.get("error"), result.get("textResultForLlm")
    for value in (error, fallback):
        if value is not None and type(value) is not str:
            return {"suppressed": "malformed"}
        if type(value) is str and len(value) > ERROR_INPUT_LIMIT:
            return {"suppressed": "oversized"}
    source = "error" if error and error.strip() else "textResultForLlm"
    scrubbed = _scrub_native_error(
        error if source == "error" else fallback or "",
        root=root, protected_marker=protected_marker)
    return {"source": source, **scrubbed} if "text" in scrubbed else scrubbed


def require_denial(result: object, report: dict | None = None, *,
                   shell_canary: Path | None = None) -> None:
    # 1.0.28 ToolsApi.execute is annotated as a dataclass but returns wire JSON.
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


@dataclass(frozen=True)
class _FilePolicyControl:
    """Private, same-run evidence; never reconstructed from sanitized diagnostics."""

    case: str
    session_id: str
    path: Path
    denied_paths: tuple[str, ...]
    result: dict
    callback: str
    callback_other: bool
    callback_session_mismatch: bool
    allowed_directory: bool
    tool: str = "view"


@dataclass(frozen=True)
class _QualifiedFilePolicy:
    """Observed policy refusal, NOT a publisher-typed denial or internal attestation."""

    pin: tuple[str, str, int]
    root: Path
    comparison_marker: str
    protected_marker: str


def _file_result(result: object, markers: tuple[str, ...]) -> dict:
    # Canary first, including unrecognized/nested fields. Do not normalize errors
    # or consult the public redactor to classify a result.
    try:
        serialized = json.dumps(result)
    except (TypeError, ValueError, RecursionError):
        raise CheckFailure("file_policy_unqualified") from None
    require(not any(marker in serialized for marker in markers), "protected_canary_leaked")
    require(len(serialized) <= CHILD_REPORT_LIMIT and type(result) is dict
            and type(result.get("resultType")) is str
            and result["resultType"] in TOOL_RESULT_KINDS
            and type(result.get("textResultForLlm")) is str
            and (result.get("error") is None or type(result["error"]) is str),
            "file_policy_unqualified")
    return result


def _require_file_pin(sdk: str, identity: object) -> tuple[str, str, int]:
    pin = (sdk, getattr(identity, "version", None),
           getattr(identity, "protocol_version", None))
    require(type(pin[0]) is str and type(pin[1]) is str and type(pin[2]) is int
            and pin == FILE_POLICY_PIN, "file_policy_unqualified")
    return pin


def qualify_file_policy(sdk: str, identity: object, root: Path,
                        controls: list[_FilePolicyControl]) -> _QualifiedFilePolicy:
    """Require all four completed controls on this candidate, never the older run."""
    pin = _require_file_pin(sdk, identity)
    target = root / "workspace" / "comparison.txt"
    protected = root / "protected" / "control-plane.txt"
    missing = root / "workspace" / "comparison-missing.txt"
    require(root.is_absolute() and root.resolve(strict=True) == root
            and target.resolve(strict=True) == target and target.is_file()
            and protected.resolve(strict=True) == protected and protected.is_file()
            and not missing.exists() and not missing.is_symlink(),
            "file_policy_unqualified")
    marker = target.read_text(encoding="utf-8")
    protected_marker = protected.read_text(encoding="utf-8")
    require(bool(marker) and bool(protected_marker) and marker != protected_marker,
            "file_policy_unqualified")
    require(type(controls) is list and len(controls) == len(COMPARISON_CASES)
            and all(type(item) is _FilePolicyControl for item in controls),
            "file_policy_unqualified")
    require(tuple(item.case for item in controls) == COMPARISON_CASES
            and all(type(item.session_id) is str and item.session_id for item in controls)
            and len({item.session_id for item in controls}) == len(COMPARISON_CASES),
            "file_policy_unqualified")
    for item in controls:
        expected_path = missing if item.case == "missing" else target
        expected_deny = (str(target),) if item.case == "native_deny" else ()
        wire = _file_result(
            item.result, (protected_marker,) if item.case == "permit"
            else (marker, protected_marker))
        require(item.tool == "view" and item.path == expected_path
                and item.denied_paths == expected_deny
                and item.allowed_directory is True
                and item.callback_other is False and item.callback_session_mismatch is False,
                "file_policy_unqualified")
        if item.case == "permit":
            require(wire["resultType"] == "success"
                    and marker in wire["textResultForLlm"]
                    and wire.get("error") is None and item.callback == "approved",
                    "file_policy_unqualified")
        elif item.case == "native_deny":
            require(wire["resultType"] == "failure"
                    and wire.get("error") == FILE_POLICY_ERROR
                    and item.callback == "not_requested",
                    "file_policy_unqualified")
        elif item.case == "missing":
            require(wire["resultType"] == "failure"
                    and wire.get("error") == MISSING_FILE_ERROR
                    and item.callback in ("not_requested", "approved"),
                    "file_policy_unqualified")
        else:
            require(wire["resultType"] == "denied" and item.callback == "rejected"
                    and wire.get("error") not in (FILE_POLICY_ERROR, MISSING_FILE_ERROR),
                    "file_policy_unqualified")
    return _QualifiedFilePolicy(pin, root, marker, protected_marker)


def require_qualified_file_refusal(result: object, qualification: _QualifiedFilePolicy,
                                   sdk: str, identity: object, *, tool: str, target: Path,
                                   denied_paths: tuple[str, ...]) -> None:
    """Only the fixed protected-file probe may reuse the fresh comparison."""
    require(type(qualification) is _QualifiedFilePolicy, "file_policy_unqualified")
    _file_result(result, (qualification.comparison_marker, qualification.protected_marker))
    comparison = qualification.root / "workspace" / "comparison.txt"
    missing = comparison.with_name("comparison-missing.txt")
    require(qualification.pin == _require_file_pin(sdk, identity)
            and tool == "view"
            and target == qualification.root / "protected" / "control-plane.txt"
            and denied_paths == (str(target),)
            and target.resolve(strict=True) == target and target.is_file()
            and target.read_text(encoding="utf-8") == qualification.protected_marker
            and comparison.resolve(strict=True) == comparison and comparison.is_file()
            and comparison.read_text(encoding="utf-8") == qualification.comparison_marker
            and not missing.exists() and not missing.is_symlink(),
            "file_policy_unqualified")
    require(result["resultType"] == "failure" and result.get("error") == FILE_POLICY_ERROR,
            "explicit_native_denial_required")


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
        # Retain the ORIGINAL marker outside the child. Never trust a marker
        # supplied in its report or reread a potentially changed fixture afterward.
        protected_marker = uuid.uuid4().hex
        (root / "protected" / "control-plane.txt").write_text(protected_marker, encoding="utf-8")
        comparison_marker = uuid.uuid4().hex
        (root / "workspace" / "comparison.txt").write_text(comparison_marker, encoding="utf-8")
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
            require(len(output) <= CHILD_REPORT_LIMIT, "invalid_child_report")
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
        except (ValueError, RecursionError, CheckFailure):
            # A failed child already uses fixed stage/reason codes; retain only
            # allowlisted diagnostics, not its raw output.
            report = safe_failure_report(
                output, root=root, protected_marker=protected_marker,
                comparison_marker=comparison_marker)
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
    "comparison_control_failed", "comparison_malformed_result",
    "comparison_canary_leaked", "comparison_cleanup_failed",
    "file_policy_unqualified",
    "process_descriptor_incompatible", "process_permission_mismatch",
    "process_start_missing", "process_result_invalid", "process_fixture_changed",
    "process_network_positive_failed", "process_network_negative_failed",
    "process_identity_invalid", "process_orphan_alive", "process_cleanup_failed",
    "process_completed_before_cancel", "process_deadline_exceeded", "process_operation_timeout",
)


def safe_failure_report(output: str, *, root: Path | None = None,
                        protected_marker: str | None = None,
                        comparison_marker: str | None = None) -> dict:
    report = {"status": "fail", "check": "invalid_child_report"}
    if type(output) is not str or len(output) > CHILD_REPORT_LIMIT:
        return report
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
                completion = candidate.get("protected_completion")
                if isinstance(completion, dict):
                    # Validate again at the subprocess boundary. In particular,
                    # JSON 0/1 must never pass as boolean success.
                    safe = {
                        key: completion[key] for key, values in {
                            "event": ("seen", "not_seen"),
                            "correlation": ("match", "mismatch", "absent", "unrecognized"),
                            "success": ("unknown",),
                            "error": ("present", "absent", "unknown"),
                            "code": ("present", "absent", "unknown"),
                            "remediation": (*COMPLETION_REMEDIATIONS, "absent", "unrecognized"),
                        }.items() if type(completion.get(key)) is str
                        and completion[key] in values
                    }
                    if safe.get("event") == "seen" and safe.get("correlation") == "match":
                        if type(completion.get("success")) is bool:
                            safe["success"] = completion["success"]
                    else:
                        # Even forged child output cannot attach another call's
                        # error/remediation to the protected request.
                        safe.update(success="unknown", error="unknown",
                                    code="unknown", remediation="absent")
                        if safe.get("correlation") == "match":
                            safe.pop("correlation")
                    report["protected_completion"] = safe
                if (candidate.get("status") == "fail"
                        and candidate.get("reason") == "explicit_native_denial_required"
                        and report.get("denial_result") == {"shape": "mapping", "kind": "failure"}
                        and report["protected_read"].get("marker") == "absent"
                        and "protected_error" in candidate):
                    error = candidate["protected_error"]
                    safe_error = {"suppressed": "malformed"}
                    if type(error) is dict:
                        if (set(error) == {"suppressed"}
                                and error["suppressed"] in ERROR_SUPPRESSIONS):
                            safe_error = {"suppressed": error["suppressed"]}
                        elif (set(error) == {"source", "text"}
                              and error["source"] in ("error", "textResultForLlm")):
                            try:
                                safe_error = _scrub_native_error(
                                    error["text"], root=root, protected_marker=protected_marker)
                            except CheckFailure:
                                report["reason"] = "protected_canary_leaked"
                                report["protected_read"]["marker"] = "present"
                                safe_error = None
                            if safe_error is not None and "text" in safe_error:
                                safe_error["source"] = error["source"]
                                safe_error["text"] = safe_error["text"][:ERROR_TEXT_LIMIT]
                    if safe_error is not None:
                        report["protected_error"] = safe_error
            comparison = candidate.get("file_comparison")
            if candidate.get("status") == "fail" and type(comparison) is dict:
                safe_cases = {}
                for case in COMPARISON_CASES:
                    diagnostic = comparison.get(case)
                    if type(diagnostic) is not dict:
                        continue
                    safe = {
                        key: diagnostic[key] for key, values in {
                            "kind": TOOL_RESULT_KINDS,
                            "denied_paths": ("empty", "exact_target"),
                            "target": ("same_file", "absent_file"),
                            "allowed_directory": ("yes", "no", "unknown"),
                            "callback": ("not_requested", "approved", "rejected", "mixed"),
                        }.items() if type(diagnostic.get(key)) is str
                        and diagnostic[key] in values
                    }
                    for key in ("marker_present", "read_success", "callback_other",
                                "callback_session_mismatch", "sandbox_error_exact"):
                        if type(diagnostic.get(key)) is bool:
                            safe[key] = diagnostic[key]
                    error = diagnostic.get("error")
                    if type(error) is dict:
                        safe_error = {"suppressed": "malformed"}
                        if set(error) == {"suppressed"} and error["suppressed"] in ERROR_SUPPRESSIONS:
                            safe_error = error
                        elif (set(error) == {"source", "text"}
                              and error["source"] in ("error", "textResultForLlm")):
                            try:
                                # Positive contents never enter diagnostics. Both original
                                # parent-held markers remain forbidden in every error.
                                safe_error = _scrub_native_error(
                                    error["text"], root=root, protected_marker=comparison_marker)
                                if "text" in safe_error:
                                    safe_error = _scrub_native_error(
                                        safe_error["text"], root=root,
                                        protected_marker=protected_marker)
                            except CheckFailure:
                                report["reason"] = "comparison_canary_leaked"
                                safe_error = {"suppressed": "malformed"}
                            if "text" in safe_error:
                                safe_error.update(source=error["source"],
                                                  text=safe_error["text"][:ERROR_TEXT_LIMIT])
                        safe["error"] = safe_error
                    safe_cases[case] = safe
                report["file_comparison"] = safe_cases
                if candidate.get("comparison_cleanup") in ("complete", "failed"):
                    report["comparison_cleanup"] = candidate["comparison_cleanup"]
            report["passed"] = [item for item in CHECKS
                                if item in candidate.get("passed", [])]
            process_controls = candidate.get("process_controls")
            if (candidate.get("status") == "fail"
                    and candidate.get("check") == "native_process_sandbox"
                    and candidate.get("reason") == "process_descriptor_incompatible"
                    and type(candidate.get("process_descriptor")) is dict):
                report["process_descriptor"] = _safe_process_descriptor(
                    candidate["process_descriptor"])
            if candidate.get("check") == "native_process_sandbox" and type(process_controls) is dict:
                report["process_controls"] = {
                    case: process_controls[case] for case in PROCESS_CASES
                    if type(process_controls.get(case)) is str
                    and process_controls[case] in ("started", "complete", "cancelled", "timed_out")
                }
            network = candidate.get("process_network")
            if candidate.get("check") == "native_process_sandbox" and type(network) is dict:
                report["process_network"] = {
                    case: network[case] for case in ("network_permit", "network_deny")
                    if type(network.get(case)) is str and network[case] in NETWORK_OUTCOMES
                }
            if candidate.get("sdk") == SDK_VERSION and candidate.get("publisher_cli") == CLI_VERSION:
                report.update(sdk=SDK_VERSION, publisher_cli=CLI_VERSION)
            if (candidate.get("runtime") == CLI_VERSION
                    and type(candidate.get("protocol")) is int and candidate["protocol"] > 0):
                report.update(runtime=CLI_VERSION, protocol=candidate["protocol"])
    except (ValueError, TypeError, RecursionError):
        pass
    return report


async def compare_native_file_policy(client, root: Path, report: dict, bounded, on_event, *,
                                    controls: list[_FilePolicyControl] | None = None) -> dict:
    """Collect four controls; private evidence is released only after all cleanup."""
    from copilot import ToolSet
    from copilot.client import ManagedSettings, ManagedSettingsPermissions
    from copilot.rpc import (
        ModeSetRequest, PermissionDecisionApproveOnce, PermissionDecisionReject,
        PermissionPathsAllowedCheckParams, PermissionPathsConfig, PermissionsConfigureParams,
        SandboxConfig, SandboxConfigUserPolicy, SandboxConfigUserPolicyFilesystem,
        SandboxConfigUserPolicyNetwork, ToolsExecuteRequest,
    )
    from copilot.session_events import PermissionMode, PermissionRequestRead, SessionMode

    workspace = root / "workspace"
    target = workspace / "comparison.txt"
    require(target.is_absolute() and target.resolve(strict=True) == target and target.is_file(),
            "comparison_control_failed")
    marker = target.read_text(encoding="utf-8")
    protected_marker = (root / "protected" / "control-plane.txt").read_text(encoding="utf-8")
    missing = workspace / "comparison-missing.txt"
    require(bool(marker) and not missing.exists() and not missing.is_symlink(),
            "comparison_control_failed")
    report["file_comparison"] = {}
    report["comparison_cleanup"] = "complete"

    async def run_case(case):
        # A separate closure/window per owned session: a late callback can never
        # borrow the next case's grant or contaminate its observation.
        session_id = str(uuid.uuid4())
        session = None
        active = False
        path = missing if case == "missing" else target
        observation = {
            "denied_paths": "exact_target" if case == "native_deny" else "empty",
            "target": "absent_file" if case == "missing" else "same_file",
            "callback": "not_requested", "callback_other": False,
            "callback_session_mismatch": False,
        }
        report["file_comparison"][case] = observation

        def permission(request, context):
            decision = PermissionDecisionReject(feedback="native_check_denied")
            if not active:
                return decision
            matched_session = context.get("session_id") == session_id
            exact = (
                matched_session and type(request) is PermissionRequestRead
                and type(request.path) is str and request.path == str(path)
                and request.resolved_path in (None, str(path))
                and (request.managed_approval_required is None
                     or request.managed_approval_required is False)
                and (request.request_sandbox_bypass is None
                     or request.request_sandbox_bypass is False)
                and request.request_sandbox_bypass_reason is None
                and request.sandbox_path_grant is None
            )
            if not matched_session:
                observation["callback_session_mismatch"] = True
            if not exact:
                observation["callback_other"] = True
                return decision
            if case != "callback_deny":
                # The missing-file control authorizes only the known-absent path;
                # no directories, bypasses, tool arguments or alternate paths.
                try:
                    intact = (not missing.exists() and not missing.is_symlink()
                              if case == "missing" else
                              target.resolve(strict=True) == target and target.is_file()
                              and target.read_text(encoding="utf-8") == marker)
                except (OSError, RuntimeError):
                    intact = False
                if intact:
                    decision = PermissionDecisionApproveOnce()
            observed = (
                "approved" if isinstance(decision, PermissionDecisionApproveOnce) else "rejected")
            previous = observation["callback"]
            observation["callback"] = (
                observed if previous in ("not_requested", observed) else "mixed")
            return decision

        try:
            require(target.read_text(encoding="utf-8") == marker
                    and target.resolve(strict=True) == target,
                    "comparison_control_failed")
            # Pinned 1.0.28 create_session supports sandbox_config; there is no
            # invented mutable-policy RPC. Only denied_paths differs for A/B.
            session = await bounded(client.create_session(
                session_id=session_id, working_directory=str(workspace),
                config_directory=str(root / "state"), enable_config_discovery=False,
                mcp_servers={}, disabled_mcp_servers=["*"], plugin_directories=[],
                agent_directories=[], skill_directories=[], instruction_directories=[],
                hook_directories=[], enable_skills=False,
                available_tools=ToolSet().add_builtin(["view"]),
                on_permission_request=permission, on_event=on_event,
                managed_settings=ManagedSettings(permissions=ManagedSettingsPermissions(
                    disable_bypass_permissions_mode="disable",
                    disable_assisted_permissions_mode=True, limit_to=[],
                )),
                sandbox_config=SandboxConfig(
                    enabled=True, allow_bypass=False, allow_dev_tool_access=False,
                    user_policy=SandboxConfigUserPolicy(
                        filesystem=SandboxConfigUserPolicyFilesystem(
                            denied_paths=[str(target)] if case == "native_deny" else []),
                        network=SandboxConfigUserPolicyNetwork(
                            allow_outbound=False, allow_local_network=False),
                    ),
                ),
            ))
            require(session.session_id == session_id, "comparison_control_failed")
            await bounded(session.rpc.permissions.configure(PermissionsConfigureParams(
                approve_all_read_permission_requests=False,
                approve_all_tool_permission_requests=False,
                paths=PermissionPathsConfig(
                    unrestricted=False, include_temp_directory=False, workspace_path=str(workspace)),
            )))
            await bounded(session.rpc.mode.set(ModeSetRequest(mode=SessionMode.PLAN)))
            require(await bounded(session.rpc.mode.get()) == SessionMode.PLAN
                    and (await bounded(session.rpc.permissions.get_mode())).mode == PermissionMode.MANUAL,
                    "comparison_control_failed")
            await bounded(session.rpc.tools.initialize_and_validate())
            allowed = await bounded(session.rpc.permissions.paths.is_path_within_allowed_directories(
                PermissionPathsAllowedCheckParams(path=str(path))))
            observation["allowed_directory"] = (
                "yes" if allowed.allowed is True else "no" if allowed.allowed is False else "unknown")
            require(allowed.allowed is True, "comparison_control_failed")
            active = True
            try:
                result = await bounded(session.rpc.tools.execute(ToolsExecuteRequest(
                    name="view", arguments={"path": str(path)}, tool_call_id="native-comparison-read")))
            finally:
                active = False
            # Scan all fields before judging shape/kind, including errors and
            # structured results. The intentional positive is private, not logged.
            try:
                serialized = json.dumps(result)
            except (TypeError, ValueError, RecursionError):
                raise CheckFailure("comparison_malformed_result") from None
            present = marker in serialized
            observation["marker_present"] = present
            require(protected_marker not in serialized, "protected_canary_leaked")
            require(case == "permit" or not present, "comparison_canary_leaked")
            # Pinned ToolResultExpanded requires string text and kind; error is
            # optional/nullable. Diagnostic suppression cannot validate a control.
            require(type(result) is dict
                    and type(result.get("textResultForLlm")) is str
                    and type(result.get("resultType")) is str
                    and result["resultType"] in TOOL_RESULT_KINDS
                    and (result.get("error") is None or type(result["error"]) is str),
                    "comparison_malformed_result")
            kind = result["resultType"]
            observation.update(
                kind=kind, read_success=kind == "success" and present,
                sandbox_error_exact=result.get("error") == "Is a sandbox denied path.",
            )
            if kind != "success":
                # Never forward a positive canary embedded in a failed response.
                if present:
                    raise CheckFailure("comparison_control_failed")
                observation["error"] = _result_error(result, root=root, protected_marker=marker)
            require(not observation["callback_session_mismatch"]
                    and not observation["callback_other"], "comparison_control_failed")
            require(target.read_text(encoding="utf-8") == marker
                    and not missing.exists() and not missing.is_symlink(),
                    "comparison_control_failed")
            if case == "permit":
                require(observation["read_success"], "comparison_control_failed")
            elif case == "missing":
                require(kind == "failure", "comparison_control_failed")
            else:
                require(kind in ("denied", "rejected", "failure"), "comparison_control_failed")
            if case == "callback_deny":
                require(observation["callback"] == "rejected", "comparison_control_failed")
            else:
                require(observation["callback"] in ("not_requested", "approved"),
                        "comparison_control_failed")
            return result, _FilePolicyControl(
                case, session_id, path,
                (str(target),) if case == "native_deny" else (), result,
                observation["callback"], observation["callback_other"],
                observation["callback_session_mismatch"], allowed.allowed,
            )
        finally:
            active = False
            cleanup_failed = False
            if session is not None:
                for operation in (session.abort, session.disconnect):
                    try:
                        await bounded(operation())
                    except Exception:
                        cleanup_failed = True
            # Delete even if create timed out after the runtime allocated the ID.
            try:
                await bounded(client.delete_session(session_id))
            except Exception:
                cleanup_failed = True
            if cleanup_failed:
                report["comparison_cleanup"] = "failed"
                if sys.exc_info()[0] is None:
                    raise CheckFailure("comparison_cleanup_failed")

    native_result = {}
    completed = []
    for case in COMPARISON_CASES:
        result, control = await run_case(case)
        completed.append(control)
        if case == "native_deny":
            native_result = result
    if controls is not None:
        require(not controls and report["comparison_cleanup"] == "complete",
                "file_policy_unqualified")
        controls.extend(completed)
    return native_result


PROCESS_CASES = (
    "workspace", "protected_permit", "protected_deny",
    "network_permit", "network_deny", "normal_exit", "cancel", "timeout",
)
NETWORK_OUTCOMES = (
    "http_ok", "http_error", "tls_error", "dns_error", "transport_timeout",
    "transport_reset", "connection_refused", "connect_permission_denied",
    "proxy_credentials", "network_setup_error",
)

PROCESS_ARGUMENT_NAMES = ("command", "description", "mode", "initial_wait", "timeout")
# Diagnostic vocabulary only, NOT additional schema support. Unknown names/text
# never leave the child. Counts saturate at 100; schemas are never serialized.
PROCESS_SCHEMA_KEYWORDS = (
    "type", "properties", "required", "additionalProperties", "description", "title",
    "$schema", "default", "enum", "minimum", "maximum", "minLength", "maxLength",
    "$ref", "$defs", "definitions", "oneOf", "anyOf", "allOf", "not", "const",
    "pattern", "format", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "items", "nullable", "additionalItems", "unevaluatedProperties",
)
PROCESS_DESCRIPTOR_LABELS = {
    "stage": ("tools", "identity", "schema", "properties", "required", "property", "argument"),
    "reason": ("shape", "count", "identity", "type", "keywords", "missing",
               "unsupported", "unsupplied", "bound_shape", "enum_shape",
               "enum_mismatch", "bound_mismatch"),
    "property": ("root", *PROCESS_ARGUMENT_NAMES),
    "keyword": ("none", *PROCESS_SCHEMA_KEYWORDS),
    "schema_shape": ("mapping", "list", "string", "number", "boolean", "null", "other"),
    "schema_type": ("absent", "object", "string", "number", "integer", "array",
                    "boolean", "null", "union", "other"),
    "required": ("yes", "no", "unknown"),
}


def _safe_process_descriptor(diagnostic: dict) -> dict:
    """Re-allowlist the fixed diagnostic at the untrusted subprocess boundary."""
    safe = {
        key: diagnostic[key] for key, values in PROCESS_DESCRIPTOR_LABELS.items()
        if type(diagnostic.get(key)) is str and diagnostic[key] in values
    }
    if type(diagnostic.get("keywords")) is list:
        safe["keywords"] = [
            key for key in PROCESS_SCHEMA_KEYWORDS if key in diagnostic["keywords"]]
    if type(diagnostic.get("required_arguments")) is list:
        safe["required_arguments"] = [
            key for key in PROCESS_ARGUMENT_NAMES if key in diagnostic["required_arguments"]]
    for key in ("unknown_keywords", "unknown_properties", "unknown_required"):
        if type(diagnostic.get(key)) is int and 0 <= diagnostic[key] <= 100:
            safe[key] = diagnostic[key]
    properties = diagnostic.get("properties")
    if type(properties) is dict:
        safe["properties"] = {
            name: {
                key: properties[name][key] for key in ("schema_shape", "schema_type", "required")
                if type(properties[name].get(key)) is str
                and properties[name][key] in PROCESS_DESCRIPTOR_LABELS[key]
            }
            for name in PROCESS_ARGUMENT_NAMES if type(properties.get(name)) is dict
        }
    return safe


class _ProcessDescriptorFailure(CheckFailure):
    def __init__(self, diagnostic: dict) -> None:
        super().__init__("process_descriptor_incompatible")
        self.diagnostic = diagnostic


def _process_arguments(metadata_result: object, command: str) -> dict:
    """Validate only the small primitive schema subset used by this fixed probe.

    SDK 1.0.28 BuiltinToolInputSchema discards properties on decoding; current
    metadata retains them. Never reconstruct constraints from descriptor prose.
    Each rejection carries its own fixed-label reason, without changing acceptance.
    """
    properties = None
    required = None

    def shape(value):
        return {dict: "mapping", list: "list", str: "string", int: "number",
                float: "number", bool: "boolean", type(None): "null"}.get(type(value), "other")

    def schema_type(value):
        if type(value) is not dict or "type" not in value:
            return "absent"
        kind = value["type"]
        if type(kind) is list:
            return "union"
        return kind if type(kind) is str and kind in (
            "object", "string", "number", "integer", "array", "boolean", "null") else "other"

    def check(condition, stage, reason, node, name="root", keyword="none"):
        if condition:
            return
        diagnostic = {
            "stage": stage, "reason": reason, "property": name, "keyword": keyword,
            "schema_shape": shape(node), "schema_type": schema_type(node),
        }
        if type(node) is dict:
            diagnostic["keywords"] = [key for key in PROCESS_SCHEMA_KEYWORDS if key in node]
            diagnostic["unknown_keywords"] = min(100, len(set(node) - set(PROCESS_SCHEMA_KEYWORDS)))
        if type(properties) is dict:
            diagnostic["unknown_properties"] = min(100, len(set(properties) - set(PROCESS_ARGUMENT_NAMES)))
            diagnostic["properties"] = {
                key: {
                    "schema_shape": shape(properties[key]), "schema_type": schema_type(properties[key]),
                    "required": ("yes" if key in required else "no") if type(required) is list else "unknown",
                } for key in PROCESS_ARGUMENT_NAMES if key in properties
            }
        if type(required) is list:
            diagnostic["required_arguments"] = [key for key in PROCESS_ARGUMENT_NAMES if key in required]
            diagnostic["unknown_required"] = min(100, sum(
                type(key) is not str or key not in PROCESS_ARGUMENT_NAMES for key in required))
        raise _ProcessDescriptorFailure(diagnostic)

    tools = getattr(metadata_result, "tools", None)
    check(type(tools) is list, "tools", "shape", tools)
    check(len(tools) == 1, "tools", "count", tools)
    tool = tools[0]
    check(getattr(tool, "name", None) == "bash" and not getattr(tool, "mcp_server_name", None),
          "identity", "identity", None)
    schema = getattr(tool, "input_schema", None)
    check(type(schema) is dict, "schema", "shape", schema)
    properties = schema.get("properties")
    required = schema.get("required", [])
    check(schema.get("type") == "object", "schema", "type", schema, keyword="type")
    check(set(schema) <= {
        "type", "properties", "required", "additionalProperties", "description", "title", "$schema",
    }, "schema", "keywords", schema)
    check(type(properties) is dict, "properties", "shape", properties, keyword="properties")
    check(type(required) is list and all(type(key) is str for key in required),
          "required", "shape", required, keyword="required")
    check(set(properties) <= set(PROCESS_ARGUMENT_NAMES),
          "properties", "unsupported", schema, keyword="properties")
    check({"command", "mode", "initial_wait"} <= set(properties),
          "properties", "missing", schema, keyword="properties")
    check(type(schema.get("additionalProperties", False)) is bool,
          "schema", "shape", schema.get("additionalProperties"), keyword="additionalProperties")
    if "$schema" in schema:
        check(schema["$schema"] in (
            "http://json-schema.org/draft-07/schema#",
            "https://json-schema.org/draft/2020-12/schema",
        ), "schema", "unsupported", schema, keyword="$schema")
    arguments = {"command": command, "mode": "sync", "initial_wait": PROCESS_TIMEOUT}
    if "description" in properties:
        arguments["description"] = "Fixed native boundary qualification"
    check(set(required) <= set(arguments), "required", "unsupplied", schema, keyword="required")
    for name, spec in properties.items():
        check(type(spec) is dict, "property", "shape", spec, name)
        check(set(spec) <= {
            "type", "description", "title", "default", "enum",
            "minimum", "maximum", "minLength", "maxLength",
        }, "property", "keywords", spec, name)
        check(spec.get("type") in ("string", "number", "integer"),
              "property", "type", spec, name, "type")
        kind = spec["type"]
        numeric = kind in ("number", "integer")
        for key in ("minimum", "maximum", "minLength", "maxLength"):
            if key in spec:
                check(type(spec[key]) in (int, float)
                      and (numeric if key in ("minimum", "maximum")
                           else kind == "string" and type(spec[key]) is int and spec[key] >= 0),
                      "property", "bound_shape", spec, name, key)
        if "enum" in spec:
            check(type(spec["enum"]) is list and bool(spec["enum"])
                  and all(type(value) in ((int, float) if numeric else (str,))
                          for value in spec["enum"]), "property", "enum_shape", spec, name, "enum")
        if name not in arguments:
            continue
        value = arguments[name]
        check(type(value) in ((int, float) if kind == "number"
                             else (int,) if kind == "integer" else (str,)),
              "argument", "type", spec, name, "type")
        check("enum" not in spec or value in spec["enum"],
              "argument", "enum_mismatch", spec, name, "enum")
        size = value if numeric else len(value)
        lower, upper = ("minimum", "maximum") if numeric else ("minLength", "maxLength")
        check(size >= spec.get(lower, size), "argument", "bound_mismatch", spec, name, lower)
        check(size <= spec.get(upper, size), "argument", "bound_mismatch", spec, name, upper)
    return arguments


class _ProcessPermission:
    """One exact native shell request, in one pending window of one owned session."""

    def __init__(self, session_id: str, command: str, call_id: str) -> None:
        self.session_id = session_id
        self.command = command
        self.call_id = call_id
        self.active = False
        self.consumed = False
        self.unexpected = False

    def __call__(self, request, context):
        from copilot.rpc import PermissionDecisionApproveOnce, PermissionDecisionReject
        from copilot.session_events import PermissionRequestShell

        exact = (
            self.active and not self.consumed and type(context) is dict
            and context.get("session_id") == self.session_id
            and type(request) is PermissionRequestShell
            and type(request.full_command_text) is str
            and request.full_command_text == self.command
            and request.tool_call_id in (None, self.call_id)
            and all(value is None or value is False for value in (
                request.managed_approval_required, request.request_sandbox_bypass,
                request.request_sandbox_permissive))
            and request.request_sandbox_bypass_reason is None
            and request.sandbox_path_grant is None
        )
        if exact:
            self.consumed = True
            return PermissionDecisionApproveOnce()
        if self.active:
            self.unexpected = True
        return PermissionDecisionReject(feedback="native_check_denied")


def _head_outcome() -> str:
    """Immutable child code: no body, credentials, redirects or host proxy copying."""
    import errno
    import http.client
    import socket
    import ssl
    import urllib.error
    import urllib.parse
    import urllib.request

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    class ConnectPermissionDenied(OSError):
        pass

    class ObservedHTTPSConnection(http.client.HTTPSConnection):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            create_connection = self._create_connection

            def connect(*args, **kwargs):
                try:
                    return create_connection(*args, **kwargs)
                except PermissionError as error:
                    if error.errno in (errno.EACCES, errno.EPERM):
                        raise ConnectPermissionDenied() from None
                    raise

            # Only local OS permission refusal before a socket is returned counts.
            # TLS, proxy CONNECT, request writes and header reads are outside this scope.
            self._create_connection = connect

    class ObservedHTTPSHandler(urllib.request.HTTPSHandler):
        def https_open(self, request):
            return self.do_open(ObservedHTTPSConnection, request, context=self._context)

    # These are the sandbox's inherited settings, not the controller host's.
    proxies = urllib.request.getproxies()
    for value in proxies.values():
        # "no" is a bypass-host list, not a proxy URL.
        if "://" in value:
            parsed = urllib.parse.urlsplit(value)
            if parsed.username is not None or parsed.password is not None:
                return "proxy_credentials"
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler(proxies), NoRedirect(),
        ObservedHTTPSHandler(context=ssl.create_default_context()))
    request = urllib.request.Request("https://docs.github.com/", method="HEAD")
    try:
        with opener.open(request, timeout=8) as response:
            # Do not read the body or serialize headers, URLs or response text.
            return "http_ok" if 200 <= response.status < 400 else "http_error"
    except urllib.error.HTTPError as error:
        outcome = "http_ok" if 300 <= error.code < 400 else "http_error"
        error.close()
        return outcome
    except (urllib.error.URLError, OSError) as error:
        cause = error.reason if isinstance(error, urllib.error.URLError) else error
        if isinstance(cause, ConnectPermissionDenied):
            return "connect_permission_denied"
        if isinstance(cause, ssl.SSLError):
            return "tls_error"
        if isinstance(cause, socket.gaierror):
            return "dns_error"
        if isinstance(cause, TimeoutError):
            return "transport_timeout"
        if isinstance(cause, OSError) and cause.errno == errno.ECONNRESET:
            return "transport_reset"
        if isinstance(cause, OSError) and cause.errno == errno.ECONNREFUSED:
            return "connection_refused"
        # HTTP/proxy status and other transport errors cannot identify the
        # tested local boundary. Never infer denial from exception text.
        return "network_setup_error"


def _process_child(workspace, target, record, parts, probe, expected_hash):
    """Fixed inline payload. Only synthetic outcomes leave the native process."""
    import hashlib
    import json
    import os
    from pathlib import Path
    import subprocess
    import time

    if "AGILE_NATIVE_AMBIENT_CANARY" in os.environ:
        raise RuntimeError("ambient_environment")
    nonce = "".join(parts)
    record = Path(record)

    def identity():
        fields = Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()
        return [os.getpid(), int(fields[19]), int(fields[1]), int(fields[2]), int(fields[3])]

    descendant = None
    identities = [identity()]
    if probe in ("normal_exit", "cancel", "timeout"):
        # Attached: no setsid/start_new_session, and no shell or arbitrary command.
        code = (
            "import json,os,time;from pathlib import Path;"
            "f=Path('/proc/self/stat').read_text().rsplit(')',1)[1].split();"
            "print(json.dumps([os.getpid(),int(f[19]),int(f[1]),int(f[2]),int(f[3])]),flush=True);"
            "time.sleep(60)"
        )
        descendant = subprocess.Popen(
            ["/usr/bin/python3", "-I", "-c", code], stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True)
        identities.append(json.loads(descendant.stdout.readline(512)))
        descendant.stdout.close()
    start = {"nonce": nonce, "identities": identities}
    temporary = record.with_suffix(".pending")
    temporary.write_text(json.dumps(start), encoding="utf-8")
    temporary.replace(record)
    print(nonce + ":started", flush=True)
    # Keep even a very short probe alive until its recorded PID/starttime has
    # been checked by the owner. This is readiness, not a timed guess at startup.
    ready = record.with_suffix(".ready")
    deadline = time.monotonic() + 5
    while not ready.exists():
        if time.monotonic() >= deadline:
            raise RuntimeError("owner_readiness_timeout")
        time.sleep(0.01)
    if ready.read_text(encoding="utf-8") != nonce:
        raise RuntimeError("owner_readiness_mismatch")
    outcomes = []
    if probe == "workspace":
        path = Path(workspace) / "process-write.txt"
        path.write_text(nonce, encoding="utf-8")
        if path.read_text(encoding="utf-8") != nonce:
            raise RuntimeError("workspace_roundtrip")
        outcomes.append("workspace_ok")
    elif probe == "protected":
        try:
            data = Path(target).read_bytes()
        except (PermissionError, FileNotFoundError):
            outcomes.append("read_refused")
        else:
            if hashlib.sha256(data).hexdigest() != expected_hash:
                raise RuntimeError("fixture_mismatch")
            outcomes.append("read_ok")
        try:
            with open(target, "r+b") as output:
                output.write(b"native-write-ok")
                output.truncate()
        except (PermissionError, FileNotFoundError):
            outcomes.append("write_refused")
        else:
            outcomes.append("write_ok")
    elif probe == "network":
        outcomes.append(_head_outcome())
    elif probe in ("normal_exit", "cancel", "timeout"):
        time.sleep(11 if probe == "normal_exit" else 60)
        descendant.terminate()
        descendant.wait(timeout=3)
        outcomes.append("attached_complete")
    else:
        raise RuntimeError("unknown_probe")
    for outcome in outcomes:
        print(nonce + ":" + outcome, flush=True)
    print(nonce + ":completed", flush=True)


def _process_command(workspace: Path, target: Path, record: Path,
                     nonce: str, probe: str, original: bytes) -> str:
    import inspect
    import shlex

    # Inline immutable source, not a script that the writable workspace can replace.
    # Neither the full start nor completion marker appears in the echoed command.
    source = inspect.getsource(_head_outcome) + "\n" + inspect.getsource(_process_child)
    arguments = (str(workspace), str(target), str(record),
                 (nonce[:16], nonce[16:]), probe, hashlib.sha256(original).hexdigest())
    return "/usr/bin/python3 -I -c " + shlex.quote(source + "\n_process_child" + repr(arguments))


def _proc_identity(pid: int) -> tuple[list[int], str] | None:
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    fields = text.rsplit(")", 1)[1].split()
    return [pid, int(fields[19]), int(fields[1]), int(fields[2]), int(fields[3])], fields[0]


def _owned_start(record: Path, nonce: str, descendants: bool) -> list[list[int]]:
    require(record.is_file() and not record.is_symlink() and record.stat().st_size <= 1024,
            "process_start_missing")
    try:
        data = json.loads(record.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        raise CheckFailure("process_start_missing") from None
    require(type(data) is dict and set(data) == {"nonce", "identities"}
            and data["nonce"] == nonce and type(data["identities"]) is list
            and len(data["identities"]) == (2 if descendants else 1), "process_start_missing")
    identities = data["identities"]
    for index, identity in enumerate(identities):
        require(type(identity) is list and len(identity) == 5
                and all(type(value) is int and value > 0 for value in identity)
                and identity[0] != os.getpid(), "process_identity_invalid")
        current = _proc_identity(identity[0])
        require(current is not None and current[0] == identity and current[1] not in ("Z", "X"),
                "process_identity_invalid")
        if index:
            require(identity[2] == identities[0][0]
                    and identity[3:] == identities[0][3:], "process_identity_invalid")
    # Walk only this recorded child's ancestry; never enumerate the machine.
    ancestor = identities[0][2]
    visited = set()
    while ancestor != os.getpid():
        require(ancestor > 1 and ancestor not in visited and len(visited) < 64,
                "process_identity_invalid")
        visited.add(ancestor)
        parent = _proc_identity(ancestor)
        require(parent is not None, "process_identity_invalid")
        ancestor = parent[0][2]
    return identities


def _identities_dead(identities: list[list[int]]) -> bool:
    require(bool(identities), "process_identity_invalid")
    for identity in identities:
        current = _proc_identity(identity[0])
        # starttime guards against PID reuse. Zombies cannot execute; the runtime
        # must still finish session teardown (disconnect/delete) independently.
        if current is not None and current[0][1] == identity[1] and current[1] not in ("Z", "X"):
            return False
    return True


def _process_result(result: object, nonce: str, expected: tuple[str, ...],
                    protected_marker: str) -> None:
    try:
        serialized = json.dumps(result)
    except (TypeError, ValueError, RecursionError):
        raise CheckFailure("process_result_invalid") from None
    require(protected_marker not in serialized, "protected_canary_leaked")
    require(len(serialized) <= CHILD_REPORT_LIMIT and type(result) is dict
            and result.get("resultType") == "success" and result.get("error") is None
            and type(result.get("textResultForLlm")) is str, "process_result_invalid")
    lines = result["textResultForLlm"].splitlines()
    observed = [line for line in lines if line.startswith(nonce + ":")]
    require(observed == [nonce + ":" + value for value in ("started", *expected, "completed")],
            "process_result_invalid")


def _network_result(result: object, nonce: str, marker: str) -> str:
    text = result.get("textResultForLlm") if type(result) is dict else None
    require(type(text) is str, "process_result_invalid")
    outcomes = [value for value in NETWORK_OUTCOMES if nonce + ":" + value in text.splitlines()]
    require(len(outcomes) == 1, "process_result_invalid")
    _process_result(result, nonce, (outcomes[0],), marker)
    return outcomes[0]


async def qualify_native_processes(client, root: Path, report: dict, bounded, on_event) -> None:
    """Disposable native sessions; no production worker capability changes."""
    import asyncio

    from copilot import ToolSet
    from copilot.client import ManagedSettings, ManagedSettingsPermissions
    from copilot.rpc import (
        PermissionPathsConfig, PermissionsConfigureParams, SandboxConfig,
        SandboxConfigUserPolicy, SandboxConfigUserPolicyFilesystem,
        SandboxConfigUserPolicyNetwork, ToolsExecuteRequest,
    )
    from copilot.session_events import PermissionMode

    workspace = root / "workspace"
    target = root / "protected" / "process-control.txt"
    original = uuid.uuid4().hex.encode("ascii")
    require(not target.exists() and not target.is_symlink(), "process_fixture_changed")
    target.write_bytes(original)
    # A/B share the complete command, including markers and fixture. Freshness
    # is enforced by removing the owned record only after the previous run dies.
    nonce = uuid.uuid4().hex
    record = workspace / ("process-" + uuid.uuid4().hex + ".json")
    ready = record.with_suffix(".ready")
    report["process_controls"] = {}
    report["process_network"] = {}

    async def wait_started(task, descendants):
        deadline = asyncio.get_running_loop().time() + PROCESS_READY_TIMEOUT
        while not record.exists():
            require(not task.done(), "process_start_missing")
            require(asyncio.get_running_loop().time() < deadline, "process_start_missing")
            await asyncio.sleep(0.05)
        return _owned_start(record, nonce, descendants)

    async def wait_dead(identities):
        deadline = asyncio.get_running_loop().time() + PROCESS_DEATH_TIMEOUT
        while not _identities_dead(identities):
            require(asyncio.get_running_loop().time() < deadline, "process_orphan_alive")
            await asyncio.sleep(0.05)

    for case in PROCESS_CASES:
        probe = ("protected" if case.startswith("protected") else
                 "network" if case.startswith("network") else case)
        command = _process_command(workspace, target, record, nonce, probe, original)
        session_id = str(uuid.uuid4())
        permission = _ProcessPermission(session_id, command, "native-process")
        session = None
        task = None
        identities = []
        expected_interrupt = case in ("cancel", "timeout")
        descendants = case in ("normal_exit", "cancel", "timeout")
        require(not record.exists() and not record.is_symlink()
                and not ready.exists() and not ready.is_symlink(), "process_start_missing")
        require(target.read_bytes() == original and target.resolve() == target,
                "process_fixture_changed")
        report["process_controls"][case] = "started"
        try:
            session = await bounded(client.create_session(
                session_id=session_id, working_directory=str(workspace),
                config_directory=str(root / "state"), enable_config_discovery=False,
                mcp_servers={}, disabled_mcp_servers=["*"], plugin_directories=[],
                agent_directories=[], skill_directories=[], instruction_directories=[],
                hook_directories=[], enable_skills=False,
                available_tools=ToolSet().add_builtin("bash"),
                on_permission_request=permission, on_event=on_event,
                managed_settings=ManagedSettings(permissions=ManagedSettingsPermissions(
                    disable_bypass_permissions_mode="disable",
                    disable_assisted_permissions_mode=True, limit_to=[],
                )),
                sandbox_config=SandboxConfig(
                    enabled=True, allow_bypass=False, allow_dev_tool_access=False,
                    user_policy=SandboxConfigUserPolicy(
                        filesystem=SandboxConfigUserPolicyFilesystem(
                            readwrite_paths=[str(workspace), str(target)],
                            denied_paths=[str(target)] if case == "protected_deny" else []),
                        network=SandboxConfigUserPolicyNetwork(
                            allowed_hosts=["docs.github.com"], allow_local_network=False,
                            allow_outbound=case == "network_permit"),
                    ),
                ),
            ))
            require(session.session_id == session_id, "process_permission_mismatch")
            await bounded(session.rpc.permissions.configure(PermissionsConfigureParams(
                approve_all_read_permission_requests=False,
                approve_all_tool_permission_requests=False,
                paths=PermissionPathsConfig(
                    unrestricted=False, include_temp_directory=False, workspace_path=str(workspace)),
            )))
            require((await bounded(session.rpc.permissions.get_mode())).mode == PermissionMode.MANUAL,
                    "process_permission_mismatch")
            await bounded(session.rpc.tools.initialize_and_validate())
            tool_metadata = await bounded(session.rpc.tools.get_current_metadata())
            try:
                arguments = _process_arguments(tool_metadata, command)
            except _ProcessDescriptorFailure as exc:
                report["process_descriptor"] = exc.diagnostic
                raise
            permission.active = True
            task = asyncio.create_task(session.rpc.tools.execute(
                ToolsExecuteRequest(name="bash", arguments=arguments, tool_call_id="native-process"),
                timeout=PROCESS_TIMEOUT))
            identities = await wait_started(task, descendants)
            started_at = asyncio.get_running_loop().time()
            ready_pending = ready.with_suffix(".ready.pending")
            ready_pending.write_text(nonce, encoding="utf-8")
            ready_pending.replace(ready)
            if expected_interrupt:
                try:
                    await asyncio.wait_for(asyncio.shield(task),
                                           PROCESS_CANCEL_TIMEOUT if case == "timeout"
                                           else PROCESS_CANCEL_DELAY)
                except TimeoutError:
                    pass  # The timer begins only after live parent + descendant proof.
                else:
                    raise CheckFailure("process_completed_before_cancel")
                require(not task.done(), "process_completed_before_cancel")
                permission.active = False
                for identity in identities:
                    current = _proc_identity(identity[0])
                    require(current is not None and current[0] == identity
                            and current[1] not in ("Z", "X"), "process_completed_before_cancel")
                await bounded(session.abort())
                # Abort acknowledgement is not proof: require child/descendant death.
                await wait_dead(identities)
                try:
                    result = await asyncio.wait_for(asyncio.shield(task), PROCESS_DEATH_TIMEOUT)
                except TimeoutError:
                    raise CheckFailure("process_cleanup_failed") from None
                except Exception:
                    # The execution may reject on native cancellation. Death, not
                    # its error text, establishes cleanup. Never emit raw exceptions.
                    result = None
                if result is not None:
                    serialized = json.dumps(result)
                    require(original.decode("ascii") not in serialized, "protected_canary_leaked")
                    require(len(serialized) <= CHILD_REPORT_LIMIT, "process_result_invalid")
                    require(nonce + ":completed" not in serialized,
                            "process_completed_before_cancel")
            else:
                result = await asyncio.wait_for(asyncio.shield(task), PROCESS_TIMEOUT)
                expected = {
                    "workspace": ("workspace_ok",),
                    "protected_permit": ("read_ok", "write_ok"),
                    "protected_deny": ("read_refused", "write_refused"),
                    "normal_exit": ("attached_complete",),
                }.get(case)
                if probe == "network":
                    # A received HTTP response (including HTTP errors) is NOT a
                    # connection denial. TLS/DNS/setup failures are inconclusive.
                    outcome = _network_result(result, nonce, original.decode("ascii"))
                    report["process_network"][case] = outcome
                    require(case != "network_permit" or outcome == "http_ok",
                            "process_network_positive_failed")
                    require(case != "network_deny" or outcome == "connect_permission_denied",
                            "process_network_negative_failed")
                else:
                    _process_result(result, nonce, expected, original.decode("ascii"))
                if case == "normal_exit":
                    require(asyncio.get_running_loop().time() - started_at > 10,
                            "process_result_invalid")
                await wait_dead(identities)
            require(permission.consumed and not permission.unexpected, "process_permission_mismatch")
            require(target.resolve() == target and target.read_bytes() == (
                b"native-write-ok" if case == "protected_permit" else original),
                    "process_fixture_changed")
        finally:
            permission.active = False
            cleanup_failed = False
            if session is not None:
                # Normal completion is checked before cleanup; do not turn a
                # successful abort of an unfinished child into a normal-exit pass.
                operations = ((session.abort,) if task is not None and not task.done() else ())
                for operation in (*operations, session.disconnect):
                    try:
                        await bounded(operation())
                    except Exception:
                        cleanup_failed = True
            try:
                await bounded(client.delete_session(session_id))
            except Exception:
                cleanup_failed = True
            if task is not None:
                if not task.done():
                    task.cancel()
                try:
                    await task
                except (Exception, asyncio.CancelledError):
                    pass  # Observe the task; local cancellation is not cleanup evidence.
            if identities:
                try:
                    await wait_dead(identities)
                except Exception:
                    cleanup_failed = True
            if cleanup_failed:
                raise CheckFailure("process_cleanup_failed") from None
        report["process_controls"][case] = (
            "cancelled" if case == "cancel" else "timed_out" if case == "timeout" else "complete")
        record.unlink()
        ready.unlink()
        if case == "protected_permit":
            target.write_bytes(original)


async def native_checks(runtime: Path, root: Path) -> dict:
    # Deliberately lazy: import/ordinary test discovery never starts an SDK/loop.
    import asyncio
    import shlex

    from copilot import BUILTIN_TOOLS_ISOLATED, CopilotClient, RuntimeConnection, ToolSet
    from copilot.client import ManagedSettings, ManagedSettingsPermissions
    from copilot.rpc import (
        ModeSetRequest, PermissionDecisionApproveOnce, PermissionDecisionReject,
        PermissionPathsAllowedCheckParams, PermissionPathsConfig,
        PermissionsConfigureParams, PermissionsSetModeRequest,
        PlanUpdateRequest, SandboxConfig, SandboxConfigUserPolicy,
        SandboxConfigUserPolicyFilesystem, SandboxConfigUserPolicyNetwork,
        ToolsExecuteRequest,
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
    protected_completion = _ProtectedReadCompletion()
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
        # SDK 1.0.28 permissions.paths.add grants directories, not individual files.
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
                     and request.resolved_path in (None, str(protected))
                     and (request.managed_approval_required is None
                          or request.managed_approval_required is False)
                     and (request.request_sandbox_bypass is None
                          or request.request_sandbox_bypass is False)
                     and request.request_sandbox_bypass_reason is None
                     and request.sandbox_path_grant is None)
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
        # Public, read-only SDK 1.0.28 inspections. Neither is a per-tool denial
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
        kind = _event_field(event, "type")
        kind = getattr(kind, "value", kind)
        if kind in ("assistant.turn_start", "assistant.message", "assistant.message_delta"):
            model_activity.set()
        protected_completion.observe(event)

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
        protected_marker = protected.read_text(encoding="utf-8")
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
            # SDK 1.0.28 customization-locations: a direct SKILL.md bundle is
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
                        denied_paths=[str(root / "protected" / "control-plane.txt")]),
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

        # Fresh same-run controls must qualify this candidate before any generic
        # file failure can count as an observed policy refusal.
        report["check"] = "native_file_denial"
        controls = []
        await compare_native_file_policy(
            client, root, report, bounded, on_event, controls=controls)
        require(not model_activity.is_set(), "comparison_control_failed")
        file_qualification = qualify_file_policy(
            metadata.version("github-copilot-sdk"), identity, root, controls)

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
                name="view", arguments={"path": str(readable_path)},
                tool_call_id=POSITIVE_READ_CALL_ID)))
        finally:
            positive_read_pending = False
        require_positive_read(readable, positive_read_decisions, report)
        report["protected_read"] = protected_observation
        protected_read_pending = True
        try:
            protected_completion.active = True
            try:
                denied = await bounded(session.rpc.tools.execute(ToolsExecuteRequest(
                    name="view", arguments={"path": str(protected)},
                    tool_call_id=PROTECTED_READ_CALL_ID)))
            finally:
                protected_read_pending = False
            # A leaked marker is a hard failure even for failure/denied/rejected.
            # Use the original marker, not a possibly changed file after execution.
            require(not protected_canary_present(denied, protected_marker, protected_observation),
                    "protected_canary_leaked")
            try:
                if (file_qualification is not None and type(denied) is dict
                        and denied.get("resultType") == "failure"
                        and denied.get("error") == FILE_POLICY_ERROR):
                    require(protected_observation["callback"] in (
                        "not_requested", "rejected_exact_read"), "file_policy_unqualified")
                    require_qualified_file_refusal(
                        denied, file_qualification, metadata.version("github-copilot-sdk"),
                        identity, tool="view", target=protected, denied_paths=(str(protected),))
                else:
                    require_denial(denied, report)
            except CheckFailure:
                # Only this exact owned direct result, after the all-field marker
                # check, may supply text. Generic failure remains a failed check.
                if type(denied) is dict and denied.get("resultType") == "failure":
                    report["protected_error"] = _protected_error(
                        denied, root=root, protected_marker=protected_marker)
                raise
            require(permission_sessions and all(value == session_id for value in permission_sessions),
                    "permission_session_mismatch")
        except Exception:
            await inspect_protected_policy()
            report["protected_completion"] = dict(protected_completion.diagnostic)
            raise
        finally:
            # No public SDK event-drain contract exists for direct tools.execute.
            # Include delivery during existing inspections, but never wait/poll,
            # fetch history, or let cleanup events mutate the failure snapshot.
            protected_completion.active = False
        report["passed"].append(report["check"])

        report["check"] = "native_process_sandbox"
        support = await bounded(client.rpc.sandbox.get_host_support())
        capabilities = {item.name: item.supported for item in support.capabilities}
        require(support.supported and capabilities.get("shell") is True
                and capabilities.get("denied_paths") is True,
                "sandbox_host_support_required")
        try:
            async with asyncio.timeout(PROCESS_PHASE_TIMEOUT) as phase_deadline:
                await qualify_native_processes(client, root, report, bounded, on_event)
        except TimeoutError:
            raise CheckFailure("process_deadline_exceeded" if phase_deadline.expired()
                               else "process_operation_timeout") from None
        require(not model_activity.is_set(), "process_result_invalid")
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

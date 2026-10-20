"""Bounded native Copilot tool invocation. No prompts, sends, or model credentials."""

import argparse
import asyncio
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time

from setup_runtime import require_hosted

ROOT = Path(__file__).resolve().parent


def policy(workspace, denied):
    return {"sandbox": {
        "enabled": True, "allowBypass": False, "allowDevToolAccess": False,
        "addCurrentWorkingDirectory": True,
        "auth": {"git": False, "gh": False},
        "sandboxMcpServers": True, "sandboxLspServers": True,
        "userPolicy": {
            "filesystem": {"readwritePaths": [str(workspace)],
                           "readonlyPaths": ["/usr", "/bin", "/lib", "/lib64"],
                           "deniedPaths": [str(denied)]},
            "network": {"allowOutbound": False, "allowLocalNetwork": False},
        },
    }}


def parse_probe(text):
    matches = re.findall(r"^NATIVE_PROBE=(\{[^\n]+\})$", text, re.MULTILINE)
    if len(matches) != 1:
        raise AssertionError("Native tool did not return exactly one completed probe")
    return json.loads(matches[0])


def check_boundaries(host, child, observed_bwrap):
    checks = {
        "non_root": child["uid"] != 0,
        "workspace_read": child["workspace_read"],
        "workspace_write": child["workspace_write"],
        "command": child["command"],
        "outside_read_denied": host["outside_read"] and not child["outside_read"],
        "outbound_denied": host["outbound"] and not child["outbound"],
        "localhost_denied": host["localhost"] and not child["localhost"],
        "native_bwrap_observed": bool(observed_bwrap),
        "private_namespaces": all(host["namespaces"][n] != child["namespaces"][n]
                                  for n in ("user", "mnt", "net")),
    }
    return checks


def check_host_integrity(denied):
    """Check the host view, not whether writes succeeded in a private sandbox view."""
    sentinel = denied / "sentinel"
    directory_intact = denied.is_dir() and not denied.is_symlink()
    return {
        "host_sentinel_unchanged": (
            directory_intact and sentinel.is_file() and not sentinel.is_symlink()
            and sentinel.read_bytes() == b"synthetic-not-a-secret"),
        "host_denied_directory_unchanged": (
            directory_intact and sorted(p.name for p in denied.iterdir()) == ["sentinel"]),
    }


def check_unavailable(result, marker):
    """CLI 1.0.98 handles the RPC successfully even when its shell command fails."""
    exits = [item for item in result.get("contents", []) if item.get("type") == "shell_exit"]
    shell = exits[0] if len(exits) == 1 else {}
    code = shell.get("exitCode")
    output = shell.get("outputPreview", "")
    # Use the actual shell result, not a mention in echoed arguments or a transport error.
    explicit_error = (
        output.startswith("<error: GenericFailure, Sandboxing is enabled but not supported on this platform:")
        and "Bubblewrap (bwrap) is unavailable." in output)
    return {
        "unavailable_sandbox_error": explicit_error,
        "unavailable_command_failed": (
            type(code) is int and code != 0
            and result.get("toolTelemetry", {}).get("metrics", {}).get("exit_code") == code
            and result.get("textResultForLlm", "").endswith(
                f"<shellId: {shell.get('shellId')} completed with exit code {code}>")),
        "no_unsandboxed_marker": not marker.exists(),
    }


def permitted(data, command):
    return (data.get("kind") == "shell" and data.get("fullCommandText") == command
            and not any(data.get(key) for key in (
                "requestSandboxBypass", "requestSandboxPermissive",
                "sandboxPathGrant", "managedApprovalRequired")))


def verify_effective_policy(result, requested):
    """Require native readback, not a saved settings file or update acknowledgement."""
    if result.get("kind") != "text":
        raise AssertionError("Native /sandbox policy did not return policy text")
    # Pinned CLI 1.0.98 returns a human-readable ANSI report, not JSON.
    # Fail closed on unrecognized/changed rendering; never treat our input as readback.
    text = re.sub(r"\x1b\[[0-9;]*m", "", result.get("text", ""))
    workspace = requested["userPolicy"]["filesystem"]["readwritePaths"][0]
    if not text.startswith(f"Effective sandbox policy for {workspace}\n\n"):
        raise AssertionError("Native effective policy header missing or workspace mismatch")
    sections = {}
    for block in re.split(r"\n{2,}", text)[1:]:
        lines = block.splitlines()
        if lines:
            if lines[0] in sections:
                raise AssertionError("Duplicate effective policy section")
            sections[lines[0]] = lines[1:]
    if sections.get("Network:") != ["  Outbound: blocked", "  Local network: blocked"]:
        raise AssertionError("Native effective network policy is not fully blocked")
    if sections.get("Dev tools:") != ["  Not granted."]:
        raise AssertionError("Native effective developer-tool grants are not disabled")
    capabilities = sections.get("Capabilities:", [])
    for label, value in (
        ("Allow sandbox bypass", "no"),
        ("Sandbox MCP servers", "sandboxed"), ("Sandbox LSP servers", "sandboxed"),
        ("Authenticate git (sandbox setting)", "off"), ("Authenticate gh (sandbox setting)", "off"),
    ):
        actual = [line for line in capabilities if line.startswith(f"  {label}:")]
        if actual != [f"  {label}: {value}"]:
            raise AssertionError(f"Native effective capability mismatch: {label}")
    filesystem = {"readonlyPaths": [], "readwritePaths": [], "deniedPaths": []}
    keys = {"Read-only": "readonlyPaths", "Read-write": "readwritePaths", "Denied": "deniedPaths"}
    for match in re.finditer(
            r"^  (Read-only|Read-write|Denied) paths \((\d+)\):\n((?:    /[^\n]+\n?)+)",
            text, re.MULTILINE):
        paths = [line[4:] for line in match[3].splitlines()]
        if len(paths) != int(match[2]):
            raise AssertionError("Native effective path count mismatch")
        filesystem[keys[match[1]]].extend(paths)
    expected = requested["userPolicy"]["filesystem"]
    if not all(set(paths) <= set(filesystem[key]) for key, paths in expected.items()):
        raise AssertionError("Native effective filesystem grants/denials mismatch")
    return {"filesystem": filesystem,
            "network": {"allowOutbound": False, "allowLocalNetwork": False},
            "allowBypass": False, "allowDevToolAccess": False,
            "auth": {"git": False, "gh": False},
            "sandboxMcpServers": True, "sandboxLspServers": True}


def sandbox_applied(result):
    properties = result.get("toolTelemetry", {}).get("properties", {})
    return (properties.get("sandboxApplied") in (True, "true")
            and properties.get("sandboxOptOutRequested") in (False, "false"))


async def cleanup(session, client, evidence):
    """Always stop the client; never replace execution evidence or its exception."""
    errors = []
    if session is not None:
        try:
            await asyncio.wait_for(session.disconnect(), 15)
        except Exception as error:
            errors.append(f"session.disconnect: {type(error).__name__}: {error}")
    try:
        stop_errors = await asyncio.wait_for(client.stop(), 15)
        if stop_errors:
            errors.append(f"client.stop: {stop_errors}")
    except Exception as error:
        errors.append(f"client.stop: {type(error).__name__}: {error}")
    evidence["cleanup_errors"] = errors


@contextmanager
def trap_server():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append("POST")  # Never log request contents.
            self.send_error(503, "Inference forbidden by synthetic proof")

        def do_GET(self):
            requests.append("GET")
            self.send_error(503, "Provider access forbidden by synthetic proof")

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port, requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def observe_bwrap(stop, observed):
    while not stop.wait(0.03):
        for entry in Path("/proc").glob("[0-9]*/comm"):
            try:
                if entry.read_text().strip() == "bwrap":
                    observed.add(entry.parent.name)
            except OSError:
                continue


async def native(cli, base, workspace, command, evidence, provider_port, unavailable):
    from copilot import CopilotClient, RuntimeConnection
    from copilot.rpc import (
        CommandsInvokeRequest, PermissionDecisionApproveOnce, PermissionDecisionReject,
        SandboxConfig, SandboxConfigSource, SessionUpdateOptionsParams, ToolsExecuteRequest,
    )

    def permission(request, _):
        data = request.to_dict()
        # Approve only this synthetic shell command; never sandbox bypass/escalation.
        if permitted(data, command):
            return PermissionDecisionApproveOnce()
        evidence.setdefault("rejected_permissions", []).append(data.get("kind"))
        return PermissionDecisionReject()

    env = {
        "PATH": os.environ["PATH"], "HOME": str(base / "home"),
        "XDG_CONFIG_HOME": str(base / "home" / ".config"),
        "XDG_CACHE_HOME": str(base / "home" / ".cache"),
        "TMPDIR": str(base / "tmp"), "COPILOT_DISABLE_KEYTAR": "1",
        "COPILOT_TELEMETRY_DISABLED": "1", "DO_NOT_TRACK": "1",
    }
    client = CopilotClient(
        connection=RuntimeConnection.for_stdio(path=str(cli), args=["--sandbox"]),
        working_directory=str(workspace), base_directory=str(base / "config"),
        env=env, use_logged_in_user=False,
    )
    session = None
    try:
        evidence["stage"] = "runtime.start"
        await asyncio.wait_for(client.start(), 45)
        evidence["stage"] = "sandbox.getHostSupport"
        support = await client.rpc.sandbox.get_host_support(timeout=20)
        evidence["host_support"] = support.to_dict()
        support_data = evidence["host_support"]
        capabilities = {c["name"]: c["supported"] for c in support_data.get("capabilities", [])}
        if not unavailable and (not support_data.get("supported") or not all(
                capabilities.get(name) for name in ("network", "denied_paths", "shell"))):
            raise RuntimeError("Native host support is unavailable; refusing normal proof")
        evidence["stage"] = "session.create"
        session = await asyncio.wait_for(client.create_session(
            model="synthetic-no-inference",
            provider={"type": "openai", "base_url": f"http://127.0.0.1:{provider_port}/v1"},
            on_permission_request=permission, working_directory=str(workspace),
            available_tools=["bash"], skip_custom_instructions=True,
            enable_config_discovery=False, enable_file_hooks=False,
            enable_skills=False, enable_host_git_operations=False,
            enable_session_store=False, skip_embedding_retrieval=True,
            enable_session_telemetry=False,
        ), 45)
        # The high-level SDK create_session has no sandbox_config argument in 1.0.22.
        # Explicitly patch the native session; --sandbox/settings alone are not proof.
        evidence["stage"] = "session.options.update"
        requested = evidence["policy"]["sandbox"]
        update = await session.rpc.options.update(SessionUpdateOptionsParams(
            sandbox_config=SandboxConfig.from_dict(requested),
            sandbox_config_source=SandboxConfigSource.SESSION_FLAG,
        ), timeout=20)
        evidence["policy_update"] = update.to_dict()
        if not update.success:
            raise AssertionError("Native session rejected explicit sandbox configuration")
        evidence["stage"] = "session.commands.invoke.sandbox.policy"
        readback = await session.rpc.commands.invoke(
            CommandsInvokeRequest(name="sandbox", input="policy"), timeout=20)
        evidence["policy_readback"] = readback.to_dict()
        evidence["effective_policy"] = verify_effective_policy(evidence["policy_readback"], requested)
        evidence["stage"] = "session.tools.initializeAndValidate"
        await session.rpc.tools.initialize_and_validate(timeout=30)
        metadata = await session.rpc.tools.get_current_metadata(timeout=20)
        evidence["tools"] = metadata.to_dict()
        evidence["stage"] = "session.tools.execute"
        result = await session.rpc.tools.execute(ToolsExecuteRequest(
            name="bash", arguments={"command": command, "description": "Synthetic sandbox boundary probe",
                                    "initial_wait": 30, "mode": "sync"},
        ), timeout=60)
        result = result.to_dict() if hasattr(result, "to_dict") else result
        evidence["native_result"] = result
        return result
    finally:
        await cleanup(session, client, evidence)


async def run(args, evidence):
    require_hosted()
    with tempfile.TemporaryDirectory(prefix="native-local-proof-") as temp, trap_server() as (port, requests):
        base = Path(temp)
        workspace, denied = base / "workspace", base / "denied"
        for folder in (workspace, denied, base / "home", base / "config", base / "tmp"):
            folder.mkdir(mode=0o700)
        config = policy(workspace, denied)
        (base / "config" / "settings.json").write_text(json.dumps(config))
        evidence["policy"] = config
        evidence["versions"] = {
            "cli": subprocess.check_output([str(args.cli), "--version"], text=True, timeout=15,
                                           env={"PATH": os.environ["PATH"], "HOME": str(base / "home")}),
            "python": subprocess.check_output(["python", "--version"], text=True, timeout=10),
            "runner": {key: os.environ.get(key) for key in ("ImageOS", "ImageVersion")},
            "packages": subprocess.check_output(
                ["dpkg-query", "-W", "bubblewrap", "slirp4netns", "util-linux", "iptables"],
                text=True, timeout=10),
        }
        if "1.0.98" not in evidence["versions"]["cli"]:
            raise AssertionError("Unexpected CLI version")
        evidence["sandbox_help"] = subprocess.check_output(
            [str(args.cli), "help", "sandbox"], text=True, timeout=15,
            env={"PATH": os.environ["PATH"], "HOME": str(base / "home")})
        (workspace / "input").write_text("synthetic-input")
        (denied / "sentinel").write_text("synthetic-not-a-secret")
        shutil.copyfile(ROOT / "probe.py", workspace / "probe.py")
        import shlex
        if args.unavailable:
            command = "printf synthetic > " + shlex.quote(str(workspace / "UNSANDBOXED"))
        else:
            ip = socket.gethostbyname("example.com")
            argv = ["/usr/bin/python3", str(workspace / "probe.py"),
                    str(workspace), str(denied), ip, str(port)]
            host = parse_probe(subprocess.check_output(argv, text=True, timeout=20))
            evidence["host_control"] = host
            if not all(host[k] for k in ("workspace_read", "workspace_write", "command",
                                         "outside_read", "outside_directory_write",
                                         "outside_sentinel_write", "outbound", "localhost")):
                raise AssertionError("Unsandboxed positive control failed")
            (denied / "write-marker").unlink()
            (denied / "sentinel").write_text("synthetic-not-a-secret")
            if not all(check_host_integrity(denied).values()):
                raise AssertionError("Host denied-path baseline was not restored")
            (workspace / "output").unlink()
            command = shlex.join(argv)
        observed, stop = set(), threading.Event()
        watcher = threading.Thread(target=observe_bwrap, args=(stop, observed), daemon=True)
        watcher.start()
        try:
            try:
                result = await native(args.cli, base, workspace, command, evidence, port, args.unavailable)
            except Exception as error:
                # Preserve execution-boundary errors, but transport failure alone
                # cannot satisfy the required completed shell-failure evidence.
                if not args.unavailable or evidence["stage"] != "session.tools.execute":
                    raise
                result = {"resultType": "failure", "error": str(error)}
                evidence["native_result"] = result
            if args.unavailable:
                evidence["assertions"] = check_unavailable(result, workspace / "UNSANDBOXED")
            else:
                child = parse_probe(result.get("textResultForLlm", ""))
                evidence["sandbox_probe"] = child
                evidence["assertions"] = check_boundaries(host, child, observed)
                evidence["assertions"]["sandbox_applied"] = sandbox_applied(result)
                evidence["assertions"].update(check_host_integrity(denied))
                evidence["assertions"]["workspace_output"] = (
                    (workspace / "output").read_text() == "synthetic-output")
            evidence["assertions"]["no_provider_requests"] = not requests
            evidence["assertions"]["cleanup_clean"] = not evidence.get("cleanup_errors")
            if not all(evidence["assertions"].values()):
                raise AssertionError("Native sandbox acceptance failed")
        finally:
            stop.set()
            watcher.join(timeout=5)
            evidence["observed_bwrap_pids"] = sorted(observed)
            evidence["provider_requests"] = list(requests)
            evidence["model_send_calls"] = 0  # No send API exists in this harness.


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("cli", type=Path)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--unavailable", action="store_true")
    args = parser.parse_args()
    evidence = {"status": "BLOCKED", "stage": "preflight", "scenario": "unavailable" if args.unavailable else "available"}
    started = time.monotonic()
    try:
        asyncio.run(asyncio.wait_for(run(args, evidence), 240))
        evidence["status"] = "PASS"
    except Exception as error:
        evidence["error"] = f"{type(error).__name__}: {error}"
    finally:
        evidence["elapsed_seconds"] = round(time.monotonic() - started, 3)
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(evidence, indent=2) + "\n")
        print(json.dumps(evidence, indent=2), flush=True)
        # Public check annotations remain readable when raw Actions logs require login.
        # GitHub limits notices per step: keep lifecycle evidence together and use <=10.
        notices = {"summary": {key: evidence[key] for key in (
            "status", "scenario", "stage", "error", "provider_requests", "model_send_calls",
            "cleanup_errors", "versions", "elapsed_seconds") if key in evidence}}
        notices.update({key: evidence[key] for key in (
            "assertions", "native_result", "host_control", "sandbox_probe", "host_support",
            "policy_update", "policy_readback", "effective_policy", "observed_bwrap_pids")
            if key in evidence})
        for key, value in notices.items():
            message = json.dumps({key: value}).replace(
                "%", "%25").replace("\r", "%0D").replace("\n", "%0A")
            print(f"::notice title=Native {evidence['scenario']} {key}::{message}", flush=True)
    raise SystemExit(0 if evidence["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()

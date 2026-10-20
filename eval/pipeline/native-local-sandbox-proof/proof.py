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
        "outside_write_denied": host["outside_write"] and not child["outside_write"],
        "outbound_denied": host["outbound"] and not child["outbound"],
        "localhost_denied": host["localhost"] and not child["localhost"],
        "native_bwrap_observed": bool(observed_bwrap),
        "private_namespaces": all(host["namespaces"][n] != child["namespaces"][n]
                                  for n in ("user", "mnt", "net")),
    }
    return checks


def permitted(data, command):
    return (data.get("kind") == "shell" and data.get("fullCommandText") == command
            and not any(data.get(key) for key in (
                "requestSandboxBypass", "requestSandboxPermissive",
                "sandboxPathGrant", "managedApprovalRequired")))


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
    from copilot.rpc import PermissionDecisionApproveOnce, PermissionDecisionReject, ToolsExecuteRequest

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
        if not unavailable and not evidence["host_support"].get("supported"):
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
        if session is not None:
            await asyncio.wait_for(session.destroy(), 15)
        await asyncio.wait_for(client.stop(), 15)


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
                                         "outside_read", "outside_write", "outbound", "localhost")):
                raise AssertionError("Unsandboxed positive control failed")
            (denied / "write-marker").unlink()
            (workspace / "output").unlink()
            command = shlex.join(argv)
        observed, stop = set(), threading.Event()
        watcher = threading.Thread(target=observe_bwrap, args=(stop, observed), daemon=True)
        watcher.start()
        try:
            try:
                result = await native(args.cli, base, workspace, command, evidence, port, args.unavailable)
            except Exception as error:
                # Only an explicit sandbox rejection at the actual execution boundary counts.
                if not args.unavailable or evidence["stage"] != "session.tools.execute":
                    raise
                result = {"resultType": "failure", "error": str(error)}
                evidence["native_result"] = result
            if args.unavailable:
                error_text = json.dumps(result).lower()
                evidence["assertions"] = {
                    "unavailable_rejected": result.get("resultType") != "success"
                    and "sandbox" in error_text
                    and any(s in error_text for s in ("unavailable", "unsupported", "not supported", "bwrap")),
                    "no_unsandboxed_marker": not (workspace / "UNSANDBOXED").exists(),
                }
            else:
                child = parse_probe(result.get("textResultForLlm", ""))
                evidence["sandbox_probe"] = child
                evidence["assertions"] = check_boundaries(host, child, observed)
                evidence["assertions"]["outside_unchanged"] = (
                    (denied / "sentinel").read_text() == "synthetic-not-a-secret"
                    and not (denied / "write-marker").exists())
                evidence["assertions"]["workspace_output"] = (
                    (workspace / "output").read_text() == "synthetic-output")
            evidence["assertions"]["no_provider_requests"] = not requests
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
        summary = {key: evidence[key] for key in (
            "status", "scenario", "stage", "error", "assertions", "provider_requests",
            "model_send_calls", "host_support", "native_result", "host_control",
            "versions", "elapsed_seconds") if key in evidence}
        message = json.dumps(summary).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::notice title=Native local sandbox proof::{message}", flush=True)
    raise SystemExit(0 if evidence["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()

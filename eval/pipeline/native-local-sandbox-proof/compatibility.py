"""Hosted, zero-inference compatibility experiment; never a live admission gate."""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

from proof import cleanup, permitted, policy, sandbox_applied, trap_server, verify_effective_policy
from setup_runtime import require_hosted

REPO = Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins" / "agile-agents-core"
MARKER = "SYNTHETIC-NOT-A-CREDENTIAL-compatibility"


def local_agent_name(name):
    return name.removeprefix("agile-agents-core:")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def agent_evidence(agent, plugin):
    """Hash only known repository files, never arbitrary paths from runtime output."""
    row = {k: v for k, v in agent.items() if k != "prompt"}
    source = plugin / "agents" / f"{local_agent_name(agent['name'])}.agent.md"
    if source.is_file():
        content = source.read_text(encoding="utf-8")
        body = content.split("---", 2)[2].strip()
        row.update(source_sha256=sha(source.read_bytes()),
                   runtime_prompt_sha256=sha(agent.get("prompt", "").encode()),
                   authored_body_sha256=sha(body.encode()),
                   prompt_matches=agent.get("prompt", "").strip() == body,
                   path_matches=agent.get("path") == str(source))
    return row


def mutation_observation(path, permissions, hooks, result):
    host_mutated = path.exists()
    return {
        "host_mutated": host_mutated,
        "permission_callback_count": len(permissions),
        "pre_tool_callback_count": len(hooks),
        "native_result": result,
        # Native permission rejection and hook/permission-error denial are distinct
        # result types. Prose alone is not evidence; execution/transport conflicts
        # and callback absence must not be reported as controller denial.
        "controller_denial_proved": (
            bool(permissions or hooks) and not host_mutated
            and result.get("resultType") in ("denied", "rejected")
            and "rpc_error" not in result
            and not any(item.get("type") == "shell_exit"
                        for item in result.get("contents") or [])
        ),
    }


def shell_payload(workspace, controller):
    script = (
        "import json,os,pathlib;"
        f"p=pathlib.Path({str(controller)!r});"
        "r={'inherited_marker':os.getenv('SYNTHETIC_INHERITED')=="
        f"{MARKER!r},'masked_present':bool(os.getenv('SYNTHETIC_MASKED')),"
        f"'masked_is_original':os.getenv('SYNTHETIC_MASKED')=={MARKER!r},"
        "'proxy_present':bool(os.getenv('HTTPS_PROXY') or os.getenv('https_proxy'))};"
        "\ntry:r['controller_read']=p.read_text()=="
        f"{MARKER!r}\nexcept OSError:r['controller_read']=False\n"
        "print('CREDENTIAL_PROBE='+json.dumps(r))"
    )
    path = workspace / "credential_probe.py"
    path.write_text(script, encoding="utf-8")
    return shlex.join(["/usr/bin/python3", str(path)])


def parse_credential_result(result):
    matches = re.findall(r"^CREDENTIAL_PROBE=(\{[^\n]+\})$",
                         result.get("textResultForLlm", ""), re.MULTILINE)
    if len(matches) != 1 or not sandbox_applied(result):
        raise AssertionError("Missing unique sandboxed credential probe result")
    exits = [x for x in result.get("contents", []) if x.get("type") == "shell_exit"]
    if len(exits) != 1 or type(exits[0].get("exitCode")) is not int or exits[0]["exitCode"] != 0:
        raise AssertionError("Credential probe shell did not complete successfully")
    return json.loads(matches[0])


async def experiment(cli, base, port, evidence):
    from copilot import CopilotClient, RuntimeConnection
    from copilot.rpc import (
        AgentSelectRequest, CommandsInvokeRequest, ModeSetRequest,
        PermissionDecisionApproveOnce, PermissionDecisionReject, SandboxConfig,
        SandboxConfigSource, SessionAgentListRequest, SessionUpdateOptionsParams,
        ToolsExecuteRequest,
    )

    workspace, denied = base / "workspace", base / "denied"
    for folder in (workspace, denied, base / "home", base / "config", base / "tmp"):
        folder.mkdir(mode=0o700)
    controller = denied / "controller-config"
    controller.write_text(MARKER)
    config = policy(workspace, denied)
    # Opt-in masking boundary only: outbound remains blocked, no HTTPS request is sent.
    config["sandbox"]["credentials"] = {
        "envVars": {"SYNTHETIC_MASKED": {"injectHosts": ["example.invalid"]}}}
    evidence["policy"] = config
    command = shell_payload(workspace, controller)
    env = {
        "PATH": os.environ["PATH"], "HOME": str(base / "home"),
        "XDG_CONFIG_HOME": str(base / "home" / ".config"),
        "XDG_CACHE_HOME": str(base / "home" / ".cache"), "TMPDIR": str(base / "tmp"),
        "COPILOT_DISABLE_KEYTAR": "1", "COPILOT_TELEMETRY_DISABLED": "1",
        "DO_NOT_TRACK": "1", "SYNTHETIC_INHERITED": MARKER, "SYNTHETIC_MASKED": MARKER,
    }
    client = CopilotClient(
        connection=RuntimeConnection.for_stdio(path=str(cli), args=["--sandbox"]),
        working_directory=str(workspace), base_directory=str(base / "config"),
        env=env, use_logged_in_user=False,
    )
    session = None
    events = []
    evidence["sessions"] = {}
    try:
        await asyncio.wait_for(client.start(), 45)
        # Separate sessions avoid permission caching and hook state contamination.
        for mode in ("hook-deny", "reject", "exception", "hook-exception", "credentials"):
            row = evidence["sessions"][mode] = {
                "permissions": [], "pre_tool_hooks": [], "user_inputs": [], "plan_exits": []}
            evidence["stage"] = mode + ".create"

            def permission(request, _):
                data = request.to_dict()
                row["permissions"].append(data)
                if mode == "exception":
                    raise ValueError("SYNTHETIC permission callback exception")
                if mode == "credentials" and permitted(data, command):
                    return PermissionDecisionApproveOnce()
                return PermissionDecisionReject()

            def hook(request, _):
                row["pre_tool_hooks"].append(request)
                if request["toolName"] in ("ask_user", "exit_plan_mode"):
                    return None  # Reach the independent refusal handlers.
                if mode == "hook-exception":
                    raise ValueError("SYNTHETIC pre-tool callback exception")
                return {"permissionDecision": "deny"}

            def user_input(request, context):
                row["user_inputs"].append({"request": request, "context": context})
                return {"answer": "SYNTHETIC refusal; not plan authorization", "wasFreeform": True}

            def plan_exit(request, context):
                row["plan_exits"].append({"request": request, "context": context})
                return {"approved": False, "feedback": "SYNTHETIC refusal"}

            session = await asyncio.wait_for(client.create_session(
                model="synthetic-no-inference",
                provider={"type": "openai", "base_url": f"http://127.0.0.1:{port}/v1"},
                on_permission_request=permission, on_user_input_request=user_input,
                on_exit_plan_mode_request=plan_exit,
                hooks={"on_pre_tool_use": hook} if mode in ("hook-deny", "hook-exception") else None,
                on_event=lambda event: events.append(event.to_dict()),
                working_directory=str(workspace), plugin_directories=[str(PLUGIN)],
                disabled_mcp_servers=["context7", "microsoft-docs", "playwright"],
                available_tools=["bash", "view", "create", "ask_user", "exit_plan_mode", "skill"],
                skip_custom_instructions=True, enable_config_discovery=False,
                enable_file_hooks=False, enable_skills=True, enable_host_git_operations=False,
                enable_session_store=False, skip_embedding_retrieval=True,
                enable_session_telemetry=False, included_builtin_skills=[],
            ), 45)
            update = await session.rpc.options.update(SessionUpdateOptionsParams(
                sandbox_config=SandboxConfig.from_dict(config["sandbox"]),
                sandbox_config_source=SandboxConfigSource.SESSION_FLAG,
            ), timeout=20)
            if not update.success:
                raise AssertionError("Sandbox policy update failed")
            readback = await session.rpc.commands.invoke(
                CommandsInvokeRequest(name="sandbox", input="policy"), timeout=20)
            row["policy_readback"] = readback.to_dict()
            row["effective_policy"] = verify_effective_policy(
                row["policy_readback"], config["sandbox"])

            async def execute(name, arguments):
                evidence["stage"] = mode + "." + name
                try:
                    result = await session.rpc.tools.execute(
                        ToolsExecuteRequest(name=name, arguments=arguments), timeout=45)
                except TimeoutError:
                    raise  # Unknown in-flight effects: stop, disconnect, never retry.
                except Exception as error:
                    evidence["blockers"].append(f"{mode}.{name}: RPC failed: {error}")
                    return {"rpc_error": f"{type(error).__name__}: {error}"}
                return result.to_dict() if hasattr(result, "to_dict") else result

            if mode == "hook-deny":
                inventory = await session.rpc.agent.list(
                    SessionAgentListRequest(include_prompt=True), timeout=30)
                evidence["agents"] = [agent_evidence(a.to_dict(), PLUGIN) for a in inventory.agents]
                expected_agents = {p.stem.removesuffix(".agent") for p in (PLUGIN / "agents").glob("*.agent.md")}
                matched_agents = {local_agent_name(a["name"]) for a in evidence["agents"]
                                  if a.get("path_matches") and a.get("prompt_matches")}
                evidence["agent_content_gaps"] = sorted(expected_agents - matched_agents)
                if evidence["agent_content_gaps"]:
                    evidence["blockers"].append("Some authored agents lack matching native path/prompt evidence")
                lead = next((a for a in inventory.agents if a.name == "agile-agents-core:dev-lead"), None)
                if lead is not None:
                    selected = await session.rpc.agent.select(AgentSelectRequest(name=lead.id), timeout=20)
                    current = await session.rpc.agent.get_current(timeout=20)
                    evidence["agent_selected"] = selected.to_dict()
                    evidence["agent_current"] = current.to_dict()
                    await session.rpc.agent.deselect(timeout=20)
                else:
                    evidence["blockers"].append("Native plugin discovery did not find dev-lead")
                await session.rpc.skills.ensure_loaded(timeout=30)
                skills = await session.rpc.skills.list(timeout=20)
                evidence["skills"] = []
                for skill in skills.skills:
                    item = skill.to_dict()
                    source = PLUGIN / "skills" / skill.name / "SKILL.md"
                    if source.is_file():
                        item["source_sha256"] = sha(source.read_bytes())
                        item["path_matches"] = skill.path == str(source)
                    evidence["skills"].append(item)
                expected_skills = {p.parent.name for p in (PLUGIN / "skills").glob("*/SKILL.md")}
                matched_skills = {s["name"] for s in evidence["skills"]
                                  if s.get("path_matches") and s.get("enabled")}
                evidence["skill_discovery_gaps"] = sorted(expected_skills - matched_skills)
                if evidence["skill_discovery_gaps"]:
                    evidence["blockers"].append("Some authored skills lack enabled native path evidence")
                # No generated plan, fake model, delegation or model selection is claimed.
                evidence["worker_list"] = {
                    "declared": json.loads(re.search(
                        r"^agents: (\[.*\])$", (PLUGIN / "agents/dev-lead.agent.md").read_text(),
                        re.MULTILINE)[1]),
                    "runtime_restriction": "NOT_EXPOSED_BY_AGENT_INFO; NOT_PROVED",
                }

            await session.rpc.tools.initialize_and_validate(timeout=30)
            row["tool_metadata"] = (await session.rpc.tools.get_current_metadata(timeout=20)).to_dict()
            if mode == "hook-deny":
                row["ask_user_result"] = await execute("ask_user", {
                    "question": "SYNTHETIC direct-tool input round trip; refuse approval",
                    "allowFreeform": True})
                if not row["user_inputs"]:
                    evidence["blockers"].append("Native ask_user did not reach input callback")
                # Native plan-mode callback mechanics, not semantic plan provenance.
                row["mode_update"] = (await session.rpc.mode.set(
                    ModeSetRequest.from_dict({"mode": "plan"}), timeout=20)).to_dict()
                await session.rpc.tools.initialize_and_validate(timeout=30)
                row["plan_result"] = await execute("exit_plan_mode", {
                    "summary": "SYNTHETIC direct-tool plan refusal; no authored agent plan"})
                row["mode_after_refusal"] = str(await session.rpc.mode.get(timeout=20))
                if not row["plan_exits"]:
                    evidence["blockers"].append("Native exit_plan_mode did not reach plan callback")
                await session.rpc.mode.set(ModeSetRequest.from_dict({"mode": "interactive"}), timeout=20)
                await session.rpc.tools.initialize_and_validate(timeout=30)

            if mode != "credentials":
                marker = workspace / ("mutation-" + mode)
                before_permissions, before_hooks = len(row["permissions"]), len(row["pre_tool_hooks"])
                result = await execute("bash", {
                    "command": "printf synthetic > " + shlex.quote(str(marker)),
                    "description": "SYNTHETIC controller denial probe", "mode": "sync", "initial_wait": 10})
                row["mutation"] = mutation_observation(
                    marker, row["permissions"][before_permissions:],
                    row["pre_tool_hooks"][before_hooks:], result)
                if not row["mutation"]["controller_denial_proved"]:
                    evidence["blockers"].append(f"{mode}: direct bash did not prove controller denial")
                # Independent in-process file-tool path; fixed synthetic target only.
                target = base / ("outside-" + mode)
                before_permissions, before_hooks = len(row["permissions"]), len(row["pre_tool_hooks"])
                result = await execute("create", {"path": str(target), "file_text": "SYNTHETIC"})
                row["file_mutation"] = mutation_observation(
                    target, row["permissions"][before_permissions:],
                    row["pre_tool_hooks"][before_hooks:], result)
                if target.exists():
                    evidence["blockers"].append(f"{mode}: in-process file mutation escaped denial")
                row["dependent_plan_execution"] = "NOT_RUN: no authorized semantic plan"
            else:
                # Independent containment measurements; no authorization claim.
                row["file_read"] = await execute("view", {"path": str(controller)})
                row["file_marker_visible"] = MARKER in json.dumps(row["file_read"])
                row["shell_result"] = await execute("bash", {
                    "command": command, "description": "SYNTHETIC credential boundaries",
                    "mode": "sync", "initial_wait": 10})
                row["credential_probe"] = parse_credential_result(row["shell_result"])
                row["controller_file_unchanged"] = controller.read_text() == MARKER
                if row["credential_probe"]["inherited_marker"]:
                    evidence["blockers"].append("Unconfigured inherited environment marker reaches shell")
                if row["file_marker_visible"] or row["credential_probe"]["controller_read"]:
                    evidence["blockers"].append("Controller marker file readable")
                if row["credential_probe"]["masked_is_original"]:
                    evidence["blockers"].append("Configured credential masking leaked synthetic original")

            await asyncio.wait_for(session.disconnect(), 15)
            session = None
        evidence["events"] = events
        sys.path.insert(0, str(REPO / "eval/deepeval"))
        from adapters.copilot_trace import parse_log_text, verify_schema
        trace = parse_log_text("\n".join(json.dumps(e) for e in events))
        evidence["trace_contract"] = {
            "events_parsed": trace.events_parsed, "tools": trace.tool_names,
            "skills_offered": trace.skills_offered, "turns": trace.turns,
            "schema_gaps": verify_schema(trace),
            "grade": "NOT_PRODUCED: native direct RPC results are not JudgeResult"}
    finally:
        await cleanup(session, client, evidence)


async def run(cli, evidence):
    require_hosted()
    from importlib.metadata import version
    if version("github-copilot-sdk") != "1.0.22":
        raise AssertionError("Unexpected SDK version")
    with tempfile.TemporaryDirectory(prefix="native-compatibility-") as temp, trap_server() as (port, requests):
        base = Path(temp)
        evidence["versions"] = {
            "sdk": version("github-copilot-sdk"),
            "cli": subprocess.check_output([str(cli), "--version"], text=True, timeout=15,
                                          env={"PATH": os.environ["PATH"], "HOME": temp}),
            "python": sys.version, "commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=REPO, text=True, timeout=10).strip()}
        if "1.0.98" not in evidence["versions"]["cli"]:
            raise AssertionError("Unexpected CLI version")
        try:
            await experiment(cli, base, port, evidence)
        finally:
            evidence["provider_requests"] = list(requests)
            evidence["model_send_calls"] = 0
            evidence["synthetic_model_events"] = False
        if requests or evidence.get("cleanup_errors"):
            raise AssertionError("Provider trap or cleanup failed")
    evidence["temporary_directory_removed"] = not base.exists()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("cli", type=Path)
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    evidence = {"experiment": "INCOMPLETE", "integration": "BLOCKED", "blockers": [],
                "scope": "native direct RPC; synthetic payloads; no model events"}
    try:
        asyncio.run(asyncio.wait_for(run(args.cli, evidence), 300))
        evidence["experiment"] = "COMPLETE"
    except Exception as error:
        evidence["error"] = f"{type(error).__name__}: {error}"
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(evidence, indent=2, default=str) + "\n")
    # Small public annotations; complete paths/hashes/results remain in the artifact.
    summary = {k: v for k, v in evidence.items() if k not in (
        "agents", "skills", "sessions", "events", "agent_selected", "agent_current", "policy",
        "trace_contract")}
    print(json.dumps(summary, indent=2, default=str))
    notices = {"summary": summary}
    notices["discovery"] = {
        "agents_count": len(evidence.get("agents", [])),
        "agent_names": [a["name"] for a in evidence.get("agents", [])],
        "agent_paths_matched": sum(a.get("path_matches", False) for a in evidence.get("agents", [])),
        "agent_prompts_matched": sum(a.get("prompt_matches", False) for a in evidence.get("agents", [])),
        "dev_lead": next(({k: v for k, v in a.items() if k not in ("description", "tools")}
                          for a in evidence.get("agents", [])
                          if local_agent_name(a["name"]) == "dev-lead"), None),
        "skills_count": len(evidence.get("skills", [])),
        "skill_paths_matched": sum(s.get("path_matches", False) for s in evidence.get("skills", [])),
        "selected": {k: v for k, v in evidence.get("agent_current", {}).get("agent", {}).items()
                     if k in ("name", "id", "path", "source")},
        "example_skill": next(({k: v for k, v in s.items() if k != "description"}
                               for s in evidence.get("skills", [])
                               if s["name"] == "acceptance-grading"), None)}
    if "trace_contract" in evidence:
        notices["trace"] = {**evidence["trace_contract"],
                            "skills_offered": sorted(set(evidence["trace_contract"]["skills_offered"]))}
    for mode, row in evidence.get("sessions", {}).items():
        notices[mode] = {
            k: v for k, v in row.items() if k not in (
                "tool_metadata", "policy_readback", "effective_policy", "pre_tool_hooks",
                "permissions", "shell_result", "file_read")}
        notices[mode]["permission_kinds"] = [p["kind"] for p in row["permissions"]]
        notices[mode]["hook_tools"] = [p["toolName"] for p in row["pre_tool_hooks"]]
        if "shell_result" in row:
            notices[mode]["shell_result"] = row["shell_result"]
            notices[mode]["file_read_error"] = row["file_read"].get("error")
    for key, value in notices.items():
        text = json.dumps(value, default=str).replace(
            "%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::notice title=Compatibility {key}::{text}")
    raise SystemExit(0 if evidence["experiment"] == "COMPLETE" else 1)


if __name__ == "__main__":
    main()

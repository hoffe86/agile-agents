#!/usr/bin/env node
// Eval-only host for a durable ask_user request. The real harness keeps its human gate.
import { spawnSync } from "node:child_process";
import { mkdtemp, readdir, readFile, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

class TransportError extends Error {}

function requireValue(condition, message) {
  if (!condition) throw new TransportError(message);
}

function parseArguments(argv) {
  const result = { plugins: [] };
  const names = new Set([
    "--phase", "--copilot", "--agent", "--session-id", "--max-ai-credits",
    "--timeout", "--prompt", "--request-id", "--tool-call-id", "--request-arguments",
  ]);
  for (let i = 0; i < argv.length; i += 2) {
    const name = argv[i];
    requireValue(i + 1 < argv.length, "Transport argument is missing a value.");
    if (name === "--plugin-dir") result.plugins.push(argv[i + 1]);
    else {
      requireValue(names.has(name) && result[name] === undefined, "Invalid transport argument.");
      result[name] = argv[i + 1];
    }
  }
  requireValue(["1", "2"].includes(result["--phase"]), "Invalid transport phase.");
  for (const name of ["--copilot", "--agent", "--session-id", "--max-ai-credits", "--timeout"]) {
    requireValue(typeof result[name] === "string" && result[name].length > 0,
      `Missing ${name}.`);
  }
  requireValue(result.plugins.length > 0, "No plugin directories were supplied.");
  if (result["--phase"] === "1") {
    requireValue(typeof result["--prompt"] === "string", "The task prompt is missing.");
  } else {
    for (const name of ["--request-id", "--tool-call-id", "--request-arguments"]) {
      requireValue(typeof result[name] === "string" && result[name].length > 0,
        `Missing ${name}.`);
    }
  }
  return result;
}

async function findRuntime(copilot, cache, timeout) {
  const env = { ...process.env, COPILOT_PKG_CACHE_HOME: cache, COPILOT_AUTO_UPDATE: "false" };
  const version = spawnSync(copilot, ["--version"], {
    env, encoding: "utf8", timeout: Math.min(timeout, 120_000),
    windowsHide: true,
  });
  requireValue(version.status === 0, "Could not initialize the Copilot CLI runtime.");
  const match = version.stdout.trim().split(/\r?\n/, 1)[0].match(
    /^(?:GitHub Copilot CLI\s+)?(\d+\.\d+\.\d+)\.?$/,
  );
  requireValue(match, "Could not determine the Copilot CLI runtime version.");
  const expected = process.env.COPILOT_CLI_VERSION;
  requireValue(!expected || match[1] === expected, "The Copilot CLI version is not the pinned version.");
  const packageRoot = join(cache, "pkg");
  const platforms = await readdir(packageRoot);
  const candidates = [];
  for (const platform of platforms) {
    const root = join(packageRoot, platform, match[1]);
    try {
      const [cli, sdk, manifest] = await Promise.all([
        stat(join(root, "index.js")),
        stat(join(root, "copilot-sdk", "index.js")),
        readFile(join(root, "package.json"), "utf8"),
      ]);
      if (cli.isFile() && sdk.isFile() && JSON.parse(manifest).version === match[1]) {
        candidates.push(root);
      }
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
  }
  requireValue(candidates.length === 1, "The bundled Copilot SDK could not be located.");
  return candidates[0];
}

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonical(value[key])]));
  }
  return value;
}

function listen(session, timeout) {
  let resolveTerminal;
  let rejectTerminal;
  let completion;
  const terminal = new Promise((resolve, reject) => {
    resolveTerminal = resolve;
    rejectTerminal = reject;
  });
  const timer = setTimeout(
    () => rejectTerminal(new TransportError("The Copilot session timed out.")),
    timeout,
  );
  const unsubscribe = session.on((event) => {
    process.stdout.write(`${JSON.stringify(event)}\n`);
    if (event.type === "tool.execution_complete") completion = completion || [];
    if (event.type === "tool.execution_complete") completion.push(event.data);
    if (event.type === "external_tool.requested"
        || (!event.agentId && ["session.idle", "session.error"].includes(event.type))) {
      clearTimeout(timer);
      resolveTerminal(event);
    }
  });
  return {
    terminal,
    completions: () => completion || [],
    close: () => { clearTimeout(timer); unsubscribe(); },
  };
}

const askUser = {
  name: "ask_user",
  description: "Ask the user a question and wait for an answer.",
  overridesBuiltInTool: true,
  skipPermission: true,
  parameters: {
    type: "object",
    properties: {
      question: { type: "string" },
      choices: { type: "array", items: { type: "string" } },
      allowFreeform: { type: "boolean" },
    },
    required: ["question"],
  },
};

async function main() {
  const args = parseArguments(process.argv.slice(2));
  const timeout = Number(args["--timeout"]) * 1000;
  requireValue(Number.isFinite(timeout) && timeout > 0, "Invalid transport timeout.");
  const deadline = Date.now() + timeout;
  const remaining = () => Math.max(1, deadline - Date.now());
  process.env.COPILOT_AUTO_UPDATE = "false";
  const cache = await mkdtemp(join(tmpdir(), "custom-eval-copilot-runtime-"));
  let client;
  let listener;
  let stage = "initializing";
  try {
    const runtime = await findRuntime(args["--copilot"], cache, remaining());
    const { CopilotClient, RuntimeConnection, approveAll } = await import(
      pathToFileURL(join(runtime, "copilot-sdk", "index.js")).href
    );
    client = new CopilotClient({
      connection: RuntimeConnection.forStdio({
        path: process.execPath,
        args: [join(runtime, "index.js"), "--max-ai-credits", args["--max-ai-credits"]],
      }),
      workingDirectory: process.cwd(),
      baseDirectory: process.env.COPILOT_HOME,
      builtinPluginDirectories: args.plugins,
    });
    const config = {
      workingDirectory: process.cwd(),
      tools: [askUser],
      onPermissionRequest: approveAll,
      includeSubAgentStreamingEvents: true,
    };
    await client.start();
    let session;
    if (args["--phase"] === "1") {
      stage = "starting the plan";
      session = await client.createSession({ ...config, sessionId: args["--session-id"] });
      await session.rpc.agent.select({ name: args["--agent"] });
      listener = listen(session, remaining());
      await session.send({ prompt: args["--prompt"] });
    } else {
      stage = "resuming the pending request";
      session = await client.resumeSession(args["--session-id"], {
        ...config, continuePendingWork: true,
      });
      listener = listen(session, remaining());
      const pending = await session.rpc.tools.listPendingRequests();
      const request = pending.items[0];
      requireValue(pending.items.length === 1 && request.requestId === args["--request-id"]
        && request.toolCallId === args["--tool-call-id"] && request.toolName === "ask_user"
        && !request.agentId, "The original root approval request is not pending.");
      const expected = JSON.parse(args["--request-arguments"]);
      requireValue(JSON.stringify(canonical(request.arguments)) === JSON.stringify(canonical(expected)),
        "The pending approval request does not match the judged question.");
      const result = await session.rpc.tools.handlePendingToolCall({
        requestId: request.requestId, result: "Approve and run autonomously",
      });
      requireValue(result.success === true, "The pending approval response was not accepted.");
    }
    const terminal = await listener.terminal;
    requireValue(terminal.type !== "session.error", "The Copilot session reported an error.");
    if (args["--phase"] === "2") {
      const matches = listener.completions().filter(
        (event) => event.toolCallId === args["--tool-call-id"],
      );
      requireValue(matches.length === 1 && matches[0].success === true
        && matches[0].result?.content === "Approve and run autonomously",
      "The original approval tool call did not complete with the judged answer.");
    }
    try {
      const usage = await session.rpc.usage.getMetrics();
      process.stdout.write(`${JSON.stringify({
        type: "result", sessionId: session.sessionId, exitCode: 0, usage,
      })}\n`);
    } catch {
      process.stdout.write('{"type":"eval.usage_unavailable","data":{}}\n');
    }
    if (terminal.type === "external_tool.requested") await session.rpc.suspend();
  } catch (error) {
    const message = error instanceof TransportError ? error.message
      : `Copilot SDK failed while ${stage}; check the CLI configuration.`;
    process.stdout.write(`${JSON.stringify({
      type: "eval.transport_error", data: { message },
    })}\n`);
    process.exitCode = 1;
  } finally {
    if (listener) listener.close();
    if (client) {
      const errors = await client.stop();
      if (errors.length) {
        process.stdout.write('{"type":"eval.transport_error","data":{"message":"Copilot SDK shutdown failed."}}\n');
        process.exitCode = 1;
      }
    }
    await rm(cache, { recursive: true, force: true });
  }
}

await main();

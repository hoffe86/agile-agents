"""Exercise the real Node transport with only its external CLI/SDK faked."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
TRANSPORT = ROOT / "eval/pipeline/copilot_approval_transport.mjs"
SDK = """
export const approveAll = () => ({kind: "approved"});
export const RuntimeConnection = {
  forStdio(options) {
    console.log(JSON.stringify({runtime: options}));
    return options;
  },
};
export class CopilotClient {
  constructor(options) {
    console.log(JSON.stringify({plugins: options.builtinPluginDirectories}));
  }
  async start() {}
  async createSession() {
    let callback;
    return {
      sessionId: "synthetic-session",
      on(handler) { callback = handler; return () => {}; },
      async send() {
        callback({type: "external_tool.requested", data: {}});
      },
      rpc: {
        agent: {async select() {}},
        usage: {async getMetrics() { return {}; }},
        async suspend() {},
      },
    };
  }
  async stop() { return []; }
}
"""


class CopilotApprovalTransportTests(unittest.TestCase):
    def run_transport(self, *, expected_version="1.0.105"):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required by the custom-eval transport")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preload = root / "fake-cli.mjs"
            # Patch the external process boundary, not the transport under test.
            preload.write_text(
                """
import childProcess from "node:child_process";
import {syncBuiltinESMExports} from "node:module";
import {mkdirSync, writeFileSync} from "node:fs";
import {join} from "node:path";
childProcess.spawnSync = (command, args, options) => {
  if (command !== "synthetic-copilot" || args.join() !== "--version") {
    throw new Error("Unexpected external command");
  }
  const runtime = join(options.env.COPILOT_PKG_CACHE_HOME, "pkg", "synthetic", "1.0.105");
  mkdirSync(join(runtime, "copilot-sdk"), {recursive: true});
  writeFileSync(join(runtime, "package.json"),
                JSON.stringify({version: "1.0.105", type: "module"}));
  writeFileSync(join(runtime, "index.js"), "");
  writeFileSync(join(runtime, "copilot-sdk", "index.js"), SDK_SOURCE);
  return {status: 0, stdout: "GitHub Copilot CLI 1.0.105\\n"};
};
syncBuiltinESMExports();
""".replace("SDK_SOURCE", json.dumps(SDK)),
                encoding="utf-8",
            )
            env = {key: os.environ[key] for key in ("PATH", "SystemRoot", "WINDIR")
                   if key in os.environ}
            env.update(HOME=str(root), USERPROFILE=str(root), TMPDIR=str(root),
                       TEMP=str(root), TMP=str(root), COPILOT_HOME=str(root / "copilot"),
                       COPILOT_CLI_VERSION=expected_version)
            result = subprocess.run(
                [node, "--import", preload.as_uri(), str(TRANSPORT),
                 "--phase", "1", "--copilot", "synthetic-copilot",
                 "--agent", "agile-agents-core:dev-lead", "--session-id", "synthetic-session",
                 "--max-ai-credits", "30", "--timeout", "10",
                 "--plugin-dir", "synthetic-core", "--prompt", "synthetic requirement"],
                env=env, capture_output=True, text=True, timeout=20, check=False,
            )
            self.assertEqual(list(root.glob("custom-eval-copilot-runtime-*")), [],
                             "The transport must remove its own runtime cache")
            return result

    def test_actual_sdk_runtime_keeps_privacy_and_cost_controls(self):
        result = self.run_transport()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        records = [json.loads(line) for line in result.stdout.splitlines()]
        (runtime,) = [row["runtime"] for row in records if "runtime" in row]
        self.assertEqual(runtime["args"][1:], [
            "--max-ai-credits", "30", "--no-auto-update", "--sync-session=off",
            "--secret-env-vars", "COPILOT_GITHUB_TOKEN,GH_TOKEN,GITHUB_TOKEN",
        ])
        self.assertNotIn("--no-ask-user", runtime["args"])
        self.assertEqual([row["plugins"] for row in records if "plugins" in row],
                         [["synthetic-core"]])
        self.assertTrue(any(row.get("type") == "external_tool.requested" for row in records))

    def test_pinned_runtime_mismatch_stops_before_sdk_start(self):
        result = self.run_transport(expected_version="0.0.0")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        records = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertFalse(any("runtime" in row for row in records))
        self.assertEqual(records, [{
            "type": "eval.transport_error",
            "data": {"message": "The Copilot CLI version is not the pinned version."},
        }])


if __name__ == "__main__":
    unittest.main()

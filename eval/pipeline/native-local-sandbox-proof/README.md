# Native local Copilot sandbox feasibility proof

This **synthetic infrastructure experiment** is separate from `worker-proof` and
`controller-proof`. It does not lift any live-evaluation hold, run a benchmark,
send a prompt, or authorize a model request. It provisions no cloud resources.
Local MXC/bubblewrap containment is **not a separate VM**.

## Execution and boundary

The path-filtered `native-local-sandbox-proof.yml` push workflow runs only on
`feat/live-evaluation-authorization`, on a fresh GitHub-hosted `ubuntu-24.04` runner.
It has a 15-minute job limit; each proof has a 240-second limit and shorter
operation timeouts. Checkout does not persist credentials. No Copilot/model
credentials or repository secrets are supplied to the experiment.

Runtime pins: standalone Copilot CLI **1.0.98** (official release SHA-256 and size
checked before extraction), Python **3.12.12**, SDK **1.0.22** and transitive wheels
with `pip --require-hashes`. Actions are commit-pinned. Linux prerequisites use the
signed **20261015T000000Z Ubuntu snapshot**; runner-provided base packages may be
newer and their actual versions and runner image identity are recorded. The
GitHub-hosted OS image is not immutable; that is a limitation of this proof.

The runner creates disposable HOME, COPILOT_HOME, XDG directories, workspace and
synthetic denied directory. Explicit policy disables outbound/local networking,
bypass, automatic developer-tool grants and Git/GitHub authentication. No local
workstation settings or OS trust stores are modified.

## Native, non-model route

The installed SDK 1.0.22's generated public RPC schema exposes these
**experimental** interfaces:

- `sandbox.getHostSupport`: host diagnostics; **not** execution proof.
- `session.tools.initializeAndValidate` and `getCurrentMetadata`: initialize and
  inspect the native offered tools without sending a turn.
- `session.tools.execute`: documented in the generated schema as executing a
  tool through the **native invocation pipeline**.

The proof requests the native `bash` tool through this route. It does not call
raw bubblewrap or wrap MXC itself. A missing RPC is an explicit **BLOCKED** result,
not an excuse to substitute an unrelated shell launcher. CLI 1.0.98 compatibility
must be established by the hosted execution, not inferred from SDK schemas.

The session uses a synthetic model identifier and a credential-free localhost
provider trap that rejects every request; any request makes acceptance fail.
There is no `session.send`, sampling, or compaction call. Only the exact synthetic
shell command may receive permission; bypass and policy escalation are rejected.
This tests native shell containment, **not** built-in in-process file tools,
remote MCP, or a hostile model. It is not a general security certification.

## Assertions and evidence

1. Unsandboxed positive controls: workspace and external synthetic sentinel
   reads/writes, shell execution, direct TCP to `example.com:443`, direct localhost
   TCP to the proof listener. No external request body is sent.
2. The same payload through Copilot: workspace read/write/command succeeds,
   execution is non-root, external sentinel access fails, outbound and localhost
   direct connections fail.
3. A real `bwrap` process is observed during native invocation, and the payload's
   user/mount/network namespace identifiers differ from the host controls. A
   saved preference or successful raw bwrap command alone cannot pass.
4. A separate fresh CLI process runs with `/usr/bin/bwrap` temporarily removed
   from PATH on the disposable runner. Only an explicit sandbox failure at the
   native tool execution boundary, with no output marker created, passes.
   A capability/RPC failure earlier in startup is **blocked**, not a successful
   unavailable-backend assertion. No claim about managed `failIfUnavailable`
   is inferred from newer documentation.
5. No provider requests. All assertions must pass; missing results fail closed.

Logs and a seven-day evidence artifact contain the policy, versions, pinned CLI
help, stage reached, native response/error, synthetic controls, assertions and
elapsed time. Compact results also appear in public check annotations, because
unauthenticated Actions log/artifact downloads may be refused. They do not upload
HOME, CLI sessions, environment dumps or secrets.
Temporary directories are removed; the missing-backend step restores bwrap even
on failure, and the workflow removes its CLI/venv. Runner disposal is the final
cleanup boundary. There are no invented token/AIU measurements.

Local pure tests (do not start Copilot):

```powershell
python -m unittest discover -s eval/pipeline/native-local-sandbox-proof -p test_proof.py -v
```

## Decisions and sources

Use the native experimental tool RPC rather than MCP bootstrap or custom MXC:
it tests the actual shell-tool pipeline with fewer moving parts. Cost: the pinned
CLI might not expose that SDK surface. If it does not, stop and report the exact
missing method; upgrading or using inference is a separate decision.

Read `copilot help sandbox` from the pinned hosted executable. The local
workstation CLI was 1.0.100 during research and is not version evidence for 1.0.98.
Current web documentation also differs from that local help on unsupported-host
fallback, which is why this proof tests behavior rather than trusting settings.

### Execution history

- Initial implementation: `adbf5ed7fac3efb42e579a58a69b392bd87365fe`,
  [hosted run 39398481935](https://github.com/hoffe86/agile-agents/actions/runs/39398481935).
  Prerequisite installation and 14 unit checks passed; SDK installation failed,
  so neither native assertion scenario ran. A local Linux-targeted pip dry-run
  reproduced a transcribed `h11` wheel checksum error. The one corrective round
  fixes that checksum, adds a hash-shape check, validates full Linux wheel
  resolution before push, and publishes compact results through annotations.

- [Official sandbox concepts and prerequisites](https://docs.github.com/en/copilot/concepts/security-governance-and-network-settings/about-cloud-and-local-sandboxes)
- [SDK public generated Python RPC schema](https://github.com/github/copilot-sdk/blob/main/python/copilot/generated/rpc.py)
- [CLI v1.0.98 release and integrity metadata](https://github.com/github/copilot-cli/releases/tag/v1.0.98)
- [Ubuntu snapshot service](https://snapshot.ubuntu.com/)

Profile: `cicd.platform` and `pipeline_paths` select GitHub Actions;
`infrastructure.iac_tool: none` and `deploy_verify: off` remain unchanged—this is
a user-authorized CI test, not infrastructure deployment. ADR 0008's deterministic
versus live-evaluation distinction and ADR 0015's pipeline-evaluation boundary
remain intact. No plugins, prior proofs or live-evaluation workflows are changed.

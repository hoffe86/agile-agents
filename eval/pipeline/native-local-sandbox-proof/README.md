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

The corrective activation attempt temporarily sets only
`kernel.apparmor_restrict_unprivileged_userns=0` on that disposable hosted runner.
This is the remedy explicitly suggested by CLI 1.0.98's failed namespace
diagnostic on Ubuntu 24.04. It permits unprivileged namespace creation; it does
not disable AppArmor, grant root to the payload, or replace the native sandbox.
The workflow records the existing value, tests `unshare --user --net true` as the
non-root runner user, and restores the value in its always-run cleanup.
Cancellation/host loss still relies on runner disposal. This VM-wide prerequisite
relaxation is appropriate only for this credential-free synthetic job, not a
workstation or shared runner.

## Native, non-model route

The installed SDK 1.0.22's generated public RPC schema exposes these
**experimental** interfaces:

- `sandbox.getHostSupport`: host diagnostics; **not** execution proof.
- `session.tools.initializeAndValidate` and `getCurrentMetadata`: initialize and
  inspect the native offered tools without sending a turn.
- `session.tools.execute`: documented in the generated schema as executing a
  tool through the **native invocation pipeline**.
- `session.options.update`: explicitly supplies `sandboxConfig` and
  `sandboxConfigSource: session_flag` before tool initialization. The pinned
  high-level Python `create_session` signature has no `sandbox_config` parameter;
  neither a settings file nor `--sandbox` alone establishes session propagation.
- `session.commands.invoke` with `sandbox policy`: requests native effective
  policy readback without inference. Before any negative tool probe, the harness
  parses the pinned CLI's ANSI text report and requires the requested grants,
  denials, blocked outbound/local network, disabled bypass, disabled developer
  grants/authentication, and sandboxed MCP/LSP routing. An unsupported
  command, unrecognized rendering, or policy mismatch is a **readiness blocker**,
  not evidence that containment passed or failed. An update acknowledgement alone
  cannot pass this gate. The exact raw readback is published for diagnosis.

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
   execution is non-root, external sentinel **read** fails, outbound and localhost
   direct connections fail. The payload attempts both a denied-directory marker
   write and a denied-sentinel overwrite. These operations may succeed in a
   private/masked view: `outside_directory_write` and `outside_sentinel_write`
   record operation outcomes, not host access. Acceptance requires **host
   integrity**, not operation-level write rejection: `host_sentinel_unchanged`
   requires the original regular file and bytes, and
   `host_denied_directory_unchanged` requires exactly the original `sentinel`
   entry (no added marker or other entry). The host positive control must perform
   both writes successfully; its effects are reset and the baseline checked
   before native execution. A private write success never excuses host mutation.
3. A real `bwrap` process is observed during native invocation, and the payload's
   user/mount/network namespace identifiers differ from the host controls. A
   saved preference or successful raw bwrap command alone cannot pass. Native
   telemetry must explicitly report `sandboxApplied:true` and
   `sandboxOptOutRequested:false`. Normal host readiness requires the `network`,
   `denied_paths` and `shell` capabilities, not just top-level `supported:true`.
4. A separate fresh CLI process runs with `/usr/bin/bwrap` temporarily removed
   from PATH on the disposable runner. Only an explicit sandbox-unavailable error
   in the native shell result, a completed **nonzero shell exit**, and no execution
   marker passes. `resultType: success` means the RPC request was handled, not
   that the command succeeded. The pinned response's single `shell_exit` record
   must have an integer nonzero `exitCode`, corroborated by telemetry `exit_code`
   and exactly one rendered shell completion with the same `shellId` and exit
   code. The structured `shellId` must be a nonempty string; telemetry in the
   observed response supplies an exit code, not a shell ID. Duplicate completions
   fail even when identical or when the final completion matches. Missing,
   ambiguous or contradictory exit evidence fails closed. An outer success
   wrapping exit 0 or an execution marker
   cannot pass; an outer failure without shell failure evidence cannot pass either.
   A capability/RPC failure earlier in startup is **blocked**, not a successful
   unavailable-backend assertion. No claim about managed `failIfUnavailable`
   is inferred from newer documentation.
5. No provider requests. All assertions must pass; missing results fail closed.
6. Session cleanup uses SDK 1.0.22's `disconnect()`, not the nonexistent
   `destroy()`. Client shutdown is attempted even if disconnect fails. Cleanup
   errors are recorded separately and prevent acceptance, without overwriting
   a native response or masking the original execution failure.

Logs and a seven-day evidence artifact contain the policy, versions, pinned CLI
help, stage reached, native response/error, synthetic controls, assertions and
elapsed time. Compact results also appear in public check annotations, because
unauthenticated Actions log/artifact downloads may be refused. They do not upload
HOME, CLI sessions, environment dumps or secrets.
Lifecycle/version fields share a summary; larger evidence fields have separate
annotations (at most ten per step) to avoid dropping or truncating decisive
responses behind version/diagnostic text.
Temporary directories are removed; the missing-backend step restores bwrap even
on failure, and the workflow removes its CLI/venv. Runner disposal is the final
cleanup boundary. There are no invented token/AIU measurements.

Local pure tests (do not start Copilot):

```powershell
python -m unittest discover -s eval/pipeline/native-local-sandbox-proof -p test_proof.py -v
```

Regression coverage includes private write success with an unchanged host,
sentinel mutation/removal/type replacement, added host files/directories,
transport success with command failure, exit 0 despite unavailable-error text,
actual execution-marker creation, generic errors, transport-only failures, and
missing/ambiguous/contradictory shell exit evidence, duplicate rendered
completions, contradictory rendered exits in both orders, and mismatched or
missing/invalid structured shell IDs. Existing read/network,
namespace, telemetry, policy readback, no-model and cleanup checks remain.

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
- Dependency repair: `e9979563ea95b6e59db424a4baffbaaf3ed56bae`,
  [hosted run 39399022251](https://github.com/hoffe86/agile-agents/actions/runs/39399022251).
  Fifteen unit tests and dependencies passed. The native shell returned
  `sandboxApplied:false`, host namespaces, and successful denied filesystem and
  network operations. Its missing-bwrap marker also executed. The native host
  diagnostic identified unavailable unprivileged user/network namespaces.
  A harness `destroy()` cleanup bug masked the normal assertions and overwrote
  the unavailable response. This was **not** a passing sandbox proof.
  The current narrow correction repairs that lifecycle, explicitly propagates
  session policy, adds a native readback gate, and enables only the documented
  ephemeral-runner namespace prerequisite. It does not change acceptance criteria
  to tolerate fallback.
- Readback-format correction: `2cfbb57585a38f0b581057b53b7338e936f45401`,
  [hosted run 39400508772](https://github.com/hoffe86/agile-agents/actions/runs/39400508772).
  Twenty-three tests, installation, namespace readiness and final cleanup passed.
  Native diagnostics reported all capabilities supported with bwrap installed.
  Both session policy updates succeeded, and native readback displayed the
  requested restrictions. The harness incorrectly expected JSON rather than the
  pinned native ANSI text report, so both scenarios stopped **before execution**.
  Zero provider requests and no cleanup errors were observed. The renderer is now
  covered by regression tests; this run is readiness evidence, not OS containment
  evidence, and does not count as a completed negative boundary test.
- Host-integrity/protocol correction baseline:
  `18c9964dd113a54ece2b28b0e906b2fd6b473437`,
  [hosted run 39401092928](https://github.com/hoffe86/agile-agents/actions/runs/39401092928).
  Twenty-four tests passed. Native execution reported sandbox applied/no opt-out,
  UID 1001, bwrap processes and separate user/mount/network namespaces. Workspace
  controls passed; outside read and outbound/direct localhost were blocked.
  The denied-directory write succeeded privately while the host sentinel stayed
  unchanged and no host marker appeared. Missing bwrap produced an explicit
  unavailable-sandbox error, shell exit 1 and no marker, wrapped in RPC
  `resultType: success`. Cleanup succeeded and provider requests stayed zero.
  This run failed two **incorrect assertions**, not those observed controls:
  `outside_write_denied` conflated host integrity with private operation rejection;
  `unavailable_rejected` conflated transport handling with command success.
  The user approved private denied-path writes on this disposable runner and
  replacing those claims with host-integrity and command-failure checks.
  `outside_unchanged` is now split into two named host checks and strengthened
  from absence of one marker to the exact directory entry set. No read denial,
  network, native activation, policy, cleanup or no-model condition was relaxed.
  This approved correction does not authorize live evaluation or silent fallback.

- [Official sandbox concepts and prerequisites](https://docs.github.com/en/copilot/concepts/security-governance-and-network-settings/about-cloud-and-local-sandboxes)
- [SDK public generated Python RPC schema](https://github.com/github/copilot-sdk/blob/main/python/copilot/generated/rpc.py)
- [CLI v1.0.98 release and integrity metadata](https://github.com/github/copilot-cli/releases/tag/v1.0.98)
- [Ubuntu snapshot service](https://snapshot.ubuntu.com/)

Profile: `cicd.platform` and `pipeline_paths` select GitHub Actions;
`infrastructure.iac_tool: none` and `deploy_verify: off` remain unchanged—this is
a user-authorized CI test, not infrastructure deployment. ADR 0008's deterministic
versus live-evaluation distinction and ADR 0015's pipeline-evaluation boundary
remain intact. No plugins, prior proofs or live-evaluation workflows are changed.

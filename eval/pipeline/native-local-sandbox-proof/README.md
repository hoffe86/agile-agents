# Native local Copilot sandbox feasibility proof

## Bounded controller/plugin compatibility verification

`compatibility.py` extends the **same** hosted workflow only after both original
sandbox scenarios pass. It keeps the original tests, pins and restrictions intact.
It uses native SDK RPC with the real core plugin directory, isolated HOME/config,
disabled plugin MCP servers, and the rejecting localhost provider trap. It never
sends a model turn, delegates a task, calls a judge, or enables the live runner.
All payloads, input questions and refusal answers are **synthetic**; there are no
synthetic model events and no claims about model-chosen skill use.

The experiment records native agent inventory, exact authored-body hashes and
source paths, dev-lead selection/readback, and enabled skill paths/source hashes.
The SDK 1.0.22 `AgentInfo` schema has no `agents` field: discovering declared
workers does **not** establish enforcement of dev-lead's worker list.
Separate sessions probe direct native tool callbacks with rejecting and raising
permission handlers, an explicitly denying pre-tool hook, user input and plan-exit
refusals. No callback invocation is fabricated by the test harness. Mutations are
checked in the host view; callback absence cannot prove controller denial.
Dependent delegated/plan execution is not attempted without semantic authorization.

An independent session uses entirely synthetic environment/file markers to compare
the native in-process `view` tool against sandboxed `bash`. Only the exact synthetic
shell command can receive `approve_once`; all other permissions are rejected.
`credentials.envVars.SYNTHETIC_MASKED.injectHosts: [example.invalid]` probes the
opt-in credential-masking boundary with outbound/local network still blocked.
It does **not** test real credentials, HTTPS substitution, destination enforcement,
remote MCP, or the controller process's own protection from a hostile peer process.
An unconfigured inherited marker is a deliberate negative control, not a secret.

`experiment: COMPLETE` means measurements finished, **not** readiness.
`integration: BLOCKED` is unconditional: permission approval is not plan
authorization, and direct RPC is not a live agent trace. Errors, negative findings,
provider requests and cleanup remain visible in artifacts/public annotations.
No production grading/admission implementation is changed.

Contract sources: pinned SDK `generated/rpc.py` (`AgentInfo`, `ToolsApi`,
`SandboxCredentialsConfig`) and `session.py` (separate input/plan callbacks);
[SDK skills documentation](https://github.com/github/copilot-sdk/blob/main/docs/features/skills.md);
ADRs [0008](../../../docs/adr/0008-layered-evaluation-strategy.md) and
[0015](../../../docs/adr/0015-deepeval-for-pipeline-evaluation.md).
The installed schema, not newer documentation, determines the tested signatures.

The existing `eval/deepeval/adapters/copilot_trace.py` accepts serialized event
envelopes with `type/data/id/parentId/timestamp`; `verify_schema` must expose absent
tool, turn and skills events rather than interpreting an empty direct-RPC trace as
agent behaviour. Native tool output is **not** a grade. `eval/grading.py` owns
`JudgeResult` schema v2 (claimed/normalized verdict, criteria, completeness,
verification and exit code); `eval/provenance.py` owns hashes and result bindings.
`metrics/acceptance.run_judge` still returns `verification_disabled`, and
`run-eval.{sh,ps1}` still block non-dry execution. This experiment removes no gates.

Local validation before hosted execution: 52 proof unit tests (39 unchanged,
13 new proof-logic tests), plus 172 existing trace/grading/provenance pytest tests.

Classifier-repair validation: **59 proof tests and 172 existing offline
trace/grading/provenance tests passed**. Replaying the raw mutation responses from
run 39424597215 changed exactly the two known false-negative flags, preserving all
other observation fields. The first repaired-SHA hosted attempt,
[39425671589](https://github.com/hoffe86/agile-agents/actions/runs/39425671589)
at `04694c686e2f785f39ad60692945b44894259369`, passed the unit step but failed
the unchanged Ubuntu prerequisite installation with exit 100. Native execution
was skipped; final runtime cleanup succeeded. Public annotations do not identify
the package-install cause, and unauthenticated log download was refused.
That attempt is **not native verification of the repair** and supplies no fresh
provider-trap or compatibility measurements. Dependency pins and workflow gates
were not changed to retry it.

First run: [39423365886](https://github.com/hoffe86/agile-agents/actions/runs/39423365886),
commit `0d68c80b66dd6342815c445faafcaf0219965960`. All original 15 available /
5 unavailable assertions passed. Native hooks denied mutations; 42 core skills
had matching source paths. The probe initially mishandled namespace-qualified
agent names and shadowed input/permission callbacks with its deny hook. One
corrective round maps `agile-agents-core:` names and separates explicit hook denial,
permission rejection, permission exception and hook-exception sessions. Input
tools reach their own refusing callbacks. This changes the experiment, not the
sandbox policy or original tests. First-run credentials already demonstrated an
unconfigured inherited marker reaching the shell, configured masking changing the
marker, and both file-tool and shell denial of the controller marker file.
### Executed result and limits (2026-10-20)

Corrected run:
[39424029975](https://github.com/hoffe86/agile-agents/actions/runs/39424029975),
commit **`ad361a9291dead5c9d5074c283e78cea52d14bb3`**.
GitHub-hosted `ubuntu-24.04`, image `20261018.339.1`; CLI 1.0.98,
SDK 1.0.22, Python 3.12.12. All workflow steps succeeded, including **52 unit
tests**, original **15 available / 5 unavailable** assertions, compatibility,
artifact publication and runner cleanup. Public evidence:
[check annotations API](https://api.github.com/repos/hoffe86/agile-agents/check-runs/118631909958/annotations?per_page=100).
Full synthetic evidence is in the seven-day `native-local-sandbox-proof` artifact.

**Integration remains BLOCKED. A green experiment is not a live readiness gate.**

1. **Real plugin discovery and selection: observed, not inferred from manifests.**
   Native inventory returned 15 namespace-qualified core agents, all with exact
   working-tree paths and `source: plugin`. Selection and current-agent readback
   both returned `agile-agents-core:dev-lead`. Its source-file SHA-256 was
   `a6900e5e88a135c3cab062e785f397f7413e9070f560592c53cd02c9bfaada48`.
   All seven workers declared by dev-lead were present in that inventory under
   namespace-qualified IDs. **Recognition/enforcement of the authored `agents:`
   restriction is not proved**: the returned SDK inventory has no worker-list
   field, and no delegate was executed. Despite `includePrompt: true`, no authored
   prompt text reached the inventory; all runtime-prompt hashes were the empty
   string hash. This is an introspection gap, **not proof that the runtime discarded
   the instructions**. Exact loaded instruction-content fidelity remains unverified.
   Native skill inventory returned all 42 core skills enabled at matching paths;
   source hashes were recorded. For example, `acceptance-grading`:
   `b27f9263066dd94d41019a365c49d6b7e91de89b10b92ccc0016ac8094e7856a`.
   No skill was chosen/read by a model. Companion plugins and external MCP
   servers were not exercised.

2. **Native callbacks: observed, including failure paths.**
   `session.tools.execute` **does run** the SDK pre-tool hook. Explicit hook denial
   blocked both `bash` and `create`, with no host mutation and no permission request.
   Without that hook, `bash` reached the permission callback: rejection returned
   `resultType: rejected`; a callback exception returned `resultType: denied`,
   reporting that user permission could not be obtained. Both left the host marker
   absent. A **pre-tool hook exception did not deny**: the shell proceeded to the
   permission callback, which rejected it. This demonstrates the difference between
   hook-only control and the separate permission boundary, not that every SDK
   controller is unsafe. In-process `create` outside writable paths was stopped by
   the sandbox file-policy check, before any permission callback.

   `ask_user` delivered a real native callback and its returned synthetic refusal
   appeared in the native tool response. `exit_plan_mode` delivered the separate
   callback with `summary`, actions, recommendation and **empty `planContent`**;
   the controller returned `approved: false`, the tool reported “Plan not approved”,
   and native mode readback remained `PLAN`. That proves callback delivery/return
   mechanics, **not authored-plan provenance, approval/resumption of an agent turn,
   or batch-policy authorization**. No approval was granted. No execution route
   was intentionally switched to bypass hooks. Alternate `shell.exec` and
   `shell.executeUserRequested` RPC paths were **not tested**; the successful
   `session.tools.execute` evidence must not be generalized to them.

   **Proof-classifier reporting repair:** the earlier classifier recognized only
   `resultType: denied`, producing false negatives for `reject` and
   `hook-exception`, also reproduced in
   [run 39424597215](https://github.com/hoffe86/agile-agents/actions/runs/39424597215)
   at `573d34ea65824849fa1608743aacd217d98fc4b4`. Both native responses were
   `rejected`, with a `permission_denied` category, one permission callback and
   no host mutation. The narrowly authorized repair accepts exact structured
   `resultType` values `denied` or `rejected`, still requiring a callback and no
   host mutation. A shell completion or RPC error contradicts controller denial
   and prevents that derived flag. Text such as “not rejected”, error prose or
   telemetry alone never establishes denial. Raw native responses, callback
   counts and host observations remain separate from the derived flag.
   Seven added offline regression tests cover these distinctions; all 39 original
   sandbox tests and 13 prior compatibility tests are unchanged (59 total).
   This repairs observation reporting, not live acceptance: `integration: BLOCKED`
   and the instruction-fidelity, environment and trace limitations remain.

3. **Synthetic credential boundaries: mixed, explicitly bounded.**
   An unconfigured inherited environment marker reached the sandboxed shell.
   An explicitly configured `SYNTHETIC_MASKED` value was present but was **not**
   the original marker. No HTTPS-proxy environment variable was observed;
   credential substitution over HTTPS was not tested. The denied controller marker
   file was unreadable through both built-in `view` (policy rejection) and sandboxed
   shell; its host bytes were unchanged. Shell telemetry confirmed sandbox applied
   and no opt-out. These are separate mechanisms: built-in in-process file checks
   are best-effort, not an OS process boundary; remote MCP is outside this OS sandbox.
   A disposable runner does not protect in-job credentials. Live controller secrets,
   alternate file/proc routes, HTTPS injection destination checks, proxy CA handling
   and remote MCP containment remain untested. No real credentials were supplied.

4. **DeepEval contract: parsing works, an evaluation trace/grade is still missing.**
   The unchanged adapter parsed **118 native event envelopes** and observed the
   offered skills. It found **zero tool-execution-start events and zero assistant
   turns**, and its existing schema checks flagged both. Direct-tool RPC results
   therefore cannot be presented as a live trajectory or silently converted into
   successful tool/skill-use evidence. An approved future agent-turn capture must
   satisfy the existing event contract without fabricating model events.
   `JudgeResult` v2, immutable baseline validation and result bindings remain the
   grading/provenance contracts; no replacement grade shape was introduced.
   `provenance.validate_result` currently accepts **only the dry/blocked execution
   contract**. An evidence-backed live admission extension is missing implementation,
   not a demonstrated DeepEval-engine incompatibility. All 172 existing offline
   trace/grading/provenance tests passed locally; no judge was invoked.

**No-model and cleanup evidence:** provider requests `[]`, model send calls `0`,
synthetic model events `false`, cleanup errors `[]`, temporary directory removed
`true`. The original scenarios also recorded no provider access and clean cleanup.
The always-run workflow cleanup/restoration step succeeded. No global workstation
configuration, plugin contracts, dependency pins, original proof tests, live runner
or judge gates were changed. Pre-existing dirty/untracked work was not staged.

### Remaining evidence contract before any live integration

- Confirm loaded authored instructions and worker selection/restriction semantics;
  distinguish inventory, actual skill invocation and delegated work.
- Bind an actual plan snapshot/digest to run, task, immutable inputs, harness,
  controller/session/delegate identities and an explicit human or authorized
  batch-policy approval reference. Prove no implementation before approval,
  rejection/cancellation/disconnect fail-closed behaviour, and invalidation after
  plan or scope changes. Permission approval is never a substitute for this record.
- Resolve credential placement and supported execution routes, test the intended
  synthetic proxy/transport boundary, and keep remote MCP disabled until separately
  assessed. A hook exception must not silently authorize mutations.
- Capture genuine model-turn/delegation events through the existing trace adapter;
  implement admission/result provenance without bypassing the current dry-only
  validator, then reuse the existing grading doctrine and `JudgeResult`.
- The repaired classifier reports direct-tool observations only; its derived flags
  and blocker array are not live admission gates.

This is a completed negative feasibility experiment, not permission for a paid
canary. Full task-05, all live benchmarks and model judges remain disabled.
No live-canary scope is authorized or recommended as ready by this result.

**Trade-off:** direct native RPC was chosen over a synthetic model server to keep
this verification small and zero-inference. It provides genuine tool/callback
mechanics, but cannot establish model-selected skills, authored-plan semantics or
delegation fidelity. Revisit only in an explicitly approved, separately bounded
follow-up; do not grow this proof into a replacement orchestration layer.

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

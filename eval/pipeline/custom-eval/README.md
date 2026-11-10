# `custom-eval/` — 10 framework-representative evaluation tasks

## What this is

Hand-written tasks chosen to exercise the **breadth** of the dev-lead agent suite and the
typical surface area of a real-world software delivery engagement. Each task is one folder under
`tasks/task-NN-<slug>/` containing a prompt, acceptance contract, operational
profile, and versioned input declaration:

| File | Purpose |
|---|---|
| `prompt.md` | The requirement fed verbatim to `dev-lead` |
| `acceptance.md` | 3-5 explicit, verifiable pass criteria |
| `solution-profile.yaml` | Synthetic profile conforming to the shipped solution-profile contract |
| `inputs.json` | Versioned list of required baseline inputs and their workspace destinations |
| `expectations.yaml` | Trajectory contract: plan gate, which agents dev-lead delegates to, which skills each one must invoke |
| `baseline/` | Minimal synthetic or task-directed source inputs; never includes the requested answer |

A run has two halves, kept in separate trust zones:

- **Runner** (`../run_custom_eval.py`) stages the baseline into a fresh git workspace, attempts
  to drive `dev-lead` through the Copilot CLI to its plan gate, and has an LLM judge the plan
  before resuming the *same* pending request. It captures `produced.diff` against the staged
  baseline and runs the task's acceptance **checks** (see below) in that workspace, recording
  `checks.json`. Missing or unverified approval evidence blocks the resume.
- **Scorer** (`../score_custom_eval.py`) reads only the recorded JSONL logs, `state.json`,
  `plan-approval.json`, `produced.diff` and `checks.json`. Trajectory is scored with **DeepEval**
  (`ToolCorrectnessMetric`); command results decide build/test/render criteria; the rest goes
  to a pluggable judge. It runs no git and no workspace code, so it can hold judge
  credentials safely.

The live agent is **not OS-sandboxed** — it runs with every tool allowed on the host, which
is why the runner refuses to start without `--unsandboxed`. The checks run in that same trust
zone, after the diff is captured (so build output never becomes evidence), with an
allowlisted environment that carries no tokens or cloud credentials. That adds nothing the
agent could not already do; it is not isolation. A sandboxed worker is
[#22](https://github.com/hoffe86/agile-agents/issues/22).

Profiles populate the six required Stage-0 fields from the shipped template, set
`backlog.create_tasks: false`, quote `infrastructure.deploy_verify: "off"`, and use
`quality_gates.test_bar` check blocks (`lint`, `typecheck`, `unit_test`,
`integration_test`, `coverage`) with argv lists. Documentation-only tasks disable the
test bar with an explicit reason. These declarations describe intended task conditions;
they do not authorize execution or bypass dev-lead's mandatory plan-approval gate.

## The 10 tasks

| # | Slug | Surface |
|---|---|---|
| 01 | `csharp-minimal-api-endpoint`       | C# / ASP.NET Minimal API + xUnit (csharp-implementation, csharp-testing) |
| 02 | `python-di-refactor`                | Python refactor + DI (python-implementation, code-review-checklist) |
| 03 | `bicep-storage-waf`                 | Bicep + Azure WAF baseline (bicep-implementation, iac-best-practices) |
| 04 | `adr-library-tradeoff`              | ADR authoring (architecture-decision-records, trade-off-reporting) |
| 05 | `pr-description`                    | Release-notes / PR-description authoring (engineering-standards) |
| 06 | `gha-oidc-deploy`                   | GitHub Actions + OIDC to Azure (cicd-pipeline-implementation) |
| 07 | `test-coverage-uplift`              | Unit + integration test backfill (csharp-testing, code-review-checklist) |
| 08 | `threat-model-api`                  | Threat-modelling (security-reviewer reviewer agent) |
| 09 | `polly-resilience`                  | Resilience patterns on HTTP client (cloud-native-patterns, csharp-implementation) |
| 10 | `helm-to-kustomize`                 | K8s migration (helm-kustomize-implementation, iac-best-practices) |

The 10 tasks together touch every author agent (coding × 2 stacks — implementation *and* the
tests that cover it, infrastructure, architect) and every reviewer agent (code-reviewer,
architecture-reviewer, security-reviewer, test-reviewer, infra-review).

## Running

```powershell
# Local: the plan approver needs Azure configuration and an authenticated az session.
python eval/pipeline/run_custom_eval.py task-05 --out $env:TEMP\ce\task-05 --unsandboxed
python eval/pipeline/run_custom_eval.py task-05 --out $env:TEMP\ce\dry --dry-run   # stage only
# Alternatively, run the three phases separately with a fresh output directory.
python eval/pipeline/run_custom_eval.py task-05 --out $env:TEMP\ce\split --phase 1 --unsandboxed
python eval/pipeline/run_custom_eval.py task-05 --out $env:TEMP\ce\split --phase approve
python eval/pipeline/run_custom_eval.py task-05 --out $env:TEMP\ce\split --phase 2 --unsandboxed
# Re-run only the acceptance checks of a finished run, e.g. after installing a missing tool.
python eval/pipeline/run_custom_eval.py task-05 --out $env:TEMP\ce\task-05 --phase verify --unsandboxed
# Score one or more runs. --judge none leaves criteria without a passing check UNVERIFIED.
python eval/pipeline/score_custom_eval.py $env:TEMP\ce\task-05 --judge azure-openai --output summary.json
```

Needs the Copilot CLI on `PATH` (pinned `1.0.105` in CI), a nonempty
`COPILOT_GITHUB_TOKEN` or `GITHUB_TOKEN`, and the hash-locked environment from
[`../../deepeval/README.md`](../../deepeval/README.md). Local runs can keep using
`COPILOT_GITHUB_TOKEN`; GitHub Actions supplies `GITHUB_TOKEN` automatically.
`--max-ai-credits` caps each phase (minimum 30). The plan approver always uses Azure OpenAI;
the acceptance judge is selected separately. Azure OpenAI authenticates with Entra only —
`az login` locally, federated `azure/login` in CI; no API key is accepted — and reads
`AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_DEPLOYMENT`. Unset `AZURE_OPENAI_API_KEY` and
`AZURE_OPENAI_AD_TOKEN`, even if empty: the underlying client otherwise picks them up in
addition to or instead of the Azure CLI token. Set the endpoint to the Azure resource URL,
for example `https://<resource>.openai.azure.com/` or
`https://<resource>.services.ai.azure.com/`, not a project URL or a Responses API operation URL.
The deployment must support Azure's deployment-based Chat Completions API. The default API
version is `2024-10-21`; local runs can override it with `AZURE_OPENAI_API_VERSION`.

In CI, run **Eval · custom-eval live run** (`.github/workflows/eval-custom.yml`) by hand.
GitHub registers it for manual dispatch only after the workflow file is on the default branch;
select the branch to evaluate when starting the run.

| Job | Holds | Does |
|---|---|---|
| `plan` | `GITHUB_TOKEN` with `contents: read` and `copilot-requests: write` | phase 1; writes the plan to the step summary (runs the checks only if dev-lead skipped the gate) |
| `approve` | OIDC and `contents: read`; no `copilot-requests` permission | the simulated approver judges the plan and outputs `approved` or `rejected`; runs no agent |
| `implement` | same as `plan` | runs only when `approve` succeeds with an `approved` decision, then resumes and runs the checks |
| `score` | OIDC and `contents: read`; no `copilot-requests` permission | DeepEval + judge over the recorded files; runs no agent |

The agent jobs install .NET 10 for the C# tasks and a pinned, checksum-verified `actionlint`
for task 06; `kubectl`, `az` and Docker come with the runner image. Locally, a tool missing
from `PATH` leaves its criterion `UNVERIFIED`.

The pinned `actionlint` 1.7.12 predates the `copilot-requests` permission. When linting
this workflow with it, exclude only that false positive:

```powershell
actionlint -ignore 'unknown permission scope "copilot-requests"\.' .github\workflows\eval-custom.yml
```

GitHub provides a short-lived `GITHUB_TOKEN`; no Copilot PAT or `EVAL_COPILOT_TOKEN` secret
is needed. The unsandboxed agent can read this token while it runs. Usage in a personally
owned repository is billed to the owner's Copilot seat; an organization-owned repository
must enable the Copilot CLI organization-billing policy. See
[Copilot CLI in GitHub Actions](https://docs.github.com/en/copilot/concepts/agent-capabilities/agent-powered-workflows-and-operations/copilot-cli-in-github-actions).

Configure these repository variables under **Settings > Secrets and variables > Actions >
Variables**:

| Variable | Value |
|---|---|
| `EVAL_AZURE_CLIENT_ID` | Client ID of the Entra application or user-assigned managed identity |
| `EVAL_AZURE_TENANT_ID` | Tenant ID of that identity |
| `EVAL_AZURE_OPENAI_ENDPOINT` | Azure OpenAI resource URL, as described above |
| `EVAL_AZURE_OPENAI_DEPLOYMENT` | Name of the deployed Chat Completions model |

Give the identity a GitHub OIDC federated credential for the branch selected when dispatching
the workflow. For these jobs, which do not use a GitHub environment, the issuer is
`https://token.actions.githubusercontent.com` and the audience is `api://AzureADTokenExchange`.
The subject must match the token's **exact** `sub` claim. Depending on the repository's OIDC
settings, the default branch subject uses either
`repo:<owner>/<repo>:ref:refs/heads/<branch>` or the immutable format
`repo:<owner>@<owner-id>/<repo>@<repo-id>:ref:refs/heads/<branch>`. Customized subject
claims can have a different format. The `azure/login` step reports the presented subject;
`AADSTS700213` means no configured credential matched the token's trust values. Compare
the issuer, subject, and audience, and configure a matching credential for each branch
that is allowed to run the evaluation.

Assign the identity `Cognitive Services OpenAI User` on the Azure OpenAI resource, or another
role that grants the required inference access. See the
[GitHub OIDC subject reference](https://docs.github.com/en/actions/reference/security/oidc#immutable-subject-claims),
[OIDC setup](https://learn.microsoft.com/azure/developer/github/connect-from-azure-openid-connect),
and [Azure OpenAI roles](https://learn.microsoft.com/azure/foundry-classic/openai/how-to/role-based-access-control#summary).
No approval environment, human reviewer, or stored client secret is needed.

## Simulated plan approval (eval-only)

dev-lead's Stage 4 plan approval is a quality gate, so an unattended run can have it judged
rather than rubber-stamped. The Azure OpenAI judge grades the plan
against [`plan-approval.md`](plan-approval.md) — seven shared criteria (Definition of Done and
scope, decomposition, coverage of the stated acceptance criteria, derived criteria shown
separately, assumptions and risks, no scope expansion, approval asked before execution) plus
any task-specific ones under `plan_approval:` in `expectations.yaml` (needs
`plan_gate: required`). Each criterion is `PASS`, `FAIL` or `UNVERIFIED`; the plan is
**approved only if every criterion passes**. The approver sees the requirement (`prompt.md`),
the preceding plan message, and the exact approval question — what a human sees — never
`acceptance.md`. The question itself may contain the plan. Missing evidence must be judged
`UNVERIFIED`; an oversized plan is rejected without making a model call.

The runner uses the pinned Copilot CLI's bundled SDK to suspend at the top-level `ask_user`
request and resume that same request after approval. This internal SDK interface is tied to
the pinned CLI version. Synthetic probes on Windows and Linux verified suspension, cold
resume, the matching tool response, and delegated skill attribution. Real `dev-lead` probes
have not yet completed this path: one did not request approval and another delegated
implementation before approval. The runner reported `blocked_approval` and `gate_skipped`,
respectively, rather than treating either as a passed gate. A separate Actions smoke test
authenticated the pinned CLI with `GITHUB_TOKEN`, but did not exercise the SDK transport.
The Azure judge and cross-job artifact flow are not yet verified end to end.

The violation detector recognizes implementing-agent delegations and top-level write tools;
it does not detect writes performed through shell commands.

The decision is written to `plan-approval.json`, labelled `llm-simulated`, and scored as its
own metric, `Plan approval (llm-simulated)`. A rejection **ends the run** as **failed**
(`plan_rejected`): there is no re-plan round. It is evidence about the plan, never a human
approval — the harness's own human gate outside evaluation is unchanged.

Trust: the approve step holds the judge credentials but runs no agent. Phase 1 deletes any
pre-existing `plan-approval.json`, and in CI `implement` is gated on the `approve` job's
successful output and a complete decision record — not on anything the agent can write —
while `score` takes the record from the `approve` job's artifact. Local runs are not
sandboxed: the agent can access credentials available to the invoking user.

## Trajectory expectations

`expectations.yaml` says what a correct *process* looks like, independent of the output:

```yaml
schema: 1
root_agent: dev-lead
plan_gate: required            # approval must be requested before implementation
agents: [coding, review-lead, code-reviewer]   # every one must be delegated to
skills:                        # per agent: each must be invoked by that agent
  coding: [read-repo-context, development-practices, python-implementation]
  any: [architecture-decision-records]          # invoked by anyone in the run
forbidden_skills:
  review-lead: [code-review-checklist]          # the orchestrator performs no lens
```

Each agent's skill list scores as its own DeepEval metric (`skills:<agent>`), so a miss is
attributed to the agent that should have loaded the skill. Tool-call starts are reported as
attempts; a load receives credit only when its matching completion reports success. A
missing completion is `UNVERIFIED`, not a pass or an agent failure. Delegation receives credit
when the named agent starts or the task call succeeds; a failed attempt is not a successful
delegation, and an incomplete attempt is `UNVERIFIED`. An attempted implementing-agent
delegation before approval still violates the plan gate. Lists hold the **core contract
loads** an agent's own definition makes mandatory — not every skill a good run might touch —
so a pass means the contract was honoured, not that the run was optimal. `any` exists for
deliverable skills whose author varies (an ADR may be drafted by dev-lead or a reviewer).
Task-10 lists criterion 2 under `unverifiable` with its reason (see fixture boundaries).

## Acceptance checks

A criterion about behaviour — it builds, its tests pass, it renders, it validates — is
decided by running a command, not by a model reading source. `expectations.yaml` declares
those commands:

```yaml
checks:
  - criterion: 1
    run: [dotnet, build, Orders.slnx, -warnaserror]   # argv, never a shell string
  - criterion: 3
    run: ["{python}", -m, pytest, -q, -p, no:cacheprovider]
    requires: [["{python}", -m, pytest, --version]]  # probe; failing => UNVERIFIED
    on_pass: judge          # passing proves only part of the criterion
    timeout: 600            # seconds, 1-3600; cwd: is workspace-relative
  - criterion: 1
    run: [az, bicep, build, --file, main.bicep, --stdout]
    fail_if_output_matches: '\(\d+,\d+\) : (Warning|Error) '   # exit 0 but linter warned
```

Per criterion: any check **failed** or **timed out** → `FAIL`, whatever the judge says; else
any **unavailable** (tool not on `PATH`, probe failed) → `UNVERIFIED` — a missing toolchain is
never charged to the agent; else all passed → `PASS`, unless a check says `on_pass: judge`,
in which case the judge grades the remaining clause (with `--judge none` it stays
`UNVERIFIED`). Command output is also shown to the judge as untrusted evidence. Declared
checks with no matching `checks.json` leave their criteria `UNVERIFIED`; rerun
`--phase verify`. Checks run only for runs that reached `complete` or `gate_skipped`.

| Task | Checked | Left to the judge |
|---|---|---|
| 01 | c1 build `-warnaserror`; c3 `dotnet test` (+judge) | c2, c4 |
| 02 | c3 pytest (+judge: monkeypatch-free); c4 `mypy --strict` (needs mypy + fastapi) | c1, c2, c5 |
| 03 | c1 `az bicep build` of module and consumer, no warnings | c2–c5 |
| 06 | c1 `actionlint` | c2–c5 |
| 07 | c1 unit tests, c2 integration tests (needs Docker), both +judge | c3 per-file coverage |
| 09 | c1 build `-warnaserror` and `dotnet test` | c2–c5 |
| 10 | c1 `kubectl kustomize` for dev, staging, prod | c3+ (c2 is unverifiable) |
| 04, 05, 08 | — documentation deliverables | all |

### What the first live runs showed

Spikes on CLI 1.0.105 (task-02, task-05), reproduced in the
`copilot-subagent-session.jsonl` fixture, exposed missing tool grants and a skipped plan gate.
The agents now grant `skill`, and `dev-lead` grants `ask_user`. A synthetic SDK probe confirmed
that a delegated worker can invoke a skill and that the trace attributes the call to that
worker. The real-agent gate outcomes above remain failures or unverified evidence; the grants
do not make those runs pass. The unsandboxed coding sub-agent also read outside its workspace,
and a 60-credit cap was hit mid-run — size `--max-ai-credits` per task.

## Interpreting acceptance evidence

See [`../scoring-rubric.md`](../scoring-rubric.md#custom-tasks) for the conceptual rubric:

- **resolved** — all acceptance criteria in `acceptance.md` pass
- **partial** — at least one criterion passes; the rest fail non-catastrophically
- **failed** — no acceptance criterion passes, or the build is broken
- **unverified** — a criterion cannot be checked; no resolved credit, with reasons
- **setup_error** — fixture or judge environment/contract error, not an agent failure
- **awaiting_approval** — the simulated decision is pending; **unverified**
- **blocked_approval** — the approval request could not be verified; **unverified**
- **dry_run** — staged only; not a scored outcome

The scorer combines them: a skipped plan gate or any failing trajectory metric makes the run
**failed** whatever the judge says, as does a plan the simulated approver rejected; a pending
decision is **unverified**. Otherwise the acceptance verdict decides, after command checks
have overridden the judge on the criteria they cover. Exit codes: 0 resolved, 1 failed,
2 partial, 3 unverified, 4 setup error.

Every selected task belongs in the denominator of any outcome report.
Original inputs are comparison evidence, never answers or seeded credit.

### Fixture boundaries

- Task 03 (Bicep) and task 08 (threat model) declare no source baseline because their prompts
  provide the complete inputs.
- Task 04's ADR-0007 is a **synthetic task fixture** about Polly. It is not this repository's
  actual ADR-0007 and does not authorize authoring or superseding an ADR in this source repo.
  The task selects the core skill's **MADR** template, not Nygard or the former custom
  six-section shape. Exactly two working-copy paths may change: add
  `docs/adr/0014-http-resilience-library.md` and update
  `docs/adr/0007-http-resilience-library.md` for bidirectional supersession. The new
  ADR links back in Links; the predecessor's superseded status links forward, preserving
  its historical rationale. The canonical sibling baseline remains unchanged.
- Task 05's four-file `diff.patch` is synthetic context; it is not a PR description.
- Task 07's implementation and PostgreSQL repository are working pre-existing code. No
  requested unit or integration tests or coverage results are seeded. Its input declaration
  lists the seven production/solution files individually, excluding local build output.
  Offline inventory/mutation tests protect those exact inputs.
  The solution contains only the production project, so test and coverage commands allow
  restore/build of newly authored test projects rather than using `--no-build`.
  The offline contract tests execute nothing; only a live run's acceptance checks restore,
  build and run the authored tests, and the integration suite needs Docker.
- Task 10's chart has the six named resources and no `Ingress` resource. Environment-specific
  `ingress.host` values are copied into the application's `PUBLIC_BASE_URL` ConfigMap setting.
  The prompt's equivalence criterion mentioning ingress hosts therefore remains ambiguous for
  a chart with no Ingress object; this fixture note preserves that discrepancy rather than
  inventing an extra Kubernetes resource or changing the acceptance criteria. When the
  literal ingress-host comparison cannot be verified, graders **must use UNVERIFIED with
  this reason**, not infer equivalence from `PUBLIC_BASE_URL` or weaken the AC. Missing
  Helm/kubectl or other native toolchains similarly remain unverified.

## Portability

A downstream fork can:

1. Delete tasks not relevant to their stack (e.g., remove #03 / #10 if no Azure / K8s).
2. Add tasks representative of their domain — declare every pre-existing input in `inputs.json`.
3. Adjust each task's `solution-profile.yaml` to match their real profile (region, compliance
   framework, allowed runtimes).

Adding a task folder registers it with the runner; nothing runs until someone dispatches it.

## Adding a new task — checklist

- [ ] Folder name is `task-NN-<kebab-slug>` with `NN` zero-padded
- [ ] `prompt.md` is 10-30 lines, written as the user would phrase it
- [ ] `acceptance.md` has 3-5 criteria, each verifiable
- [ ] `solution-profile.yaml` supplies required Stage-0 fields and actual per-check commands
- [ ] `inputs.json` declares every required baseline input, or an empty list when none exists
- [ ] `expectations.yaml` names the delegated agents and each one's core skill loads
- [ ] Any measured result records its method and limitations in [`../../baselines.md`](../../baselines.md); fixture presence alone is not a result
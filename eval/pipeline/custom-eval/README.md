# `custom-eval/` — 10 framework-representative evaluation tasks

## What this is

Hand-written tasks chosen to exercise the **breadth** of the dev-lead agent suite and the
typical surface area of a real-world software delivery engagement. Each task is one folder under
`tasks/task-NN-<slug>/` containing a prompt, acceptance contract, operational
profile, and versioned input declaration:

| File | Purpose |
|---|---|
| `prompt.md` | The user-story prompt fed verbatim to `dev-lead` |
| `acceptance.md` | 3-5 explicit, verifiable pass criteria |
| `solution-profile.yaml` | Synthetic profile conforming to the shipped solution-profile contract |
| `inputs.json` | Version-1 explicit source/destination inputs, each with a required flag |
| `expectations.yaml` | Trajectory contract: plan gate, which agents dev-lead delegates to, which skills each one must invoke |
| `baseline/` | Minimal synthetic or task-directed source inputs; never includes the requested answer |

A run has two halves, kept in separate trust zones:

- **Runner** (`../run_custom_eval.py`) stages the baseline into a fresh git workspace, drives
  `dev-lead` to its plan gate, and has an LLM judge the plan before resuming the *same pending
  request*. It records `phase1-changes.json` before acceptance checks, captures `produced.diff`
  against the baseline, and runs the task's declared **checks**, recording `checks.json`.
  Missing or unverified approval evidence blocks the resume.
- **Scorer** (`../score_custom_eval.py`) reads only the recorded JSONL logs, `state.json`,
  `phase1-changes.json`, `plan-approval.json`, `produced.diff` and `checks.json`. Trajectory
  is scored with **DeepEval** (`ToolCorrectnessMetric`); command results decide
  build/test/render criteria; the rest goes to a pluggable judge. The completed final response
  is separate untrusted evidence. The scorer runs no git and no workspace code.

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

## Input staging and isolation

The runner mounts **only `agile-agents-core`**. Each task declares ordinary
version-1 `inputs`; there is no separate resolver or guidance manifest:

```json
{
  "source": "baseline/.github/skills/python-testing/SKILL.md",
  "destination": ".github/skills/python-testing/SKILL.md",
  "required": true
}
```

Sources must be task-local regular files. Symlinks, escaping/duplicate paths and
configuration injection (`.git`, `.copilot`, `.claude`, plugins, agents or an
overwritten task profile) fail setup. Native skill/instruction files are copied
exactly like source inputs; the runner does not resolve capabilities or emulate
`applyTo`. Presence is **not invocation**.

Tasks 01/02/03/06/07/08/09/10 explicitly supply only their named technical
capabilities. Tasks 04/05 need no technical skills. Their minimal, newly authored
references are MIT test data, not copies of retired skills, scripts or resources.
Technical skill-use expectations remain required when staged. No user-owned
package, global skill directory or personal absolute path is a benchmark input.

Live phases isolate HOME, USERPROFILE, COPILOT_HOME and XDG roots, omit ambient
instruction/plugin/model overrides, and require `--sync-session=off` and
`--secret-env-vars`. Missing controls fail
setup. The runner probes the actual CLI, and the Node transport passes these controls to
the SDK's CLI process. Dry runs stage only: they do not query the CLI or validate its flags.
This is configuration isolation, **not an OS sandbox**.

Offline tests cover exact staging, path/configuration rejection, core-only
mounting, environment isolation and required privacy flags. Approval and
per-agent command/skill evidence remain independently scored. These tests are
not evidence of a successful live RPI run.

## The 10 tasks

| # | Slug | Surface |
|---|---|---|
| 01 | `csharp-minimal-api-endpoint`       | C# / ASP.NET Minimal API + xUnit (csharp-implementation, csharp-testing) |
| 02 | `python-di-refactor`                | Python refactor + DI (local python-implementation/python-testing) |
| 03 | `bicep-storage-waf`                 | Bicep + Azure WAF baseline (local bicep-implementation) |
| 04 | `adr-library-tradeoff`              | ADR authoring (architecture-decision-records, engineering-judgement) |
| 05 | `pr-description`                    | PR/release artifacts (dev-lead-templates completion reference) |
| 06 | `gha-oidc-deploy`                   | GitHub Actions + OIDC to Azure (cicd-pipeline-implementation) |
| 07 | `test-coverage-uplift`              | Unit + integration test backfill (local csharp-testing, independent code-reviewer) |
| 08 | `threat-model-api`                  | Architect-authored STRIDE document (local minimal threat-model-analyst reference), independent security review |
| 09 | `polly-resilience`                  | Resilience patterns on HTTP client (cloud-native-patterns, csharp-implementation) |
| 10 | `helm-to-kustomize`                 | K8s migration (local helm-kustomize-implementation) |

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

Needs Node.js and the Copilot CLI on `PATH` (CLI pinned `1.0.105` in CI), a nonempty
`COPILOT_GITHUB_TOKEN` or `GITHUB_TOKEN`, and the hash-locked environment from
[`../../deepeval/README.md`](../../deepeval/README.md). Local runs can keep using
`COPILOT_GITHUB_TOKEN`; Actions supplies `GITHUB_TOKEN` to the two agent phase steps.
`--max-ai-credits` caps each phase (minimum 30). The plan approver always uses Azure OpenAI;
the acceptance judge is selected separately. Azure OpenAI authenticates with Entra only —
`az login` locally, federated `azure/login` in CI; no API key is accepted — and reads
`AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_DEPLOYMENT`. Unset `AZURE_OPENAI_API_KEY`
and `AZURE_OPENAI_AD_TOKEN`, even if empty; ambient credentials are rejected.
The endpoint must be the HTTPS Azure resource URL, not a project or operation URL.
The deployment must support deployment-based Chat Completions (default API version
`2024-10-21`, overridable with `AZURE_OPENAI_API_VERSION`). The judge requests
`temperature=0`; only a specific unsupported-temperature response triggers one retry
with the deployment default and a warning that results may vary. Safe diagnostics report
HTTP status, never SDK response bodies or credentials.

In CI, dispatch **Eval · custom-eval live run** (`.github/workflows/eval-custom.yml`).
GitHub registers manual dispatch once the workflow is on the default branch; select the
branch to evaluate when starting the run:

| Job | Holds | Does |
|---|---|---|
| `plan` | `GITHUB_TOKEN`: `contents: read`, `copilot-requests: write`; no OIDC | phase 1; writes the plan to the step summary (runs checks only if dev-lead skipped the gate) |
| `approve` | OIDC and `contents: read`; no `copilot-requests` | the simulated approver judges the plan and outputs `approved` or `rejected`; runs no agent |
| `implement` | same as `plan` | runs only when `approve` succeeds with an `approved` decision, then resumes and runs the checks |
| `score` | OIDC and `contents: read`; no `copilot-requests` | DeepEval + judge over the recorded files; runs no agent |

The agent jobs install .NET 10 for C# tasks, task-02-only hash-locked Python tools, and
checksum-verified `actionlint` for task 06; `kubectl`, `az` and Docker come with the runner
image. Task 02 layers `requirements-task02.lock.txt` on the evaluation environment and runs
`pip check`; approver/scorer jobs retain the evaluation lock alone. Missing local tools leave
their criteria `UNVERIFIED`. The pinned actionlint 1.7.12 predates `copilot-requests`;
when checking this workflow, suppress only its unknown-scope diagnostic:

```powershell
actionlint -ignore 'unknown permission scope "copilot-requests"\.' .github\workflows\eval-custom.yml
```

Actions uses a short-lived `GITHUB_TOKEN`; no Copilot PAT or `EVAL_COPILOT_TOKEN` secret is
needed. The unsandboxed agent can read this token. Billing and organization policy must allow
[Copilot CLI in Actions](https://docs.github.com/en/copilot/concepts/agent-capabilities/agent-powered-workflows-and-operations/copilot-cli-in-github-actions).
Configure repository variables `EVAL_AZURE_CLIENT_ID`, `EVAL_AZURE_TENANT_ID`,
`EVAL_AZURE_OPENAI_ENDPOINT` and `EVAL_AZURE_OPENAI_DEPLOYMENT`.
The Entra identity needs an OIDC credential whose issuer, audience and exact subject match
the selected branch's token, plus inference access such as `Cognitive Services OpenAI User`
on the resource. Subject formats can be classic, immutable or customized: use the actual
subject reported by `azure/login`, not an assumed template. See
[OIDC setup](https://learn.microsoft.com/azure/developer/github/connect-from-azure-openid-connect).
No approval environment, human reviewer or stored client secret is needed for this eval.

## Simulated plan approval (eval-only)

dev-lead's Stage 4 plan approval is a quality gate, so an unattended run can have it judged
rather than rubber-stamped. The Azure OpenAI judge grades the plan
against [`plan-approval.md`](plan-approval.md) — seven shared criteria (Definition of Done and
scope, decomposition, coverage of the stated acceptance criteria, derived criteria shown
separately, assumptions and risks, no scope expansion, approval asked before execution) plus
any task-specific ones under `plan_approval:` in `expectations.yaml` (needs
`plan_gate: required`). Each criterion is `PASS`, `FAIL` or `UNVERIFIED`; the plan is
**approved only if every criterion passes**. The approver sees the requirement (`prompt.md`),
preceding plan message and exact question/choices, never `acceptance.md`. The question may
contain the plan. Missing evidence is `UNVERIFIED`; oversized plans are rejected without a
model call.

The Node transport uses the pinned CLI's bundled SDK to suspend at the top-level `ask_user`
request and resume that same request after approval. Its internal interface is version-bound.
The decision binds the session, request, tool call, visible plan, requirement and rubric.
A stale or mismatched decision, missing evidence, nonzero transport exit or a different
completed response cannot pass; further unapproved questions block completion.

The gate detects implementing-agent delegation attempts and top-level write tools, plus
persistent committed, staged, unstaged and non-ignored untracked changes against the
baseline, including shell writes. The snapshot excludes generated build/cache directories,
Python bytecode in `__pycache__`, `.copilot-runs/` telemetry and task-profile setup.
A nonempty snapshot fails; a missing/malformed snapshot is unverified and prevents approval
and resume. Reverted, ignored or out-of-workspace changes are not detected, and the
unsandboxed agent can tamper with local evidence. Detection is not a security boundary.

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
missing completion is `UNVERIFIED`, not a pass or an agent failure. Lists hold the
**core contract loads plus explicitly staged consumer capabilities**, not every
skill a good run might touch. A pass means the measured contract was honoured,
not that the run was optimal. `any` supports deliverable skills whose author varies;
it never authorizes a reviewer to write or launch a nested author.
Task-10 lists criterion 2 under `unverifiable` with its reason (see fixture boundaries).

Delegation receives credit when the named agent starts or its task call succeeds.
Failed attempts receive no credit; incomplete attempts are `UNVERIFIED`. An attempted
implementing-agent delegation before approval still violates the gate.

Current acceptance owners:

- The **code-reviewer agent rubric** owns code quality; its delegation and
  read-only skills are required. Reviewer forbidden-workflow checks still apply.
- **dev-lead-templates/references/completion.md** covers
  intent, real test evidence, rollback, migration/breaking changes and publication
  approval. Task acceptance judges the requested PR text.
- `threat-model-analyst` is **task-08-only synthetic author guidance**, not the
  a general toolkit. Attribution belongs to `architect`;
  security-reviewer remains independent. No threat-library coverage is claimed.

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
`{python}` is the verifier's interpreter. For task 02, install
`requirements-task02.lock.txt` with `--require-hashes --only-binary=:all:` into an isolated
evaluation environment, then verify using that interpreter.
The judge can grade a completed final response when it is the requested deliverable, but
its claims are not proof of changes or test results. A pending plan is not a final answer.
Responses over 120,000 characters leave model-judged criteria `UNVERIFIED` without a model
call; command-check overrides still apply.

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

### Runtime limitations

- Delegated skill use requires the native `skill` grant and source-attributed
  execution evidence. Static grants do not prove role-wide invocation or
  automatic scoped-instruction injection.
- Native `ask_user` and transport support do not prove real dev-lead compliance.
  Missing request evidence remains `blocked_approval`; implementation before approval
  is `gate_skipped` and fails scoring.
- The agent is unsandboxed and can read outside its workspace. Set
  `--max-ai-credits` for the task; a cap is not filesystem isolation.

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
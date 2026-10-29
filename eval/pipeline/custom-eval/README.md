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
| `inputs.json` | Versioned list of required baseline inputs and their workspace destinations |
| `expectations.yaml` | Trajectory contract: plan gate, which agents dev-lead delegates to, which skills each one must invoke |
| `baseline/` | Minimal synthetic or task-directed source inputs; never includes the requested answer |

A run has two halves, kept in separate trust zones:

- **Runner** (`../run_custom_eval.py`) stages the baseline into a fresh git workspace, drives
  `dev-lead` through the Copilot CLI up to its plan gate, waits for a human approval, resumes
  the *same* session, and captures `produced.diff` against the staged baseline.
- **Scorer** (`../score_custom_eval.py`) reads only the recorded JSONL logs, `state.json` and
  `produced.diff`. Trajectory is scored with **DeepEval** (`ToolCorrectnessMetric`); acceptance
  goes to a pluggable judge. It runs no git and no workspace code, so it can hold judge
  credentials safely.

The live agent is **not OS-sandboxed** — it runs with every tool allowed on the host, which
is why the runner refuses to start without `--unsandboxed`. A sandboxed worker is
[#22](https://github.com/hoffe86/agile-agents/issues/22); until then behavioural criteria
(builds, tests, lint) are `UNVERIFIED` by design, never judged from source.

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
# Local: phase 1 stops at the plan gate and prints dev-lead's plan; approve interactively.
python eval/pipeline/run_custom_eval.py task-05 --out $env:TEMP\ce\task-05 --unsandboxed
python eval/pipeline/run_custom_eval.py task-05 --out $env:TEMP\ce\dry --dry-run   # stage only
# Score one or more runs. --judge none leaves every acceptance criterion UNVERIFIED.
python eval/pipeline/score_custom_eval.py $env:TEMP\ce\task-05 --judge azure-openai --output summary.json
```

Needs the Copilot CLI on `PATH` (pinned `1.0.105` in CI), `COPILOT_GITHUB_TOKEN`, and the
hash-locked environment from [`../../deepeval/README.md`](../../deepeval/README.md).
`--max-ai-credits` caps each phase (minimum 30). The `azure-openai` judge authenticates with
Entra only — `az login` locally, federated `azure/login` in CI; no API key is accepted — and
reads `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_DEPLOYMENT`.

In CI, run **Eval · custom-eval live run** (`.github/workflows/eval-custom.yml`) by hand:

| Job | Holds | Does |
|---|---|---|
| `plan` | Copilot token, read-only `GITHUB_TOKEN` | phase 1; writes the plan to the step summary |
| `implement` | same | waits on the **`eval-approval`** environment — its required reviewers *are* the plan gate — then resumes with `--approve` |
| `score` | OIDC (`id-token: write`) for the judge only | DeepEval + judge over the recorded files |

Repository setup: secret `EVAL_COPILOT_TOKEN` (a dedicated, low-privilege account — the
unsandboxed agent can read its own environment), environment `eval-approval` with required
reviewers, and for the Azure judge the variables `EVAL_AZURE_CLIENT_ID`,
`EVAL_AZURE_TENANT_ID`, `EVAL_AZURE_OPENAI_ENDPOINT`, `EVAL_AZURE_OPENAI_DEPLOYMENT`.

## Trajectory expectations

`expectations.yaml` says what a correct *process* looks like, independent of the output:

```yaml
schema: 1
root_agent: dev-lead
plan_gate: required            # phase 1 must not delegate to an implementing agent
agents: [coding, review-lead, code-reviewer]   # every one must be delegated to
skills:                        # per agent: each must be invoked by that agent
  coding: [read-repo-context, development-practices, python-implementation]
  any: [architecture-decision-records]          # invoked by anyone in the run
forbidden_skills:
  review-lead: [code-review-checklist]          # the orchestrator performs no lens
```

Each agent's skill list scores as its own DeepEval metric (`skills:<agent>`), so a miss is
attributed to the agent that should have loaded the skill. Lists hold the **core contract
loads** an agent's own definition makes mandatory — not every skill a good run might touch —
so a pass means the contract was honoured, not that the run was optimal. `any` exists for
deliverable skills whose author varies (an ADR may be drafted by dev-lead or a reviewer).
Task-10 lists criterion 2 under `unverifiable` with its reason (see fixture boundaries).

### What the first live runs showed

Spikes on CLI 1.0.105 (task-02, task-05), reproduced in the
`copilot-subagent-session.jsonl` fixture:

- **Sub-agents cannot invoke skills.** The `skill` tool is not offered inside a delegated
  agent, so `coding` made zero skill calls: `skills:coding` scores **0.0** and the run fails.
  This is the harness's most important open finding, and exactly what per-agent skill
  scoring exists to catch.
- **The plan gate is skipped in prompt mode.** Under `-p`, dev-lead implemented without
  waiting; the runner records `gate_skipped` and the run scores failed. An interactive
  approval path over ACP (`copilot --acp`) is the candidate fix.
- The unsandboxed coding sub-agent read outside its workspace, and a 60-credit cap was hit
  mid-run — size `--max-ai-credits` per task.

## Interpreting acceptance evidence

See [`../scoring-rubric.md`](../scoring-rubric.md#custom-tasks) for the conceptual rubric:

- **resolved** — all acceptance criteria in `acceptance.md` pass
- **partial** — at least one criterion passes; the rest fail non-catastrophically
- **failed** — no acceptance criterion passes, or the build is broken
- **unverified** — a criterion cannot be checked; no resolved credit, with reasons
- **setup_error** — fixture or judge environment/contract error, not an agent failure
- **blocked_approval** / **skipped** — mandatory human gate / dry run, not outcomes

The scorer combines them: a skipped plan gate or any failing trajectory metric makes the run
**failed** whatever the judge says; a pending or refused approval is **unverified**; otherwise
the judge's verdict decides. Exit codes: 0 resolved, 1 failed, 2 partial, 3 unverified,
4 setup error.

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
  This command correction does not establish runtime readiness: no generated code,
  Testcontainers database, restore, or test command is executed by these contract checks.
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
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
| `baseline/` | Minimal synthetic or task-directed source inputs; never includes the requested answer |

These are retained **benchmark data**, not a runnable suite. No workspace stager,
agent runner or acceptance scorer is supplied. Source-consistency tests inspect
the fixtures without executing their declared commands. Live execution and its
sandbox boundary are deferred to
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

## Interpreting acceptance evidence

See [`../scoring-rubric.md`](../scoring-rubric.md#custom-tasks) for the conceptual rubric:

- **resolved** — all acceptance criteria in `acceptance.md` pass
- **partial** — at least one criterion passes; the rest fail non-catastrophically
- **failed** — no acceptance criterion passes, or the build is broken
- **unverified** — a criterion cannot be checked; no resolved credit, with reasons
- **setup_error** — fixture or judge environment/contract error, not an agent failure
- **blocked_approval** / **skipped** — mandatory human gate / dry run, not outcomes

Every selected task belongs in the denominator of any future outcome report.
Original inputs are comparison evidence, never answers or seeded credit.
Narrative deliverables can be reviewed manually against the criteria. The active
[DeepEval scorer](../../deepeval/README.md) measures recorded skill invocation;
it does not establish these acceptance outcomes.

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

Task folders are data; adding one does not register or execute a benchmark.

## Adding a new task — checklist

- [ ] Folder name is `task-NN-<kebab-slug>` with `NN` zero-padded
- [ ] `prompt.md` is 10-30 lines, written as the user would phrase it
- [ ] `acceptance.md` has 3-5 criteria, each verifiable
- [ ] `solution-profile.yaml` supplies required Stage-0 fields and actual per-check commands
- [ ] `inputs.json` declares every required baseline input, or an empty list when none exists
- [ ] Any measured result records its method and limitations in [`../../baselines.md`](../../baselines.md); fixture presence alone is not a result
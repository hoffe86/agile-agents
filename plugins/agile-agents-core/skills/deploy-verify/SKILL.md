---
name: deploy-verify
description: >-
  Opt-in deployed verification — push the feature branch, let the project's own CI/CD pipeline deploy pipeline + IaC + application to the first non-production environment, and report whether it actually deployed. Proves the things `plan` / `what-if` structurally cannot: quota, policy denial, name collisions, RBAC at apply time, unregistered providers, non-idempotent IaC. Gated on `solution-profile.yaml: infrastructure.deploy_verify` (default `off`) and never touches production. Loaded by `dev-lead` at Stage 8 after the test bar passes.
applies_to: all
---

# Deploy-Verify

`terraform plan` succeeding and `terraform apply` succeeding are different claims. This skill makes the second one, in the cheapest honest way: it does not deploy anything itself — it pushes the branch and lets **the project's own pipeline** do the deploying, then reads the result.

That indirection is the whole design. Using the real pipeline means the run also verifies the pipeline: its OIDC federation, its environment gates, its service connections, its variable groups, its stage ordering. An agent shelling out to `az deployment create` would prove the IaC and prove nothing about the path the change actually ships through.

## What plan / what-if cannot catch

The justification for spending the time and the cloud money:

| Failure mode | Caught by plan / what-if? |
|---|---|
| Quota or regional capacity exhausted | ❌ |
| Azure Policy / Deny assignment refuses the resource | ❌ what-if does not evaluate policy |
| Name collision, or a soft-delete tombstone (Key Vault, Cosmos, API Management) | ❌ |
| Deploy identity lacks a role only needed at apply time | ❌ |
| Resource provider not registered on the subscription | ❌ |
| IaC is not idempotent — a second apply still shows changes | ❌ |
| Module outputs resolve to something the next module can consume | ❌ |
| Application actually starts on the deployed infrastructure | ❌ |

**Run the cheap check first.** Everything above is what plan / what-if *cannot* see — but the things they *can* see should be caught before spending a deployment on them. On Bicep, **`azure-deployment-preflight`** (shipped by `agile-agents-bicep`) covers template syntax, what-if and the permission check in one pass; on Terraform, `plan` plus `terraform validate` is the equivalent. A run that fails preflight has no business reaching this gate, and the failure is free instead of costing a pipeline run and real cloud time.

## When this skill fires

At **Stage 8**, immediately after the test bar returns green, and only when **all** preconditions hold. Any precondition unmet → emit a `skipped` event with the specific reason and pass through. Never block a run because deployed verification was unavailable — it is an enhancement to the gate, not a new mandatory gate.

Preconditions:

1. `infrastructure.deploy_verify` is `dev`. Default is `off` → skip, no warning. Most repos have no non-prod environment wired for this and that is a normal state.
2. `infrastructure.environment_chain` is non-empty. The target is `environment_chain[0]`. If that entry's name contains `prod`, **halt and ask the user** — a chain whose first entry is production is a misconfiguration, and guessing is not safe.
3. `cicd.platform` is set and the pipeline definitions in `cicd.pipeline_paths` exist.
4. The diff actually touches something deployable — IaC, application source, or a pipeline definition. A docs-only or test-only diff skips with `reason=nothing_deployable`.
5. The branch is a feature branch, not the default branch.

## Branching strategy determines reachability

Read `cicd.release_strategy` **before** pushing. It decides whether a feature-branch push can trigger a dev deployment at all:

| `release_strategy` | Does pushing the feature branch deploy to dev? |
|---|---|
| `trunk` | Usually yes — feature branches commonly run the full pipeline including a dev deploy. Proceed. |
| `gitflow` | Usually no — dev deploys come from `develop`. Proceed only if a pipeline trigger in `cicd.pipeline_paths` matches this branch. |
| `release-branches` / `env-branches` | Usually no — the environment is driven by its own branch. Same check as gitflow. |
| empty / unknown | Inspect the pipeline triggers and decide from those. |

If the strategy or the triggers say this branch will not reach a dev deploy, emit `skipped, reason=branch_not_deployable` and say so plainly in the report. **Do not** "fix" it by pushing to `develop`, retargeting the pipeline, or adding a trigger — that is a change to the project's release process, far outside the mandate of a verification step.

## Procedure

1. **Confirm the target.** Resolve `environment_chain[0]`. Re-assert it is not production. This is the one check worth doing twice.
2. **Push the branch.** Commit any uncommitted work on the feature branch first; push. Never force-push, never push to the default branch. This needs no approval — committing and pushing are ungated — and it authorises nothing beyond itself: this skill opens no PR.
3. **Find the run.** Locate the pipeline run triggered by that head SHA. If no run appears within ~2 minutes, emit `skipped, reason=no_pipeline_run` — the triggers did not match, which is information, not a failure.
4. **Poll to completion**, bounded by `cost_envelope.max_minutes_per_run` (whatever remains of it). On timeout: `failure, reason=timeout`, and report the run URL so a human can pick it up.
5. **Read the outcome.** On failure, extract the failing stage/job name and the error tail. A pipeline URL alone is not a report.
6. **Assert convergence** — the strong check, and the reason this skill is worth more than "the pipeline went green". Re-run `terraform plan` / `az deployment group what-if` against the deployed environment. **An empty diff is the pass condition.** A non-empty diff after a successful apply means the IaC is not idempotent — it will drift on every subsequent run. Report that as a failure even though the pipeline reported success.
7. **Application liveness**, when the pipeline does not already assert it: one request to the deployed health endpoint. Same shape as the smoke slot in `test-bar-gate`, pointed at the deployed URL rather than localhost.
8. **Post-deploy telemetry**, when the Azure MCP tools are available (`azure-mcp/*` — from Microsoft's [`azure-skills`](https://github.com/microsoft/azure-skills) plugin) and the workload has App Insights or Log Analytics wired: query the exception and failed-request counts for the few minutes since the deploy. A deployment that succeeds and then throws on first request is the failure mode a status check is blindest to. Tools absent → skip this step and say so; never treat missing telemetry as a pass *or* a failure.

## Teardown

There is none, deliberately. This deploys to a **long-lived dev environment the project already owns and already pays for**, so there is nothing to clean up — the next run overwrites the same resources. Ephemeral per-run resource groups were considered and rejected: they add quota pressure, cold-start latency, and a teardown path that must survive the agent crashing.

The consequence to be honest about: **concurrent runs against the same dev environment will fight.** Two agents deploying different branches to one environment produce results neither can trust. Until this is used at that concurrency it is not worth solving; when it is, the fix is a lock on the environment, not per-run infrastructure.

## Cost

`cost_envelope` models tokens and wall-clock. It does not and should not model Azure spend — a token budget cannot see a resource left running. Put an **Azure Budget with an alert on the dev subscription**; that is the platform's job and it already does it well. This skill's only cost obligation is honouring the remaining `max_minutes_per_run` when polling.

## Failure attribution

Feeds the same corrective loop as the test bar — one retry, then halt and ask.

| Failing stage | Author to re-engage |
|---|---|
| IaC deployment (Bicep/Terraform apply) | `infrastructure` |
| Non-empty diff on the convergence re-plan | `infrastructure` |
| Application build or deploy step | `coding` |
| Application health check after a successful deploy | `coding` |
| Exceptions / failed requests in post-deploy telemetry | `coding` — the deploy worked, the app does not |
| Pipeline definition itself (syntax, auth, missing variable) | `infrastructure` |
| Quota, policy denial, missing role assignment | **halt — ask the user.** These need a subscription owner, not another agent round. |

That last row matters: an agent cannot raise a quota or grant itself a role, and retrying will burn the envelope on a deterministic failure.

## Event log

Emit to the run event log (`run-event-log`):

```json
{ "event_type": "deploy_verify", "outcome": "success", "environment": "dev", "run_url": "https://…", "duration_s": 412, "convergence": "empty" }
{ "event_type": "deploy_verify", "outcome": "skipped", "reason": "not_configured" }
{ "event_type": "deploy_verify", "outcome": "failure", "environment": "dev", "run_url": "https://…", "failed_stage": "deploy-infra", "error_tail": "…" }
```

## Hard rules

- **Never production.** Not the last entry of `environment_chain`, not any entry whose name contains `prod`, regardless of configuration.
- **Never merge, never force-push, never rewrite shared history.** Pushing the feature branch is the entire write footprint.
- **Never modify pipeline triggers to make a deploy happen.** If the branch does not reach the environment, report that.
- **Skip loudly, fail loudly, never silently pass.** A skipped verification must appear in the hand-off — a run that reports "verified" when it only ran `plan` is worse than one that never tried.

---
name: iac-best-practices
description: Cross-cutting Infrastructure-as-Code best practices that apply regardless of tool (Bicep, Terraform, Helm, Kustomize, ARM, Pulumi) or cloud. Covers naming conventions, tagging, module composition, state/secret handling, idempotency, environment promotion, drift management, and well-architected alignment. USE FOR any IaC request to enforce or audit general best practices, or to decide on naming/tagging/structure. Platform-specific conventions and control ids come from that platform's own skill.
metadata:
  applies_to: all
---

# IaC Best Practices (cross-cutting)

This skill is **technology-agnostic**. Concrete IaC, container and pipeline guidance
comes from applicable native instructions, local skills and installed external
plugins selected by descriptions/capabilities via `read-repo-context`.

## 1. Naming

`infrastructure.naming_convention` takes precedence, followed by existing repo conventions
and the target provider's published naming guidance (including per-service constraints).
Do not impose another provider's abbreviations, environment labels or region codes.

Select provider guidance only with both actual availability and applicability.
Multi-cloud/hybrid targets require evidence of the affected resource subset;
document that scope and apply guidance only there. Tool syntax or a state backend
does not identify the resource provider. Clarify missing/conflicting declarations.
Without matching guidance, use repo/provider conventions and authoritative docs;
report that fallback in the hand-off. No provider naming default is supplied here.

## 2. Tagging — enforce the solution's declared policy

Required keys and supported resource types come from the solution. Check coverage
of these purposes, but do not invent mandatory key names or contact values:

| Illustrative key | Example | Purpose |
|---|---|---|
| `environment` | `prod` | Routing/cost split |
| `workload` | `payments-api` | Cost center per app |
| `costCenter` | `CC-12345` | Finance allocation |
| `owner` | `team-payments@company.com` | Operational contact |
| `managedBy` | `bicep` / `terraform` / `manual` | Change-management origin |
| `dataClassification` | `confidential` | Compliance triage |

Optional but recommended: `gitRepo`, `gitCommit` (for traceability of what deployed what).

Implement tag inheritance from the platform's parent scope where supported; otherwise pass a `tags` parameter/variable through every module. An Azure resource group (RG) is one such scope, not a universal requirement.

## 3. Module composition

- **Modules have a single, clear purpose.** A module that provisions "everything for service X" is fine; a module that provisions "all infra for the company" is not.
- **Inputs are explicit and validated.** Every input has a description, type, and validation rule (allowed values, length, regex). No undocumented inputs.
- **Outputs surface only what callers need.** Resource IDs, FQDNs, principal IDs. Don't dump the entire resource object.
- **Versioning:** modules pinned to specific versions (`v1.2.3` or commit SHA). Never `latest` / `main`.
- **Prefer official/verified modules** from the registry `infrastructure.module_source` names, before authoring your own. Forking a verified module for one tweak is usually wrong — file an issue or contribute upstream.

## 4. Secret handling

- **No secrets in source.** Not in `.bicepparam`, not in `terraform.tfvars`, not in `values.yaml`, not in environment YAML files.
- **Reference, don't embed.** Use the declared platform's secrets store and supported reference/injection mechanism; verify secrets do not leak through state, logs or outputs.
- **Rotate by reference change** — your IaC should never need a re-deploy to rotate a secret.
- **Pipeline secrets** scoped to environments with required reviewers; never store as repo-level secrets if they grant prod access.

## 5. State & idempotency

- **Idempotent by construction.** Running the same template twice must produce the same result. No hidden timestamps, no random names without a stable seed, no `local-exec` that mutates external state.
- **Shared state** requires protected storage, locking and access controls appropriate to the declared tool. Preserve the selected backend; do not infer it from the resource provider.
- **State is canonical.** Don't edit state files manually. Use the IaC tool's supported state/import operations for the declared provider.
- **Some tools keep no state file** — the platform's own resource manager is the state (Bicep/ARM). There is still a preview command (`what-if`) that is the equivalent of `plan`, and you must run it before every deploy.

## 6. Environment promotion

- **Same code, different parameters.** Environments deploy the same versioned definition; differences live in the solution's parameter or overlay mechanism.
- **Promote by branch or by tag**, not by editing files between environments. A successful `dev` deploy of commit `abc123` is the artifact that gets promoted to `test`, then `stg`, then `prod`.
- **Manual approval gate before prod**, always. Even fully-automated pipelines should pause for a human ack.

## 7. Drift management

- **Detect** drift on a schedule using the tool/provider's preview: for example, `terraform plan` with no apply; for Azure Bicep/ARM only, `az deployment sub what-if` against the last-known parameter file. Surface non-empty diffs as alerts.
- **Reconcile** drift through the IaC tool, not by hand-editing in the Portal. If a hotfix was applied in the Portal during an incident, capture it in IaC the same week.
- **Forbid console/portal mutations** of IaC-managed resources through the platform's policy engine where possible (or at least via documented team agreement).

## 8. Well-architected alignment

Before declaring an architecture "done," walk it through the five pillars every major cloud publishes a framework against — and which apply just as well on-prem:

1. **Reliability** — redundancy across zones (and regions for tier-1), defined RTO/RPO, backup strategy *and a rehearsed restore*, health probes, retry-with-backoff in clients.
2. **Security** — workload identity over secrets, no public endpoints by default, private connectivity, customer-managed keys for sensitive stores, role-based access over shared keys and connection strings.
3. **Cost optimisation** — right-sized instances, autoscaling, committed-use / reserved pricing for steady-state, cheaper tiers or scheduled shutdown for non-production, lifecycle policies on storage.
4. **Operational excellence** — IaC for everything, CI/CD with rollback, structured logging into a queryable store, alerts on the SLIs that back the SLO, runbooks for the top failure modes.
5. **Performance efficiency** — load-tested before production, caching where the access pattern justifies it, async patterns end-to-end.

For pillar depth, service guidance and assessment tooling, select available
capabilities applicable to `infrastructure.cloud` and the affected resource scope.
Without a match use repo/provider docs and disclose the fallback. Never assess
against a platform the solution does not target.

## 9. Pre-deploy gates (run all of these)

| Gate | Tool |
|---|---|
| Syntax + linter | Solution-declared validation commands |
| Plan / what-if | Solution-declared non-mutating preview |
| Security | The scanner and policy the solution already uses |
| Compliance | The platform's posture/compliance scanner, when the project has one |
| Cost | The platform's pricing tooling, when installed |
| Quotas / region | The platform's quota tooling — a design that exceeds a regional quota fails at deploy |
| Access control | Review role assignments for least privilege before applying |

Unavailable required gates are unverified configuration gaps, not passes. Report
missing tooling and prerequisites; optional or explicitly disabled gates are
visible skips. Do not invent a toolchain or install one without approval.

## 10. Post-deploy verification

- **Smoke test** against the deployed endpoint (`curl /health`).
- **Confirm topology matches intent** — read back the deployed resources, whether through the platform's MCP tooling, CLI, or a visualiser skill.
- **Check diagnostics on day one** for alert noise and for errors the deployment introduced.

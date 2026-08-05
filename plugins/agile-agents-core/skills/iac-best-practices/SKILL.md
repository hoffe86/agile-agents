---
name: iac-best-practices
description: Cross-cutting Infrastructure-as-Code best practices that apply regardless of tool (Bicep, Terraform, Helm, Kustomize, ARM, Pulumi) or cloud. Covers naming conventions, tagging, module composition, state/secret handling, idempotency, environment promotion, drift management, and well-architected alignment. USE FOR any IaC request to enforce or audit general best practices, or to decide on naming/tagging/structure. Platform-specific conventions and control ids come from that platform's own skill.
applies_to: all
---

# IaC Best Practices (cross-cutting)

This skill is **technology-agnostic**. It encodes the rules that the language-specific skills (`bicep-implementation`, `terraform-azure-implementation`, `helm-kustomize-implementation`, `cicd-pipeline-implementation`) all defer to.

## 1. Naming

Use the **Microsoft Cloud Adoption Framework abbreviations** + this pattern:

```
<resource-type-abbrev>-<workload>-<env>-<region-abbrev>[-<instance>]
```

- Examples: `rg-payments-prod-weu`, `kv-payments-prod-weu`, `stpaymentsprodweu` (storage: no hyphens, ≤ 24 chars, lowercase).
- `<env>` ∈ `{dev, test, stg, prod}` (use `stg`, not `staging`).
- `<region-abbrev>`: `weu` (West Europe), `neu` (North Europe), `eus` (East US), etc.
- Globally-unique resources: append a 4-char hash from `uniqueString()` / `random_id` to avoid collisions.

The abbreviations and per-service name rules are platform-specific — take them from the target platform's conventions skill when installed (`azure-platform-conventions` on Azure), otherwise from that provider's published naming guidance. `infrastructure.naming_convention` overrides all of it.

## 2. Tagging — required tags on every resource

| Tag | Example | Purpose |
|---|---|---|
| `environment` | `prod` | Routing/cost split |
| `workload` | `payments-api` | Cost center per app |
| `costCenter` | `CC-12345` | Finance allocation |
| `owner` | `team-payments@company.com` | Operational contact |
| `managedBy` | `bicep` / `terraform` / `manual` | Change-management origin |
| `dataClassification` | `confidential` | Compliance triage |

Optional but recommended: `gitRepo`, `gitCommit` (for traceability of what deployed what).

Implement tag inheritance from RG to children where the platform supports it; otherwise pass a `tags` parameter/variable through every module.

## 3. Module composition

- **Modules have a single, clear purpose.** A module that provisions "everything for service X" is fine; a module that provisions "all infra for the company" is not.
- **Inputs are explicit and validated.** Every input has a description, type, and validation rule (allowed values, length, regex). No undocumented inputs.
- **Outputs surface only what callers need.** Resource IDs, FQDNs, principal IDs. Don't dump the entire resource object.
- **Versioning:** modules pinned to specific versions (`v1.2.3` or commit SHA). Never `latest` / `main`.
- **Prefer official/verified modules** from the registry `infrastructure.module_source` names, before authoring your own. Forking a verified module for one tweak is usually wrong — file an issue or contribute upstream.

## 4. Secret handling

- **No secrets in source.** Not in `.bicepparam`, not in `terraform.tfvars`, not in `values.yaml`, not in environment YAML files.
- **Reference, don't embed.** Use Key Vault references (`@Microsoft.KeyVault(...)` for App Settings, `azurerm_key_vault_secret` data source, Secrets Store CSI Driver in K8s).
- **Rotate by reference change** — your IaC should never need a re-deploy to rotate a secret.
- **Pipeline secrets** scoped to environments with required reviewers; never store as repo-level secrets if they grant prod access.

## 5. State & idempotency

- **Idempotent by construction.** Running the same template twice must produce the same result. No hidden timestamps, no random names without a stable seed, no `local-exec` that mutates external state.
- **Remote state** mandatory for any non-trivial Terraform deployment. Backend in azurerm with state locking (blob lease).
- **State is canonical.** Don't edit state files manually. Use `terraform state` subcommands or `az resource` imports.
- **Some tools keep no state file** — the platform's own resource manager is the state (Bicep/ARM). There is still a preview command (`what-if`) that is the equivalent of `plan`, and you must run it before every deploy.

## 6. Environment promotion

- **Same code, different parameters.** `dev`, `test`, `stg`, `prod` deploy from the same Bicep/Terraform; differences live in parameter files / tfvars / overlay values.
- **Promote by branch or by tag**, not by editing files between environments. A successful `dev` deploy of commit `abc123` is the artifact that gets promoted to `test`, then `stg`, then `prod`.
- **Manual approval gate before prod**, always. Even fully-automated pipelines should pause for a human ack.

## 7. Drift management

- **Detect** drift on a schedule: `terraform plan` weekly with no apply; `az deployment sub what-if` against the last-known parameter file. Surface non-empty diffs as alerts.
- **Reconcile** drift through the IaC tool, not by hand-editing in the Portal. If a hotfix was applied in the Portal during an incident, capture it in IaC the same week.
- **Forbid console/portal mutations** of IaC-managed resources through the platform's policy engine where possible (or at least via documented team agreement).

## 8. Well-architected alignment

Before declaring an architecture "done," walk it through the five pillars every major cloud publishes a framework against — and which apply just as well on-prem:

1. **Reliability** — redundancy across zones (and regions for tier-1), defined RTO/RPO, backup strategy *and a rehearsed restore*, health probes, retry-with-backoff in clients.
2. **Security** — workload identity over secrets, no public endpoints by default, private connectivity, customer-managed keys for sensitive stores, role-based access over shared keys and connection strings.
3. **Cost optimisation** — right-sized instances, autoscaling, committed-use / reserved pricing for steady-state, cheaper tiers or scheduled shutdown for non-production, lifecycle policies on storage.
4. **Operational excellence** — IaC for everything, CI/CD with rollback, structured logging into a queryable store, alerts on the SLIs that back the SLO, runbooks for the top failure modes.
5. **Performance efficiency** — load-tested before production, caching where the access pattern justifies it, async patterns end-to-end.

For pillar deep-dives, service-specific guidance, and assessment tooling, load the target platform's well-architected skill when installed (`azure-well-architected` on Azure) — it also supplies the security-benchmark control ids reviewers cite. `solution-profile.yaml: infrastructure.cloud` says which platform's framework is the relevant one; do not assess against a framework the project does not target.

## 9. Pre-deploy gates (run all of these)

| Gate | Tool |
|---|---|
| Syntax + linter | The IaC tool's own — `bicep build/lint`, `terraform fmt/validate`, `helm lint`, `kustomize build` |
| Plan / what-if | The IaC tool's preview command — `terraform plan`, `az deployment ... what-if` |
| Security | `tfsec`, `checkov`, `kube-linter`, or the scanner the repo already runs |
| Compliance | The platform's posture/compliance scanner, when the project has one |
| Cost | The platform's pricing tooling, when installed |
| Quotas / region | The platform's quota tooling — a design that exceeds a regional quota fails at deploy |
| Access control | Review role assignments for least privilege before applying |

Gates whose tooling is not installed are skipped explicitly, not silently — say which ones in the hand-off.

## 10. Post-deploy verification

- **Smoke test** against the deployed endpoint (`curl /health`).
- **Confirm topology matches intent** — read back the deployed resources, whether through the platform's MCP tooling, CLI, or a visualiser skill.
- **Check diagnostics on day one** for alert noise and for errors the deployment introduced.

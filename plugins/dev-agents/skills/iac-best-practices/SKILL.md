---
name: iac-best-practices
description: Cross-cutting Infrastructure-as-Code best practices that apply regardless of tool (Bicep, Terraform, Helm, Kustomize, ARM, Pulumi). Covers naming conventions, tagging, module composition, state/secret handling, idempotency, environment promotion, drift management, and Well-Architected Framework alignment. USE FOR any IaC request to enforce or audit general best practices, decide on naming/tagging/structure, or align a design with the Azure Well-Architected Framework.
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

Reference the [CAF abbreviations table](https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/ready/azure-best-practices/resource-abbreviations).

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
- **Prefer official modules** (Azure Verified Modules in both Bicep and Terraform flavors) before authoring your own. Forking an AVM module for one tweak is usually wrong — file an issue or contribute upstream.

## 4. Secret handling

- **No secrets in source.** Not in `.bicepparam`, not in `terraform.tfvars`, not in `values.yaml`, not in environment YAML files.
- **Reference, don't embed.** Use Key Vault references (`@Microsoft.KeyVault(...)` for App Settings, `azurerm_key_vault_secret` data source, Secrets Store CSI Driver in K8s).
- **Rotate by reference change** — your IaC should never need a re-deploy to rotate a secret.
- **Pipeline secrets** scoped to environments with required reviewers; never store as repo-level secrets if they grant prod access.

## 5. State & idempotency

- **Idempotent by construction.** Running the same template twice must produce the same result. No hidden timestamps, no random names without a stable seed, no `local-exec` that mutates external state.
- **Remote state** mandatory for any non-trivial Terraform deployment. Backend in azurerm with state locking (blob lease).
- **State is canonical.** Don't edit state files manually. Use `terraform state` subcommands or `az resource` imports.
- **Bicep "state" lives in Azure Resource Manager** itself — but `what-if` is the equivalent of `plan` and you must run it before every deploy.

## 6. Environment promotion

- **Same code, different parameters.** `dev`, `test`, `stg`, `prod` deploy from the same Bicep/Terraform; differences live in parameter files / tfvars / overlay values.
- **Promote by branch or by tag**, not by editing files between environments. A successful `dev` deploy of commit `abc123` is the artifact that gets promoted to `test`, then `stg`, then `prod`.
- **Manual approval gate before prod**, always. Even fully-automated pipelines should pause for a human ack.

## 7. Drift management

- **Detect** drift on a schedule: `terraform plan` weekly with no apply; `az deployment sub what-if` against the last-known parameter file. Surface non-empty diffs as alerts.
- **Reconcile** drift through the IaC tool, not by hand-editing in the Portal. If a hotfix was applied in the Portal during an incident, capture it in IaC the same week.
- **Forbid Portal mutations** of IaC-managed resources via Azure Policy where possible (or at least via documented team agreement).

## 8. Well-Architected Framework alignment

Before declaring an architecture "done," walk it through the five WAF pillars:

1. **Reliability** — redundancy across zones (and regions for tier-1), defined RTO/RPO, backup strategy, health probes, retry-with-backoff in clients.
2. **Security** — managed identities, no public endpoints by default, private endpoints + private DNS, customer-managed keys for sensitive stores, RBAC over keys/connection-strings.
3. **Cost optimization** — right-sized SKUs, autoscaling, reserved instances for steady-state workloads, dev/test plans for non-prod, lifecycle policies on storage.
4. **Operational excellence** — IaC for everything, CI/CD with rollback, structured logging into Log Analytics, alerts on the right SLIs, runbooks for top 5 failure modes.
5. **Performance efficiency** — load-tested before prod (`azure-loadtesting` MCP tool), caching layer where appropriate, async patterns end-to-end.

Use the **`azure-wellarchitectedframework`** MCP tool to pull the official assessment for a specific scenario. The canonical reference is the **[Azure Well-Architected Framework on Microsoft Learn](https://learn.microsoft.com/en-us/azure/well-architected/)** — consult it for pillar deep-dives, service-specific guides, and the WAF assessment tool.

## 9. Pre-deploy gates (run all of these)

| Gate | Tool |
|---|---|
| Syntax + linter | `bicep build/lint`, `terraform fmt/validate`, `helm lint`, `kustomize build` |
| Plan / what-if | `terraform plan`, `az deployment ... what-if` |
| Security | `tfsec`, `checkov`, PSRule for Bicep, `kube-linter` |
| Compliance | `azure-compliance` skill (azqr) |
| Cost | `azure-pricing` MCP tool |
| Quotas / region | `azure-quotas` MCP tool |
| RBAC | `azure-rbac` skill |

## 10. Post-deploy verification

- **Smoke test** against the deployed endpoint (`curl /health`).
- **Resource visualizer** (`azure-resource-visualizer` skill) to confirm topology matches intent.
- **Diagnostics** (`azure-diagnostics` skill / AppLens) on day-1 for any alert noise.

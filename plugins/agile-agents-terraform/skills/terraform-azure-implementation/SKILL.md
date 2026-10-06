---
name: terraform-azure-implementation
description: Implement Azure-targeted Terraform (azurerm + AzAPI providers), preferring Azure Verified Modules (AVM) and HashiCorp + Microsoft style guides. USE FOR writing, modifying or migrating Terraform for a declared Azure target, with this capability installed. DO NOT USE for generic `.tf` files or non-Azure Terraform; Terraform syntax alone does not establish Azure applicability.
applies_to: azure, terraform
---

# Terraform (Azure) Implementation

## Applicability — check before using any guidance below

This Azure-only skill requires an **installed** capability and
`infrastructure.cloud: azure`. For a multi-cloud/hybrid declaration, require explicit
repo evidence of an Azure resource subset (for example, the target module's Azure
provider/resources) and document that scope in the hand-off; hybrid alone is not Azure
evidence. Apply this skill only to that subset, never the other providers in the repo.

`.tf`, `.tfvars`, a Terraform request, or an Azure state backend alone does not establish
Azure resource applicability. Missing or conflicting cloud declarations need clarification.
If this gate is not met, do not apply AVM/CAF/Azure tooling: use repo/provider conventions
and the provider's own documentation, reporting the fallback in the hand-off. An unavailable
skill also takes that fallback; no new plugin or dependency is implied.

You are now implementing or modifying Terraform code for the evidenced Azure scope.

## 1. Understand the existing state first

- Read `versions.tf`, `providers.tf`, `main.tf`, `variables.tf`, `outputs.tf`, `terraform.tfvars`, and any `backend.tf`.
- Identify:
  - **Provider versions** (`azurerm`, `azapi`, `random`, `time`) — keep within configured constraints.
  - **Backend** (azurerm remote state, Terraform Cloud, local) — never reconfigure without explicit ask.
  - **Module pattern** (root with inline resources vs. composition of reusable modules).
- Check whether the project uses **AVM for Terraform** (`Azure/avm-res-*/azurerm`).

If the codebase is unfamiliar, invoke **`acquire-codebase-knowledge`** first.
Always pull current best practices via the **`azure-azureterraformbestpractices`** MCP tool **before generating non-trivial code**.

## 2. Compose with these skills and tools

| Concern | Skill / Tool |
|---|---|
| Diff existing Terraform AzureRM resource shapes | `terraform-azurerm-set-diff-analyzer` (vendored) |
| Convert ARM/Bicep to Terraform | `import-infrastructure-as-code` (vendored) |
| Best-practice rules | `azure-azureterraformbestpractices` MCP tool |
| Pre-deploy compliance scan | `azure-compliance` skill (azqr) |
| Architectural review | `azure-wellarchitectedframework` MCP tool |
| Cost estimation | `azure-pricing` MCP tool |
| Quota / region availability | `azure-quotas` MCP tool |

## 3. Default conventions

- **AVM first.** Use `module "x" { source = "Azure/avm-res-<rp>-<resource>/azurerm"  version = "..." }` before authoring raw resources. Pin exact versions, never use `>=` alone.
- **File layout** (per module):
  - `main.tf` — resources
  - `variables.tf` — inputs (with `description`, `type`, `validation`, sensible defaults only when truly safe)
  - `outputs.tf` — outputs (mark `sensitive = true` for secrets)
  - `versions.tf` — `terraform { required_version, required_providers }`
  - `providers.tf` — provider config (root module only)
  - `locals.tf` — derived values
- **Naming:** snake_case for HCL identifiers; resource names follow CAF abbreviations (`rg-`, `vnet-`, `kv-`, `st`, etc.).
- **Tags:** `var.tags` merged into every resource via `merge(var.tags, { ... })`. Use the **canonical camelCase tag keys** (same across Bicep / Terraform / Helm so cost reports and policies align), even though HCL identifiers are snake_case — quote them: `"costCenter" = var.cost_center`, `"managedBy" = "terraform"`. Required keys: `environment`, `workload`, `costCenter`, `owner`, `managedBy`, `dataClassification`. See `iac-best-practices` §2 for the authoritative list.
- **No data sources for things you create** in the same root — pass values via outputs.
- **No `count` for conditional resources** if `for_each` works — `for_each` is stable across reorderings.
- **Use `azapi` provider** for resources/properties not yet in `azurerm` — don't block on missing coverage.
- **Managed identity over service principals** for runtime auth.
- **No public network access by default** — private endpoints + private DNS zones for PaaS.
- **Sensitive variables** marked `sensitive = true`; no secrets in `terraform.tfvars`. Use Key Vault data sources or pipeline-injected env vars.
- **State file is canonical.** Never edit `.tfstate` by hand. Use `terraform state mv/rm/import` for surgical changes.

## 4. Validate before handing off

```powershell
terraform fmt -recursive
terraform init -backend=false  # quick local validate without contacting backend
terraform validate
terraform plan -out tfplan      # against the real backend
terraform show -no-color tfplan
```

Optional but recommended scanners (run if installed):

```powershell
tflint
tfsec        # or  trivy config .
checkov -d .
```

Fix everything you introduced. Don't `-disable-rule` without a written justification.

## 5. Hand off

```
TERRAFORM IMPLEMENTATION COMPLETE
- Files: <list>
- Backend: <local | azurerm | tfc>
- Modules used (with versions): <list>
- Plan summary: +<N> to add, ~<N> to change, -<N> to destroy
- Sensitive outputs: <list>
- Open items for review: <if any>
```

## 6. What you do NOT do

- Don't `terraform apply` from this skill — `azure-deploy` owns that.
- Don't change provider versions or backend config without surfacing the impact.
- Don't add CI/CD — that's `cicd-pipeline-implementation`.
- Don't commit mid-workflow — commit once the task is complete, not file by file, and never to the default branch.

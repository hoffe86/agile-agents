---
name: terraform-azure-implementation
description: Implement Azure infrastructure using Terraform (azurerm + AzAPI providers), preferring Azure Verified Modules (AVM) for Terraform and following HashiCorp + Microsoft style guides. USE FOR any request to write, add, modify, or refactor `.tf` files, Terraform modules, `terraform.tfvars`, or to migrate ARM/Bicep to Terraform on Azure. Triggered by "Terraform", "azurerm", "AzAPI", "tfvars", "terraform module", "AVM Terraform".
applies_to: azure, terraform
---

# Terraform (Azure) Implementation

You are implementing or modifying Terraform code that targets Azure.

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
- Don't commit.

---
name: bicep-implementation
description: Implement Azure infrastructure using Bicep with Azure Verified Modules (AVM) wherever possible, following Microsoft's published Bicep best practices and Well-Architected Framework. USE FOR any request to write, add, modify, or refactor `.bicep` files, Bicep modules, `main.bicep`, parameter files (`*.bicepparam`), or to migrate ARM JSON to Bicep. Triggered by "Bicep", "AVM", "Azure Verified Module", "deploy with Bicep", "Bicep module".
applies_to: azure, bicep
---

# Bicep Implementation

You are implementing or modifying Bicep infrastructure for Azure.

## 1. Understand the existing state first

- Read `main.bicep`, `*.bicepparam`, `bicepconfig.json`, and any `azure.yaml` (azd) at the repo root.
- Identify deployment scope: subscription, resource group, management group, tenant.
- Check whether the project already uses **AVM** modules (`br/public:avm/...`).
- Confirm Bicep CLI version: `bicep --version` (target ≥ 0.30 for newer syntax like `func`, user-defined types).

If the codebase is unfamiliar, invoke **`acquire-codebase-knowledge`** first.
For app-centric provisioning workflows, prefer the **`azure-prepare`** plugin skill — it owns the `.azure/plan.md` + `azd` flow.
For enterprise / landing-zone work, prefer **`azure-enterprise-infra-planner`** plugin skill.

## 2. Compose with these skills and tools

| Concern | Skill / Tool |
|---|---|
| Pull AVM modules and keep them current | `update-avm-modules-in-bicep` (vendored) |
| Convert ARM JSON to Bicep | `import-infrastructure-as-code` (vendored) |
| Authoritative resource schemas | **`azure-bicepschema`** MCP tool |
| Pre-deploy compliance scan | `azure-compliance` skill (azqr) |
| Architectural review | `azure-wellarchitectedframework` MCP tool |
| Cost estimation | `azure-pricing` MCP tool |
| Quotas / region availability | `azure-quotas` MCP tool |
| RBAC role assignments | `azure-rbac` skill |
| Deploy when ready | `azure-deploy` skill (`azd up`, `az deployment`) |

## 3. Default conventions

- **AVM first.** Reach for `br/public:avm/res/<service>/<resource>:<version>` before authoring resource definitions by hand. Pin a specific version, not `latest`.
- **One file = one purpose.** `main.bicep` is the entry point; extract per-service modules into `modules/<service>.bicep`.
- **Use parameters with `@description`, `@minLength/@maxLength`, `@allowed`, `@secure`.** Mark every secret-bearing param `@secure()`.
- **No hard-coded names.** Generate via `uniqueString(resourceGroup().id, ...)` or accept a `namePrefix` parameter; honor the project's naming convention (CAF: `<resource-type-abbrev>-<workload>-<env>-<region>-###`).
- **Tags on every resource group and resource.** Inherit a `tags` parameter top-down. Required tags (canonical camelCase keys — match across Bicep / Terraform / Helm so cost reports and policies align): `environment`, `workload`, `costCenter`, `owner`, `managedBy: bicep`, `dataClassification`. See `iac-best-practices` §2 for the authoritative list.
- **Outputs for everything the caller will need** (resource IDs, FQDNs, principal IDs). Mark outputs `@secure()` if they carry secrets — but prefer Key Vault references over emitting secrets.
- **Managed identities over connection strings.** Use system-assigned MI by default; user-assigned only when shared across resources.
- **No public endpoints by default.** Private endpoints + private DNS zones for PaaS services unless the user explicitly opts out.
- **`existing` keyword** when referencing resources you don't own (e.g., shared Key Vault, log analytics workspace).
- **Use `loadTextContent` / `loadJsonContent`** for embedding scripts or policies, not inline strings.
- **Avoid `array()`-wrapping single items.** Use `[item]` syntax.
- **User-defined types** (Bicep ≥ 0.21) for complex parameter shapes; better than relying on `object`.

## 4. Validate before handing off

```powershell
# Syntax + linter
bicep build main.bicep
bicep lint main.bicep

# What-if against the target subscription
az deployment sub what-if --location westeurope --template-file main.bicep --parameters main.bicepparam
# (or  az deployment group what-if  for RG scope)

# AVM version drift check
# (use update-avm-modules-in-bicep skill)
```

Address every linter warning that you introduced. Don't suppress warnings without a comment explaining why.

## 5. Hand off

Return to the orchestrator:

```
BICEP IMPLEMENTATION COMPLETE
- Files: <list>
- Scope: subscription | resourceGroup | mg | tenant
- AVM modules used: <list with versions>
- what-if summary: +<N> resources, ~<N> changes, -<N> deletions
- Open items for review: <if any>
```

## 6. What you do NOT do

- Don't `az deployment ... create` from this skill — that's `azure-deploy`'s job (and the orchestrator decides timing).
- Don't add a CI/CD pipeline — that's `cicd-pipeline-implementation`.
- Don't change `azd` environment values without surfacing it.
- Don't commit.

---
name: azure-platform-grounding
description: Azure grounding for authoring and reviewing — Cloud Adoption Framework (CAF) resource naming abbreviations and required tags, Azure Verified Module (AVM) selection and pinning, secure-by-default resource settings, the five Well-Architected pillars as concrete Azure review checks, and the MCSB / CIS Azure control ids reviewers cite findings against. USE FOR naming or tagging an Azure resource, picking or pinning an AVM module, setting managed identity / Key Vault / private endpoint defaults, assessing an Azure design or diff against reliability / security / cost / operational excellence / performance, or citing a control id on an Azure finding. Triggered by "CAF naming", "resource abbreviation", "AVM", "Azure Verified Module", "Well-Architected", "WAF pillar", "MCSB", "CIS Azure", "landing zone".
applies_to: azure
---

# Azure platform grounding

Load this when `solution-profile.yaml: infrastructure.cloud` is `azure`. It is the Azure
substitution for the neutral terms core agents use — "verified module" → AVM, "naming
convention" → CAF, "well-architected pillars" → WAF, "security benchmark" → whatever
`compliance_security.security_benchmarks` lists (typically `mcsb`, `cis-azure`), "managed
secrets store" → Key Vault.

It is **grounding, not automation**: conventions and review criteria that apply to a diff or a
design, before anything is deployed. For live-subscription work — scanning deployed resources,
querying actual spend, provisioning, diagnostics — install
[`microsoft/azure-skills`](https://github.com/microsoft/azure-skills) and use those skills plus
the Azure MCP Server they ship. The two are complementary; this skill does not duplicate them.

## 1. Naming

Default to the CAF pattern unless `infrastructure.naming_convention` says otherwise — the
profile always wins:

```
<resource-type-abbrev>-<workload>-<env>-<region-abbrev>[-###]
rg-payments-prod-weu          kv-payments-prod-weu
stpaymentsprodweu             (storage: no hyphens, <=24 chars, lowercase)
```

`<env>` is one of `dev, test, stg, prod` (use `stg`, not `staging`). Common abbreviations — the
full table is the
[CAF abbreviations reference](https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/ready/azure-best-practices/resource-abbreviations),
consult it rather than inventing one:

| Resource | Abbrev | Resource | Abbrev |
|---|---|---|---|
| Resource group | `rg-` | Key Vault | `kv-` |
| Virtual network | `vnet-` | Storage account | `st` (no hyphen) |
| Subnet | `snet-` | Log Analytics workspace | `log-` |
| Network security group | `nsg-` | App Service plan | `asp-` |
| Private endpoint | `pep-` | App Service / Function | `app-` / `func-` |
| Managed identity | `id-` | Container app / environment | `ca-` / `cae-` |
| AKS cluster | `aks-` | Container registry | `cr` (no hyphen) |
| SQL server / database | `sql-` / `sqldb-` | Cosmos DB | `cosmos-` |
| Application Insights | `appi-` | Service Bus namespace | `sb-` |

**Watch the per-service rules** — they are the usual cause of a failed deployment. Storage
accounts and container registries are lowercase alphanumeric only; Key Vault names are globally
unique and 3–24 chars; several services reject what a hyphenated pattern produces. Generate
names from a `namePrefix` parameter or a uniqueness suffix (`uniqueString()` / `random_id`) —
never hard-code.

## 2. Tagging

Apply `infrastructure.tagging_convention` when the profile declares one. Otherwise the CAF
minimum, set at resource-group level and inherited: `Environment`, `Workload`, `Owner`,
`CostCenter`, `Criticality`, `DataClassification` (mirror
`compliance_security.data_classification`), `ManagedBy: IaC`.

Tags are how anyone answers "who owns this and what does it cost" six months later. An untagged
production resource is a finding.

## 3. Modules — Azure Verified Modules

**Prefer AVM over hand-rolled resources.** AVM modules are Microsoft-maintained, WAF-aligned,
and ship secure defaults you would otherwise have to remember.

- **Look for the module first** — check the
  [AVM index](https://azure.github.io/Azure-Verified-Modules/indexes/) before authoring
  resources directly. Both Bicep and Terraform flavours exist.
- **Pin the version.** Floating to latest turns an unrelated deployment into an unreviewed
  infrastructure change.
- **Do not fork a module for one tweak.** Most AVM modules expose the escape hatch you need; if
  not, file an issue upstream and use a native resource *alongside* the module, not a fork.
- **Justify going custom** in the hand-off. "No AVM module exists for X" is a fine reason;
  "I didn't check" is not.

## 4. Secure-by-default resource settings

Create Azure resources with these on unless there is a stated reason not to. Each absence is a
review finding, not a preference:

- **Managed identity** (user-assigned for anything shared) — never connection strings, account
  keys, or service-principal secrets in IaC.
- **RBAC over access policies and shared keys**, assigned at the narrowest scope that works.
- **Key Vault references** for every secret a service consumes; the vault has soft delete and
  purge protection on.
- **Public network access disabled + private endpoint** where the profile requires private
  connectivity; otherwise an explicit, documented allow-list — never "all networks" by default.
- **Diagnostic settings** to a Log Analytics workspace, retention matched to the compliance
  scope.
- **TLS 1.2 or higher**, HTTPS-only, encryption at rest with platform-managed keys minimum
  (customer-managed where the data classification demands it).
- **Deletion protection** on stateful production resources (locks, soft delete, backup).

## 5. Topology

- **Resource group per lifecycle**, not per resource type. Things deleted together live
  together.
- **Subscription per environment** for anything with a production tier — it is the only boundary
  that reliably separates quota, policy, and blast radius.
- **Follow the landing zone if the organisation has one.** Do not invent networking, policy, or
  identity structure a platform team already owns. If the profile declares a landing zone and
  you cannot see it, say so rather than guessing.
- **Region choice is a requirement, not a default** — constrained by
  `compliance_security.data_residency` and by which services and availability zones exist there.

## 6. The five Well-Architected pillars as review checks

Walk every Azure design and every non-trivial Azure infrastructure diff through all five. Say
which pillars you **deprioritised and why** — silent omission reads as an oversight. A pillar
with no finding is a pass; do not manufacture one per pillar.

| Pillar | Concrete Azure checks |
|---|---|
| **Reliability** | Zone-redundant SKUs where the region offers them; health probes on every load-balanced backend; retry with backoff in clients; failover target matches the declared RTO/RPO; no single-instance production compute; backup configured *and* restore rehearsed. |
| **Security** | The section 4 defaults, plus: no secret literals anywhere in IaC or state; least-privilege role assignments; logs retained to the compliance scope. |
| **Cost optimisation** | SKU justified against stated load, not chosen defensively; autoscale or scale-to-zero for bursty workloads; non-production on cheaper tiers or scheduled shutdown; reserved capacity considered for steady state; no orphaned disks, IPs, or snapshots. |
| **Operational excellence** | Everything in IaC, no click-ops; deployment repeatable through the declared pipeline; alerts on the SLIs backing the SLO, not raw CPU; a runbook for the top two failure modes; tagging good enough to answer ownership and cost. |
| **Performance efficiency** | SKU and tier sized against a stated target (P95 latency, RPS), not a guess; caching where the read pattern justifies it; data tier matched to the access pattern; async/queue decoupling for long-running work; region matched to user location and residency constraints. |

## 7. Citing a control id

Reviewers cite a canonical reference on every finding. On Azure the precedence is:

1. **OWASP / CWE** — application-level findings. Always preferred; they travel across platforms.
2. **MCSB control id** (e.g. `MCSB IM-1`, `MCSB NS-2`, `MCSB DP-4`) — platform and
   resource-configuration findings. The Microsoft Cloud Security Benchmark is the default Azure
   control set and maps onto CIS and NIST.
3. **CIS Azure Foundations Benchmark** (e.g. `CIS Azure 3.1`) — when the project lists
   `cis-azure` in `compliance_security.security_benchmarks`, or when CIS matches the finding
   more precisely than MCSB.
4. **WAF pillar** — design-level trade-offs that are not a control violation.

**Only cite a benchmark the profile declares.** A CIS Azure finding on a project that lists only
`mcsb` is noise — reframe it against MCSB or against the pillar.

## 8. Canonical references

- **[Azure Well-Architected Framework](https://learn.microsoft.com/en-us/azure/well-architected/)** — pillar deep-dives, service guides, assessment tool.
- **[Azure Architecture Center](https://learn.microsoft.com/en-us/azure/architecture/)** — reference architectures and cloud design patterns. Prefer a published reference architecture over an invented topology, and name the one you followed.
- **[Microsoft Cloud Security Benchmark](https://learn.microsoft.com/en-us/security/benchmark/azure/introduction)** — control ids and their CIS / NIST mappings.
- **[CIS Azure Foundations Benchmark](https://www.cisecurity.org/benchmark/azure)** — when the project declares it.

Reach these through the Microsoft Learn documentation MCP server (shipped by
`agile-agents-core`) rather than from memory — service defaults change.

## 9. What this skill does NOT do

- It does not write Bicep or Terraform syntax — that is `bicep-implementation` /
  `terraform-azure-implementation`.
- It does not touch a live subscription. Scanning deployed resources, querying spend,
  provisioning, and diagnostics belong to `microsoft/azure-skills` and the Azure MCP Server.
- It does not replace the neutral review lens. Secrets handling, least privilege, encryption,
  backup, logging, and pipeline supply-chain hardening are reviewed on every platform; this
  skill supplies only the Azure-specific detail and the control id to cite.

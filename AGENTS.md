<!-- GENERATED-BY: scripts/generate-agents-md.ps1 -->
# AGENTS.md — agile-agents

> Generated from `solution-profile.yaml` on 2026-08-04.
> Do not edit by hand — regenerate with `scripts/generate-agents-md.ps1` (or `.sh`).

This file follows the cross-vendor [AGENTS.md](https://agents.md) convention so that
agentic CLIs (Claude Code, Copilot CLI, Cursor, Aider, …) can pick up a portable
description of how this repository expects autonomous agents to behave. The
authoritative, richer machine-readable contract remains
[`solution-profile.yaml`](solution-profile.yaml) plus the per-agent
[`*.agent.md`](.github/agents/) files.

## Project context

- **Project**: agile-agents
- **Primary language(s)**: unspecified
- **Backlog platform**: unspecified
- **Documentation**: unspecified (platform: unspecified)
- **Branch naming**: unspecified
- **Commit convention**: unspecified
- **Default branch**: main

## How to interact

This repository runs a **supervisor + specialist** topology. The
`dev-lead` agent drives the **RPI pattern** (Research → Plan → Implement
→ Review): it researches against the prepared concept + ADRs, decomposes
the story into tasks that `backlog-manager` creates as child work items in
the tracker (approved by a human), then delegates to the specialist agents
in sequence (architect → coding → testing → infrastructure → review
fan-out). Each worker emits a **sentinel hand-off block** on
completion — those block names are canonical and parsed by
`dev-lead`:

- `IMPLEMENTATION COMPLETE` (coding)
- `TESTS COMPLETE` (testing)
- `INFRASTRUCTURE COMPLETE` (infrastructure)
- `ARCHITECTURE DESIGN COMPLETE` (architect)
- `REVIEW COMPLETE` (every reviewer)
- `TASKS PLANNED` (backlog-manager)

Agents **never commit or merge** — they propose changes for human review.
Reviewers are **read-only**. See `.github/AGENTS-MD-MAPPING.md` for the
full convention map.

## Agents

### `architect`

Read-only / advisory architect for application and cloud solution architecture (deepest support for Azure; other clouds and on-prem are handled from the provider's own guidance). Produces design artifacts (C4 sketches L1–L3, arc42-style one-pagers, technology recommendations, integration patterns, NFR analysis) that coding and infrastructure then implement. Decisions are captured inline in the design doc (arc42 §9 as a short table) and surfaced as trade-off bullets. USE FOR: design new system or component, evaluate architecture options, choose Azure services or topology, draft C4 / arc42 documentation, analyze NFRs / quality attributes, design integration / eventing patterns, plan API contracts before implementation, assess WAF impact of a design choice. DO NOT USE FOR: writing application code (use coding), writing IaC (use infrastructure), reviewing existing code (use review or architecture-review), running or fixing tests (use testing), end-to-end autonomous feature delivery (use dev-lead if present), authoring Architecture Decision Records (ADRs are written up-front by humans before the agent fleet runs — architect honours them and reports decision gaps, but never creates ADR files).

- **Tools**: agent, azure-mcp/search, edit, execute, read, search, todo, vscode, web
- **Sub-agents**: _none_

### `architecture-review`

Performs a focused, READ-ONLY architectural review of a diff. Reviews boundary integrity (bounded contexts, layering, cross-service writes, contract changes), design patterns, ADR alignment, NFR impact, dependency direction (Clean Architecture inward-only), and Azure Well-Architected pillar implications when cloud is involved. Distinguishes reversible vs irreversible decisions. Cites arc42, C4, WAF, MADR, microservices.io, DDD canon, ISO 25010. USE FOR: architecture-only review of a diff, check bounded-context / layering integrity, audit public-contract / API / event-schema change, assess WAF impact of a code change, validate ADR alignment, review introduction of a new integration / dependency, review microservice boundary changes. Auto-invoked by review when the diff crosses boundaries, changes contracts, or touches >10 files. DO NOT USE FOR: full multi-lens review (use review), designing new architecture before code exists (use architect), security review (use security-review), IaC topology review (use infrastructure-review), making changes (this agent is read-only). NEVER modifies code.

- **Tools**: azure-mcp/search, execute, read, search, todo, vscode, web
- **Sub-agents**: _none_

### `backlog-manager`

Create, improve, review, and maintain backlog work items (Epics, Features, Product Backlog Items, Issues, Tasks) in the team's tracker. USE FOR: creating work items from conversations, improving story formulations, checking consistency across related items, drafting acceptance criteria, updating tracker fields, linking parent/child relationships, reviewing backlog quality, or materialising a dev-lead Plan as child tasks under a parent story (the Plan workflow). DO NOT USE FOR: writing code, tests, or IaC (use coding / testing / infrastructure), design or ADR decisions (use architect), reviewing a diff (use review), estimating / prioritising / progressing item state on your own authority (the team decides — you capture what was agreed), end-to-end autonomous delivery (use dev-lead).

- **Tools**: agent, azure-mcp/search, browser, edit, execute, microsoft/azure-devops-mcp/*, read, search, todo, vscode, web
- **Sub-agents**: _none_

### `coding`

Implements features, fixes bugs, and refactors application code in any language the repo uses, following that ecosystem's current best practices. Deep skill support for C#/.NET (default .NET 10) and Python; other languages are handled from the repo's own conventions and the declared `tech_stack` profile. USE FOR: implement a feature, fix a bug, refactor code, add a class / module / function, integrate a library, migrate code between framework versions, apply a design pattern. DO NOT USE FOR: architecture / ADR / design decisions before code exists (use architect), Infrastructure-as-Code — Bicep / Terraform / Helm / Dockerfile / pipelines (use infrastructure), writing or fixing tests (use testing), reviewing or auditing code (use review), end-to-end autonomous delivery (use dev-lead if present). Hands off to testing when implementation is complete.

- **Tools**: agent, azure-mcp/search, edit, execute, read, search, todo, vscode, web
- **Sub-agents**: _none_

### `dev-lead`

Autonomous development lead. Takes a single, already-prepared requirement or user story and drives it end-to-end through the RPI pattern — Research → Plan → Implement → Review — by delegating to the specialist agents in sequence, enforcing a quality gate between each stage, passing context forward, and reporting one final Definition-of-Done verdict. In the Plan phase it decomposes the story into meaningful, independently- implementable tasks (each with acceptance criteria + an approach note) and has `backlog-manager` create them as child work items linked to the parent story in the tracker, then presents that plan for human approval. Owns decomposition, sequencing, gating, cross-stage context, failure triage, and scope control. USE FOR: "build me X end-to-end", "implement this story autonomously", "deliver this feature", multi-stage work that crosses research + planning + coding + testing + review, autonomous / unattended runs against a requirements file or backlog item, when you want one verdict instead of orchestrating the agents yourself. **Plans the work as tracker tasks and presents that plan for human approval before starting autonomous execution**; once approved, runs every remaining stage without further confirmation, stopping mid-run only on: ambiguity, gate failure surviving one retry, scope change, destructive action, missing secret, tracker-write failure, or ❌ Block review verdict. DO NOT USE FOR: a single stage in isolation — call the specialist directly (architect / coding / testing / review), quick edits or one-line fixes (use coding), pure design work (use architect), pure review (use review), Infrastructure-as-Code only (use infrastructure). Never silently expands scope — if the requirement is ambiguous, asks once up-front and stops.

- **Tools**: agent, execute, read, search, todo
- **Sub-agents**: architect, backlog-manager, coding, infrastructure, review, testing

### `infrastructure-review`

Performs a focused, READ-ONLY review of Infrastructure-as-Code changes — Bicep, Terraform, Helm / Kustomize, GitHub Actions, Azure Pipelines, Dockerfiles. Cloud-agnostic by contract; the deepest ruleset is Azure (Well-Architected Framework, Azure Verified Modules, CAF naming + tagging, CIS Azure Benchmark, Microsoft Cloud Security Benchmark), other clouds are reviewed against their own provider guidance and the repo's conventions. Always applies pipeline supply-chain hardening (OIDC over static credentials, pinned actions, build-once-promote-artifacts, SLSA). USE FOR: IaC-only review of a diff, audit Bicep / Terraform / Helm / Kustomize change, review pipeline (GitHub Actions / Azure Pipelines) hardening, check naming + tagging, check verified-module usage, audit Dockerfile, check secrets handling and OIDC adoption, WAF-pillar review of Azure infrastructure. Auto-invoked by review when the diff touches *.bicep / *.bicepparam / *.tf / *.tfvars / Chart.yaml / kustomization.yaml / k8s manifests / .github/workflows/*.yml / azure-pipelines.yml / Dockerfile. DO NOT USE FOR: full multi-lens review (use review), writing or modifying IaC (use infrastructure), application code review (use review), architectural / topology decisions before IaC exists (use architect). NEVER modifies code.

- **Tools**: azure-mcp/search, execute, read, search, todo, vscode, web
- **Sub-agents**: _none_

### `infrastructure`

Implements Infrastructure as Code (IaC) using Bicep, Terraform, Helm / Kustomize, Dockerfiles, and GitHub Actions / Azure Pipelines for CI/CD. Cloud-agnostic by contract, with the deepest skill support for Azure (AVM modules, CAF naming + tagging, WAF alignment); other clouds and on-prem are handled from the repo's own conventions and the provider's documentation. Picks the right technology-specific skill based on what already exists in the repo, then applies cross-cutting IaC best practices (managed identity over secrets, least-privilege, OIDC, pinned versions). USE FOR: write or modify Bicep / Terraform / Helm chart / Kustomize overlay / Dockerfile, create or update a CI/CD workflow, provision cloud resources, set up network topology / private endpoints, add workload identity + RBAC, configure a secrets store, define naming + tagging, harden a pipeline (OIDC, pinned actions, build-once-promote). DO NOT USE FOR: architecture / topology decisions before IaC exists (use architect), application code (use coding), reviewing existing IaC (use infrastructure-review), end-to-end autonomous delivery (use dev-lead if present). Owns its own IaC tests (Terratest / Pester / Bicep test framework) end-to-end — does NOT hand those off to testing (which is scoped to application unit / integration tests only). Hands off to infrastructure-review and review.

- **Tools**: agent, azure-mcp/search, edit, execute, read, search, todo, vscode, web
- **Sub-agents**: _none_

### `review`

Orchestrates a multi-lens, READ-ONLY code review of a diff or set of changed files. Performs the general code-quality review itself (Clean Code / SOLID / standards / regressions / docs) and delegates specialised lenses to security-review (always), test-review (when tests or testable code change), architecture-review (when boundaries / contracts / >10 files change), and infrastructure-review (when IaC / pipelines change). Merges all findings into a single severity-ranked report with one final verdict (worst-of all specialists). USE FOR: review a PR or branch, audit a diff, "check this change", request full multi-lens review, code health check on uncommitted work. DO NOT USE FOR: only one specialised lens — call the specialist directly (security-review / test-review / architecture-review / infrastructure-review), making code changes (this agent is read-only), fixing the findings (delegate back to coding / infrastructure / testing), end-to-end delivery (use dev-lead if present). NEVER modifies code.

- **Tools**: agent, azure-mcp/search, execute, read, search
- **Sub-agents**: architecture-review, infrastructure-review, security-review, test-review

### `security-review`

Performs a focused, READ-ONLY security review of a diff or set of changed files. Applies OWASP Top 10 / OWASP ASVS / CWE Top 25 / OWASP LLM Top 10 / NIST SSDF / Microsoft SDL / MCSB lenses. Catches injection, broken auth / authz, secrets, insecure deserialisation, SSRF, prompt injection, supply-chain, missing input validation, weak crypto, over-privilege. Produces severity-rated findings with canonical references (OWASP A0X / CWE-XXX / LLM0X) and concrete fixes. USE FOR: security-only review of a diff, threat-model-style code audit, check for secrets / hardcoded credentials, OWASP / CWE-aligned audit, AI / LLM safety review (prompt injection, jailbreak surface), supply-chain audit. Auto-invoked by review on every review. DO NOT USE FOR: full multi-lens review (use review — it invokes this agent automatically), fixing the findings (delegate back to coding / infrastructure), test-quality review (use test-review), architecture-level threat modelling before code exists (use architect + threat-model-analyst skill). NEVER modifies code.

- **Tools**: azure-mcp/search, execute, read, search, todo, vscode, web
- **Sub-agents**: _none_

### `test-review`

Performs a focused, READ-ONLY review of test code and test coverage in a diff. Reviews test quality (AAA structure, single responsibility per test, deterministic, isolated, fast), coverage of new / changed behaviour (happy path + edge cases + negative paths), test-double usage (mocking abuse, over-stubbing, fragile test patterns), and test infrastructure (fixtures, factories, no real secrets, no real network). Cites xUnit Test Patterns, Google Testing guidance, Fowler test pyramid, and language-specific best practices. USE FOR: test-only review of a diff, audit test quality, check coverage of new behaviour, find brittle / flaky / over-mocked tests, check AAA / naming conventions, review test infrastructure. Auto-invoked by review when the diff touches tests or adds testable production code. DO NOT USE FOR: full multi-lens review (use review), writing or fixing tests (use testing), security or architecture aspects of tests (use security-review / architecture-review). NEVER modifies code.

- **Tools**: azure-mcp/search, execute, read, search, todo, vscode, web
- **Sub-agents**: _none_

### `testing`

Adds, fixes, and runs tests for application code in any language the repo uses. Detects the existing test framework automatically and chases coverage of new / changed behaviour (not absolute %). Deep skill support for C#/.NET (xUnit / NUnit / MSTest / TUnit) and Python (pytest); other ecosystems are handled via the repo's existing test setup. USE FOR: write tests for new code, improve test coverage on a specific file / class / function, fix failing tests, add edge-case / negative-path tests, refactor brittle tests, set up test fixtures / factories, add integration tests for a feature. DO NOT USE FOR: implementing the production code under test (use coding first), reviewing test quality of someone else's diff (use test-review), IaC tests like Terratest / Pester (use infrastructure), end-to-end autonomous delivery (use dev-lead if present). Hands off to review when the suite is green.

- **Tools**: agent, azure-mcp/search, edit, execute, read, search, todo, vscode, web
- **Sub-agents**: _none_


## Skills

The following skills are available in `.github/skills/` (or
`skills/` at the repo root in the agile-agents source). Each skill
is a self-contained `<name>/SKILL.md` with YAML frontmatter and a
natural-language workflow.

- **acquire-codebase-knowledge** (`agile-agents-core`) — Use this skill when the user explicitly asks to map, document, or onboard into an existing codebase.
- **ado-work-items** (`agile-agents-ado`) — Azure DevOps Boards mechanics for reading and writing work items — MCP tool entry points, field mapping per work-item type (Epic / Feature / PBI / Issue / Task), markdown-vs-HTML formatting rules, ...
- **architecture-decision-records** (`agile-agents-core`) — Author Architecture Decision Records (ADRs) using the MADR (Markdown Any Decision Records) format.
- **architecture-design** (`agile-agents-core`) — Author or update a software/solution architecture design document.
- **aspire** (`agile-agents-dotnet`) — Aspire skill covering the Aspire CLI, AppHost orchestration, service discovery, integrations, MCP server, VS Code extension, Dev Containers, GitHub Codespaces, templates, dashboard, and deployment.
- **backlog-item-standards** (`agile-agents-core`) — Tracker-agnostic content standards for authoring backlog work items — body structure per work-item type (Epic / Feature / PBI / Issue), writing rules, BDD/Gherkin scenario format, and the Definitio...
- **bicep-implementation** (`agile-agents-bicep`) — Implement Azure infrastructure using Bicep with Azure Verified Modules (AVM) wherever possible, following Microsoft's published Bicep best practices and Well-Architected Framework.
- **breakdown-feature-implementation** (`agile-agents-core`) — Prompt for creating detailed feature implementation plans, following Epoch monorepo structure.
- **breakdown-test** (`agile-agents-core`) — Test Planning and Quality Assurance prompt that generates comprehensive test strategies, task breakdowns, and quality validation plans for GitHub projects.
- **cicd-pipeline-implementation** (`agile-agents-core`) — Implement CI/CD pipelines for infrastructure and application code using GitHub Actions or Azure Pipelines (YAML).
- **code-localisation** (`agile-agents-core`) — Locate the small set of code files relevant to a task in a large repository.
- **code-review-checklist** (`agile-agents-core`) — Perform a high-signal code review of a diff or set of changed files focused on correctness, design, readability, test quality, and documentation.
- **codeql** (`agile-agents-core`) — Comprehensive guide for setting up and configuring CodeQL code scanning via GitHub Actions workflows and the CodeQL CLI.
- **conventional-commit** (`agile-agents-core`) — Prompt and workflow for generating conventional commit messages using a structured XML format.
- **cost-budget** (`agile-agents-core`) — Read the per-run / per-phase cost envelope from `solution-profile.yaml: cost_envelope`, gate run start (refuse if envelope is missing on production-tier engagements), checkpoint at every phase tran...
- **create-github-action-workflow-specification** (`agile-agents-core`) — Create a formal specification for an existing GitHub Actions CI/CD workflow, optimized for AI consumption and workflow maintenance.
- **create-implementation-plan** (`agile-agents-core`) — Create a new implementation plan file for new features, refactoring existing code or upgrading packages, design, architecture or infrastructure.
- **csharp-implementation** (`agile-agents-dotnet`) — Implement C#/.NET features end-to-end using current best practices (modern C# language features, async correctness, DI, SOLID, secure-by-default).
- **csharp-testing** (`agile-agents-dotnet`) — Add or extend tests for C#/.NET code using xUnit, NUnit, MSTest, or TUnit (whichever the solution already uses), then run them and pursue coverage.
- **dev-lead-templates** (`agile-agents-core`) — Rendering templates for the dev-lead orchestration run — the plan-approval gate prompt (Stage 1.7), the conditional design-approval gate prompt (Stage 2.5), and the final Done/Stop report (Stage 6).
- **dotnet-design-pattern-review** (`agile-agents-dotnet`) — Review the C#/.NET code for design pattern implementation and suggest improvements.
- **e2e-testing** (`agile-agents-core`) — End-to-end testing playbook for full-stack work — Playwright (TypeScript/Python) or Selenium (Python) backend selected via `solution-profile.yaml: testing.e2e.framework` (or `none` to skip).
- **editorconfig** (`agile-agents-core`) — Generates a comprehensive and best-practice-oriented .editorconfig file based on project analysis and user preferences.
- **ef-core** (`agile-agents-dotnet`) — Get best practices for Entity Framework Core
- **git-commit** (`agile-agents-core`) — Execute git commit with conventional commit message analysis, intelligent staging, and message generation.
- **github-issues** (`agile-agents-github`) — GitHub Issues mechanics for reading and writing work items — tool entry points, the single-body field layout with section headings, cross-reference and closing-keyword syntax, labels / milestones /...
- **helm-kustomize-implementation** (`agile-agents-core`) — Implement Kubernetes deployments via raw manifests, Helm charts, or Kustomize overlays — with AKS in mind.
- **iac-best-practices** (`agile-agents-core`) — Cross-cutting Infrastructure-as-Code best practices that apply regardless of tool (Bicep, Terraform, Helm, Kustomize, ARM, Pulumi).
- **import-infrastructure-as-code** (`agile-agents-terraform`) — Import existing Azure resources into Terraform using Azure CLI discovery and Azure Verified Modules (AVM).
- **multi-stage-dockerfile** (`agile-agents-core`) — Create optimized multi-stage Dockerfiles for any language or framework
- **polyglot-test-agent** (`agile-agents-core`) — Generates comprehensive, workable unit tests for any programming language using a multi-agent pipeline.
- **pr-description** (`agile-agents-core`) — Generate a high-signal pull-request description from a diff and the run's hand-off context.
- **pytest-coverage** (`agile-agents-python`) — Run pytest tests with coverage, discover lines missing coverage, and increase coverage to 100%.
- **python-implementation** (`agile-agents-python`) — Implement Python features end-to-end using current best practices (type hints, src layout, ruff-clean, modern stdlib, async where appropriate).
- **python-testing** (`agile-agents-python`) — Add or extend tests for Python code using pytest (the de-facto standard), then run them and chase coverage.
- **read-repo-context** (`agile-agents-core`) — Canonical preamble every coding-suite agent loads at the start of a turn.
- **refactor** (`agile-agents-core`) — Surgical code refactoring to improve maintainability without changing behavior.
- **refactor-method-complexity-reduce** (`agile-agents-core`) — Refactor given method `${input:methodName}` to reduce its cognitive complexity to `${input:complexityThreshold}` or below, by extracting helper methods.
- **release-notes** (`agile-agents-core`) — Generate release notes (CHANGELOG entry + GitHub release body) from commit history between two refs.
- **reviewer-read-only-rules** (`agile-agents-core`) — Defence-in-depth read-only contract that every review agent enforces.
- **ruff-recursive-fix** (`agile-agents-python`) — Run Ruff checks with optional scope and rule overrides, apply safe and unsafe autofixes iteratively, review each change, and resolve remaining findings with targeted edits or user decisions.
- **run-event-log** (`agile-agents-core`) — Emit one JSON Lines event per phase boundary, tool call, and completion to `.copilot-runs/<run-id>/events.jsonl` for audit, cost tracking, and post-hoc analysis.
- **security-review** (`agile-agents-core`) — AI-powered codebase security scanner that reasons about code like a security researcher — tracing data flows, understanding component interactions, and catching vulnerabilities that pattern-matchin...
- **solution-profile-interview** (`agile-agents-core`) — Bootstrap or repair `.github/solution-profile.yaml` by discovering what the repo already tells you and interviewing the human only for what it can't.
- **terraform-azure-implementation** (`agile-agents-terraform`) — Implement Azure infrastructure using Terraform (azurerm + AzAPI providers), preferring Azure Verified Modules (AVM) for Terraform and following HashiCorp + Microsoft style guides.
- **terraform-azurerm-set-diff-analyzer** (`agile-agents-terraform`) — Analyze Terraform plan JSON output for AzureRM Provider to distinguish between false-positive diffs (order-only changes in Set-type attributes) and actual resource changes.
- **test-bar-gate** (`agile-agents-core`) — Pre-reviewer automated quality gate — runs lint, type-check, and unit tests after `coding`/`testing` finish and before the reviewer fan-out.
- **threat-model-analyst** (`agile-agents-core`) — Full STRIDE-A threat model analysis and incremental update skill for repositories and systems.
- **update-avm-modules-in-bicep** (`agile-agents-bicep`) — Update Azure Verified Modules (AVM) to latest versions in Bicep files.
- **webapp-testing** (`agile-agents-core`) — Toolkit for interacting with and testing local web applications using Playwright.

Mandatory-load skills (loaded by every agent regardless of context):

_(none configured)_

## Cost & evaluation

- **Evaluation harness**: see [`./eval/`](eval/)
- **Cost envelope**: see `solution-profile.yaml` → `cost_envelope` and
  the `cost-budget` skill for per-phase / per-run USD ceilings and
  model-tiering policy.
- **Run event log**: structured JSON events at
  `.copilot-runs/<run-id>/events.jsonl` — schema in
  `skills/run-event-log/SKILL.md`.

---

_Generated from `solution-profile.yaml` — do not edit by hand;
regenerate with `scripts/generate-agents-md.ps1`._

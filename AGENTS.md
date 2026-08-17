<!-- GENERATED-BY: scripts/generate-agents-md.ps1 -->
# AGENTS.md — agile-agents

> Generated from `solution-profile.yaml` on 2026-08-17.
> Do not edit by hand — regenerate with `scripts/generate-agents-md.ps1` (or `.sh`).

This file follows the cross-vendor [AGENTS.md](https://agents.md) convention so that
agentic CLIs (Claude Code, Copilot CLI, Cursor, Aider, …) can pick up a portable
description of how this repository expects autonomous agents to behave. The
authoritative, richer machine-readable contract remains
[`solution-profile.yaml`](solution-profile.yaml) plus the per-agent
[`*.agent.md`](.github/agents/) files.

## Project context

- **Project**: agile-agents
- **Primary language(s)**: powershell, python, shell
- **Backlog platform**: github-issues
- **Documentation**: docs/ (platform: in-repo)
- **Branch naming**: unspecified
- **Commit convention**: conventional-commits
- **Default branch**: main

## How to interact

This repository runs a **supervisor + specialist** topology. The
`dev-lead` agent drives the **RPI pattern** (Research → Plan → Implement
→ Review): it researches against the prepared concept + ADRs, decomposes
the story into tasks that `backlog-manager` creates as child work items in
the tracker (approved by a human), then delegates to the specialist agents
in sequence (architect → coding → infrastructure → review
fan-out). Each worker emits a **sentinel hand-off block** on
completion — those block names are canonical and parsed by
`dev-lead`:

- `IMPLEMENTATION COMPLETE` (coding — production code **and** the tests covering it)
- `ANALYSIS COMPLETE` (data-scientist — an answer plus its evidence)
- `INFRASTRUCTURE COMPLETE` (infrastructure)
- `ARCHITECTURE DESIGN COMPLETE` (architect)
- `REVIEW COMPLETE` (review-lead — the specialist reviewers report into it)
- `TASKS PLANNED` (backlog-manager)
- `BOOTSTRAP COMPLETE` (bootstrapper)

Agents branch, commit and push on their own — on a feature branch, never the default one.
**Opening a pull request needs the user's explicit approval**, and **completing, merging or
closing a PR is human-only, always**, as are force-pushing, rewriting shared history and
production deploys. Deployments to non-production run through the project's own pipeline and are gated
on `infrastructure.deploy_verify`. Reviewers are **read-only**. See `.github/AGENTS-MD-MAPPING.md` for the
full convention map.

## Agents

### `architect`

Read-only / advisory architect for application and cloud solution architecture on whatever platform the project targets — the cloud, hosting model and stack come from `solution-profile.yaml`, and vendor-specific depth comes from whichever skill plugins are installed. Produces design artifacts (C4 sketches L1–L3, arc42-style one-pagers, technology recommendations, integration patterns, NFR analysis) that coding and infrastructure then implement. Decisions are captured inline in the design doc (arc42 §9 as a short table) and surfaced as trade-off bullets. USE FOR: design new system or component, evaluate architecture options, choose cloud services or topology, draft C4 / arc42 documentation, analyze NFRs / quality attributes, design integration / eventing patterns, plan API contracts before implementation, assess well-architected impact of a design choice. DO NOT USE FOR: writing application code (use coding), writing IaC (use infrastructure), reviewing existing code (use review-lead or architecture-reviewer), running or fixing tests (use coding — it owns the tests for the code it writes), end-to-end autonomous feature delivery (use dev-lead if present), authoring Architecture Decision Records (ADRs are written up-front by humans before the agent fleet runs — architect honours them and reports decision gaps, but never creates ADR files).

- **Tools**: agent, azure-mcp-server/*, azure-mcp/*, azure/*, browser, context7/*, edit, execute, microsoft-docs/*, playwright/*, read, search, todo, vscode, web
- **Sub-agents**: _none_

### `architecture-reviewer`

Performs a focused, READ-ONLY architectural review of a diff. Reviews boundary integrity (bounded contexts, layering, cross-service writes, contract changes), design patterns, ADR alignment, NFR impact, dependency direction (Clean Architecture inward-only), and well-architected pillar implications when cloud is involved. Distinguishes reversible vs irreversible decisions. Cites arc42, C4, the target platform's well-architected framework, MADR, microservices.io, DDD canon, ISO 25010. USE FOR: architecture-only review of a diff, check bounded-context / layering integrity, audit public-contract / API / event-schema change, assess well-architected impact of a code change, validate ADR alignment, review introduction of a new integration / dependency, review microservice boundary changes. Auto-invoked by review-lead when the diff crosses boundaries, changes contracts, or touches >10 files. DO NOT USE FOR: full multi-lens review (use review-lead), designing new architecture before code exists (use architect), security review (use security-reviewer), IaC topology review (use infrastructure-reviewer), making changes (this agent is read-only). NEVER modifies code.

- **Tools**: browser, context7/*, execute, microsoft-docs/*, playwright/*, read, search, todo, vscode, web
- **Sub-agents**: _none_

### `backlog-manager`

Create, improve, review, and maintain backlog work items (Epics, Features, Product Backlog Items, Issues, Tasks) in the team's tracker. USE FOR: creating work items from conversations, improving work item formulations, checking consistency across related items, drafting acceptance criteria, updating tracker fields, linking parent/child relationships, reviewing backlog quality, or materialising a dev-lead Plan as child tasks under a parent work item (the Plan workflow). DO NOT USE FOR: writing code, tests, or IaC (use coding / infrastructure), design or ADR decisions (use architect), reviewing a diff (use review-lead), estimating / prioritising / progressing item state on your own authority (the team decides — you capture what was agreed), end-to-end autonomous delivery (use dev-lead). # `tools` is a filter, not a hint: a tracker server that is not listed here is unreachable even when # it is running. `github` and the ADO server names are granted below because those trackers ship a # mechanics skill. On any other tracker, add `'<your-server>/*'` here. # A grant must match the server's registered name exactly, and that name may itself contain a slash # (`microsoft/azure-devops-mcp`) — copy it verbatim from your mcp-config.json.

- **Tools**: ado/*, agent, azure-devops-mcp/*, azure-devops/*, browser, context7/*, edit, execute, github/*, microsoft-docs/*, playwright/*, read, search, todo, vscode, web
- **Sub-agents**: _none_

### `bootstrapper`

Sets up and configures the harness for a solution: runs the profile interview, writes `.github/solution-profile.yaml`, works out which companion plugins the declared stack actually needs, and installs them with the user's approval — then verifies the result and names what is still missing. Owns the one-off bootstrap and the repair path, so the delivery pipeline doesn't carry bootstrap logic it uses once per solution. USE FOR: "set up the harness here", "configure the agents for this repo", "bootstrap the solution profile", "which plugins do I need", "repair / update the profile", a first run in a repo that has no `solution-profile.yaml`, or a profile that is missing required fields. DO NOT USE FOR: delivering a requirement end-to-end (use dev-lead), writing code, tests or IaC (use coding / infrastructure), designing a system (use architect), reviewing a change (use review-lead), maintaining *this* harness repo's own vendored skills (that is the repo-local `capability-scout`). Never installs anything — plugin or otherwise — without explicit approval, and never invents a profile value to get past a question.

- **Tools**: browser, context7/*, edit, execute, microsoft-docs/*, playwright/*, read, search, todo, vscode, web
- **Sub-agents**: _none_

### `capability-scout`

Dependency manager for the harness's own artifacts. Works **demand-first**: derives what each phase of the pipeline needs for the declared stack, compares that against the skills actually installed and the routes agents actually declare, and reports the **gaps** — then looks for something to fill a *named* gap. In a consumer project it answers "which plugins does this stack need, and what will still be uncovered"; in the marketplace repo it also searches the curated sources, triages `scripts/check-vendored-drift.ps1` output, and proposes where an adopted artifact belongs. Presents findings and stops — a human approves every adoption. USE FOR: "what capability are we missing", "scout for .NET / Bicep / testing", "do we already have a skill for X", "which plugins should this project install", "audit our vendored skills", "triage the drift report", periodic coverage review. DO NOT USE FOR: running the profile interview or installing plugins (that is `bootstrapper` — it owns the write and the approval gate), delivering a requirement (use `dev-lead`), or writing the skill a gap calls for (a human decides; then a maintainer or `coding` writes it). Never adopts, installs, or edits an artifact itself.

- **Tools**: browser, context7/*, execute, github/*, microsoft-docs/*, playwright/*, read, search, todo, vscode, web
- **Sub-agents**: _none_

### `code-reviewer`

Performs a focused, READ-ONLY general code-quality review of a diff — the craft lens: correctness, line-level design, readability, standards compliance, error handling, regressions, cloud-native and resilience anti-patterns, and documentation currency. Judges the change against the repo's declared conventions (`solution-profile.yaml`, `copilot-instructions.md`) and accepted decision records. USE FOR: general-quality-only review of a diff, "is this code any good", Clean Code / SOLID / standards audit of a change, check for regressions or swallowed errors, check docs kept pace with behaviour. Auto-invoked by review-lead on every review. DO NOT USE FOR: full multi-lens review (use review-lead — it invokes this agent automatically), security findings (use security-reviewer), test quality or coverage (use test-reviewer), cross-module boundaries / contracts / ADR alignment (use architecture-reviewer), IaC and pipelines (use infrastructure-reviewer), fixing the findings (delegate back to coding / infrastructure), whole-repository audits with no diff (that is the `code-review` skill, run standalone). NEVER modifies code.

- **Tools**: browser, context7/*, execute, microsoft-docs/*, playwright/*, read, search, todo, vscode, web
- **Sub-agents**: _none_

### `coding`

Implements features, fixes bugs, and refactors application code **and covers the change with tests** — the two halves of one engineer's job, in any language the repo uses. Detects the existing test framework automatically and chases coverage of new / changed behaviour (not absolute %). Deep skill support for C#/.NET (default .NET 10) and Python; other languages are handled from the repo's own conventions and the declared `tech_stack` profile. USE FOR: implement a feature, fix a bug, refactor code, add a class / module / function, integrate a library, migrate code between framework versions, apply a design pattern, write tests for new code, improve coverage on a specific file / class / function, fix failing tests, add edge-case / negative-path tests, set up test fixtures / factories, add integration tests for a feature. DO NOT USE FOR: architecture / ADR / design decisions before code exists (use architect), Infrastructure-as-Code — Bicep / Terraform / Helm / Dockerfile / pipelines, and the IaC tests that go with them like Terratest / Pester (use infrastructure), reviewing or auditing code or test quality (use review-lead / test-reviewer), end-to-end autonomous delivery (use dev-lead if present). Hands off to review once the change builds and its tests are green.

- **Tools**: agent, browser, context7/*, edit, execute, microsoft-docs/*, playwright/*, read, search, todo, vscode, web
- **Sub-agents**: _none_

### `data-reviewer`

Performs a focused, READ-ONLY review of data-science and analytics work in a diff — the lens that judges whether a **conclusion survives scrutiny**, not whether the code is tidy. Reviews statistical validity (leakage, split discipline, baselines, metric choice and averaging, uncertainty, multiplicity), cohort fairness, reproducibility (seed, data version, re-run command), dataset provenance and epistemic status, PII in committed artifacts, and — for AI/LLM features — evaluation-set coverage and LLM-as-judge validity. USE FOR: data-only review of a diff, audit an analysis or model change, check an evaluation set, verify a reported metric is what it claims, check for train /test leakage, review notebook or experiment reproducibility, check cohort breakdown on a model that affects people. Auto-invoked by review-lead when the diff touches analysis, model, notebook, evaluation-set or metric code. DO NOT USE FOR: full multi-lens review (use review-lead — it invokes this agent automatically), general code craft in analysis code (use code-reviewer), data-handling security and secrets (use security-reviewer), test quality of ordinary unit tests (use test-reviewer), data-platform topology (use architecture-reviewer), producing or fixing the analysis (delegate back to data-scientist). NEVER modifies code, never re-runs an experiment to "check", and never re-fits a model.

- **Tools**: browser, context7/*, execute, microsoft-docs/*, playwright/*, read, search, todo, vscode, web
- **Sub-agents**: _none_

### `data-scientist`

Analyses data, designs and runs experiments, builds and evaluates models, and supports AI-integrated features with the evidence that says whether they work. Carries two evaluation rubrics and routes by what the project is building: **classical ML** (train/test/holdout discipline, leakage, calibration, drift, cohort fairness) and **AI/LLM** (evaluation-set design, groundedness, task adherence, LLM-as-judge caveats, responsible-AI risk-to-metric mapping). Owns the model and its evidence; `coding` owns the application that serves it. USE FOR: exploratory data analysis, data profiling and quality assessment, feature engineering, training or tuning a model, choosing and computing evaluation metrics, designing an evaluation set for an LLM or agent feature, measuring an AI feature's output quality, drift and cohort-fairness analysis, statistical questions ("is this difference real?"), and answering whether the data supports a proposed capability at all. DO NOT USE FOR: production application code, services or APIs — including the code that serves a model (use coding), Infrastructure-as-Code, pipelines or training-cluster provisioning (use infrastructure), system or data-platform architecture decisions (use architect), reviewing someone else's diff (use review-lead), end-to-end autonomous delivery (use dev-lead). Hands off with `ANALYSIS COMPLETE`, which reports a negative result as a legitimate outcome rather than a failure.

- **Tools**: agent, browser, context7/*, edit, execute, microsoft-docs/*, playwright/*, read, search, todo, vscode, web
- **Sub-agents**: _none_

### `dev-lead`

Autonomous development lead. Takes a single, already-prepared requirement and drives it end-to-end through the RPI pattern — Research → Plan → Implement → Review — by delegating to the specialist agents in sequence, enforcing a quality gate between each stage, passing context forward, and reporting one final Definition-of-Done verdict. In the Plan phase it decomposes the requirement into meaningful, independently- implementable tasks (each with acceptance criteria + an approach note) and has `backlog-manager` create them as child work items linked to the parent work item in the tracker, then presents that plan for human approval. Owns decomposition, sequencing, gating, cross-stage context, failure triage, and scope control. USE FOR: "build me X end-to-end", "implement this requirement autonomously", "deliver this feature", multi-stage work that crosses research + planning + coding + review, autonomous / unattended runs against a requirements file or backlog item, executing a plan you already produced in planning mode (hand it the `plan.md` path — it adopts that decomposition instead of re-deriving one), when you want one verdict instead of orchestrating the agents yourself. **Plans the work as tracker tasks and presents that plan for human approval before starting autonomous execution**; once approved, runs every remaining stage without further confirmation, stopping mid-run only on: ambiguity, gate failure surviving one retry, scope change, destructive action, missing secret, tracker-write failure, or ❌ Block review verdict. DO NOT USE FOR: a single stage in isolation — call the specialist directly (architect / coding / infrastructure / review), quick edits or one-line fixes (use coding), pure design work (use architect), pure review (use review-lead), Infrastructure-as-Code only (use infrastructure). Never silently expands scope — if the requirement is ambiguous, asks once up-front and stops.

- **Tools**: ado/*, agent, azure-devops-mcp/*, azure-devops/*, browser, context7/*, execute, microsoft-docs/*, playwright/*, read, search, todo, vscode, web
- **Sub-agents**: architect, backlog-manager, bootstrapper, coding, data-scientist, infrastructure, review-lead

### `infrastructure-reviewer`

Performs a focused, READ-ONLY review of Infrastructure-as-Code changes in whatever technology the repo uses — Terraform, Bicep, CloudFormation, Pulumi, ARM, Helm / Kustomize, Dockerfiles, and CI/CD pipeline definitions. Cloud- and tool-agnostic by contract: `solution-profile.yaml` declares the cloud, IaC tool, module source, naming / tagging conventions and security benchmarks, and findings are cited against that provider's own well-architected framework and benchmark. The cloud-neutral lens always applies — secrets handling, least-privilege identity, private networking, encryption, backup on stateful resources, logging / retention, version pinning, and pipeline supply-chain hardening (OIDC over static credentials, pinned actions, build-once-promote-artifacts, SLSA). USE FOR: IaC-only review of a diff, audit an IaC or Kubernetes manifest change, review pipeline hardening, check naming + tagging, check verified-module usage, audit a Dockerfile, check secrets handling and OIDC adoption, well-architected review of cloud infrastructure. Auto-invoked by review-lead when the diff touches IaC, Kubernetes manifests, pipeline definitions, or Dockerfiles. DO NOT USE FOR: full multi-lens review (use review-lead), writing or modifying IaC (use infrastructure), application code review (use review), architectural / topology decisions before IaC exists (use architect). NEVER modifies code.

- **Tools**: azure-mcp-server/*, azure-mcp/*, azure/*, browser, context7/*, execute, microsoft-docs/*, playwright/*, read, search, todo, vscode, web
- **Sub-agents**: _none_

### `infrastructure`

Implements Infrastructure as Code (IaC) in whatever technology the project declares — Terraform, Bicep, CloudFormation, Pulumi, ARM, Helm / Kustomize, Dockerfiles, and CI/CD pipeline definitions. Cloud- and tool-agnostic by contract: `solution-profile.yaml` declares the cloud, IaC tool, module source, hosting model, secrets store and naming / tagging conventions, and the agent routes to whichever implementation skill the project installed — falling back to the repo's own conventions and the provider's documentation when none is. Always applies the cross-cutting IaC lens (workload identity over secrets, least-privilege, OIDC, pinned versions, build-once-promote). USE FOR: write or modify IaC, a Kubernetes chart or overlay, or a Dockerfile; create or update a CI/CD workflow; provision cloud resources; set up network topology and private connectivity; add workload identity + role assignments; configure a secrets store; define naming + tagging; harden a pipeline (OIDC, pinned actions, build-once-promote). DO NOT USE FOR: architecture / topology decisions before IaC exists (use architect), application code (use coding), reviewing existing IaC (use infrastructure-reviewer), end-to-end autonomous delivery (use dev-lead if present). Owns its own IaC tests end-to-end — does NOT hand those off to coding (which owns application code and the unit / integration tests that cover it). Hands off to infrastructure-reviewer and review.

- **Tools**: agent, azure-mcp-server/*, azure-mcp/*, azure/*, browser, context7/*, edit, execute, microsoft-docs/*, playwright/*, read, search, todo, vscode, web
- **Sub-agents**: _none_

### `review-lead`

Orchestrates a multi-lens, READ-ONLY code review of a diff or set of changed files. Delegates every lens to a specialist — code-reviewer (general quality, always), security-reviewer (always), test-reviewer (when tests or testable code change), architecture-reviewer (when boundaries / contracts / >10 files change), and infrastructure-reviewer (when IaC / pipelines change) — then merges their findings into a single severity-ranked report with stable ids, an owner per finding, and one final verdict (worst-of all specialists). USE FOR: review a PR or branch, audit a diff, "check this change", request full multi-lens review, code health check on uncommitted work. DO NOT USE FOR: only one specialised lens — call the specialist directly (code-reviewer / security-reviewer / test-reviewer / data-reviewer / architecture-reviewer / infrastructure-reviewer), making code changes (this agent is read-only), fixing the findings (delegate back to coding / infrastructure), end-to-end delivery (use dev-lead if present). NEVER modifies code.

- **Tools**: agent, browser, context7/*, execute, microsoft-docs/*, playwright/*, read, search, todo, vscode, web
- **Sub-agents**: architecture-reviewer, code-reviewer, data-reviewer, infrastructure-reviewer, security-reviewer, test-reviewer

### `security-reviewer`

Performs a focused, READ-ONLY security review of a diff or set of changed files. Applies OWASP Top 10 / OWASP ASVS / CWE Top 25 / OWASP LLM Top 10 / NIST SSDF / Microsoft SDL, plus the security benchmarks the profile declares, lenses. Catches injection, broken auth / authz, secrets, insecure deserialisation, SSRF, prompt injection, supply-chain, missing input validation, weak crypto, over-privilege. Produces severity-rated findings with canonical references (OWASP A0X / CWE-XXX / LLM0X) and concrete fixes. USE FOR: security-only review of a diff, threat-model-style code audit, check for secrets / hardcoded credentials, OWASP / CWE-aligned audit, AI / LLM safety review (prompt injection, jailbreak surface), supply-chain audit. Auto-invoked by review-lead on every review. DO NOT USE FOR: full multi-lens review (use review-lead — it invokes this agent automatically), fixing the findings (delegate back to coding / infrastructure), test-quality review (use test-reviewer), architecture-level threat modelling before code exists (use architect + threat-model-analyst skill). NEVER modifies code.

- **Tools**: browser, context7/*, execute, microsoft-docs/*, playwright/*, read, search, todo, vscode, web
- **Sub-agents**: _none_

### `test-reviewer`

Performs a focused, READ-ONLY review of test code and test coverage in a diff. Reviews test quality (AAA structure, single responsibility per test, deterministic, isolated, fast), coverage of new / changed behaviour (happy path + edge cases + negative paths), test-double usage (mocking abuse, over-stubbing, fragile test patterns), and test infrastructure (fixtures, factories, no real secrets, no real network). Cites xUnit Test Patterns, Google Testing guidance, Fowler test pyramid, and language-specific best practices. USE FOR: test-only review of a diff, audit test quality, check coverage of new behaviour, find brittle / flaky / over-mocked tests, check AAA / naming conventions, review test infrastructure. Auto-invoked by review-lead when the diff touches tests or adds testable production code. DO NOT USE FOR: full multi-lens review (use review-lead), writing or fixing tests (use coding — it owns the tests for the code it writes), security or architecture aspects of tests (use security-reviewer / architecture-reviewer). NEVER modifies code.

- **Tools**: browser, context7/*, execute, microsoft-docs/*, playwright/*, read, search, todo, vscode, web
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
- **artifact-coverage** (`agile-agents-core`) — Work out which capabilities the agent harness needs for a given stack, which installed skills cover them, and where the gaps are — then judge whether a candidate artifact is worth adopting and whic...
- **aspire** (`agile-agents-dotnet`) — Aspire skill covering the Aspire CLI, AppHost orchestration, service discovery, integrations, MCP server, VS Code extension, Dev Containers, GitHub Codespaces, templates, dashboard, and deployment.
- **azure-deployment-preflight** (`agile-agents-bicep`) — Performs comprehensive preflight validation of Bicep deployments to Azure, including template syntax validation, what-if analysis, and permission checks.
- **azure-platform-grounding** (`agile-agents-azure`) — Azure grounding for authoring and reviewing — Cloud Adoption Framework (CAF) resource naming abbreviations and required tags, Azure Verified Module (AVM) selection and pinning, secure-by-default re...
- **backlog-item-standards** (`agile-agents-core`) — Tracker-agnostic content standards for authoring backlog work items — body structure per work-item type (Epic / Feature / PBI / Issue), writing rules, BDD/Gherkin scenario format, and the Definitio...
- **bicep-implementation** (`agile-agents-bicep`) — Implement Azure infrastructure using Bicep with Azure Verified Modules (AVM) wherever possible, following Microsoft's published Bicep best practices and Well-Architected Framework.
- **cicd-pipeline-implementation** (`agile-agents-core`) — Implement CI/CD pipelines for infrastructure and application code using GitHub Actions or Azure Pipelines (YAML).
- **cloud-native-patterns** (`agile-agents-core`) — Canonical reference for cloud design patterns, resilience defaults, 12-Factor cloud-native readiness, observability, and HTTP/gRPC API hygiene used by the authoring and review agents.
- **code-localisation** (`agile-agents-core`) — Locate the small set of code files relevant to a task in a large repository.
- **code-review-checklist** (`agile-agents-core`) — Perform a high-signal code review of a diff or set of changed files focused on correctness, design, readability, test quality, and documentation.
- **code-reviewer** (`agile-agents-core`) — Standalone whole-repository code audit — no diff, no pipeline.
- **codeql** (`agile-agents-core`) — Comprehensive guide for setting up and configuring CodeQL code scanning via GitHub Actions workflows and the CodeQL CLI.
- **conventional-commit** (`agile-agents-core`) — Prompt and workflow for generating conventional commit messages using a structured XML format.
- **cost-budget** (`agile-agents-core`) — Read the per-run / per-phase cost envelope from `solution-profile.yaml: cost_envelope`, gate run start (refuse if envelope is missing on production-tier engagements), checkpoint at every phase tran...
- **csharp-implementation** (`agile-agents-dotnet`) — Implement C#/.NET features end-to-end using current best practices (modern C# language features, async correctness, DI, SOLID, secure-by-default).
- **csharp-testing** (`agile-agents-dotnet`) — Add or extend tests for C#/.NET code using xUnit, NUnit, MSTest, or TUnit (whichever the solution already uses), then run them and pursue coverage.
- **data-engineering-practices** (`agile-agents-core`) — The craft bar for moving and shaping data — data contracts, schema evolution, idempotent and replayable loads, partitioning, backfills, quality gates that fail loudly, lineage, orchestration hygien...
- **data-science-practices** (`agile-agents-core`) — The craft bar for data work — question-before-method discipline, data quality and provenance, leakage and split hygiene, baselines, uncertainty, cohort fairness, reproducibility, and PII/synthetic-...
- **deploy-verify** (`agile-agents-core`) — Opt-in deployed verification — push the feature branch, let the project's own CI/CD pipeline deploy pipeline + IaC + application to the first non-production environment, and report whether it actua...
- **dev-lead-templates** (`agile-agents-core`) — Rendering templates for the dev-lead orchestration run — the plan-approval gate prompt (Stage 4), the conditional design-approval gate prompt (Stage 5), and the final Done/Stop report (Stage 9).
- **development-practices** (`agile-agents-core`) — The implementation half of the build-and-verify craft — smallest-change bias, no speculative generality, cloud-native and observability defaults, error handling, documentation-in-the-same-change, l...
- **dotnet-design-pattern-review** (`agile-agents-dotnet`) — Review the C#/.NET code for design pattern implementation and suggest improvements.
- **dotnet-startup-discovery** (`agile-agents-dotnet`) — Work out how to start a .NET application and which URL proves it came up — Aspire AppHost, Azure Functions, ASP.NET Core web projects, console/worker services — by reading what the project already ...
- **e2e-testing** (`agile-agents-core`) — End-to-end testing playbook for full-stack work — Playwright (TypeScript/Python) or Selenium (Python) backend selected via `solution-profile.yaml: testing.e2e.framework` (or `none` to skip).
- **editorconfig** (`agile-agents-core`) — Generates a comprehensive and best-practice-oriented .editorconfig file based on project analysis and user preferences.
- **ef-core** (`agile-agents-dotnet`) — Get best practices for Entity Framework Core
- **engineering-judgement** (`agile-agents-core`) — The operating posture every agent in the suite works to — how someone with long experience in the role decides, escalates, and reports.
- **engineering-standards** (`agile-agents-core`) — The engineering quality bar every agent in the suite works to — Clean Code, SOLID, DDD, Clean Architecture, security-by-default, error handling, immutability, configuration over hardcoding, Infrast...
- **git-commit** (`agile-agents-core`) — Execute git commit with conventional commit message analysis, intelligent staging, and message generation.
- **github-issues** (`agile-agents-github`) — GitHub Issues mechanics for reading and writing work items — tool entry points, the single-body field layout with section headings, cross-reference and closing-keyword syntax, labels / milestones /...
- **helm-kustomize-implementation** (`agile-agents-core`) — Implement Kubernetes deployments via raw manifests, Helm charts, or Kustomize overlays — with AKS in mind.
- **iac-best-practices** (`agile-agents-core`) — Cross-cutting Infrastructure-as-Code best practices that apply regardless of tool (Bicep, Terraform, Helm, Kustomize, ARM, Pulumi) or cloud.
- **import-infrastructure-as-code** (`agile-agents-terraform`) — Import existing Azure resources into Terraform using Azure CLI discovery and Azure Verified Modules (AVM).
- **multi-stage-dockerfile** (`agile-agents-core`) — Create optimized multi-stage Dockerfiles for any language or framework
- **playwright-generate-test** (`agile-agents-core`) — Generate a Playwright test based on a scenario using Playwright MCP
- **polyglot-test-agent** (`agile-agents-core`) — Generates comprehensive, workable unit tests for any programming language using a multi-agent pipeline.
- **pr-description** (`agile-agents-core`) — Generate a high-signal pull-request description from a diff and the run's hand-off context.
- **pytest-coverage** (`agile-agents-python`) — Run pytest tests with coverage, discover lines missing coverage, and increase coverage to 100%.
- **python-implementation** (`agile-agents-python`) — Implement Python features end-to-end using current best practices (type hints, src layout, ruff-clean, modern stdlib, async where appropriate).
- **python-startup-discovery** (`agile-agents-python`) — Work out how to start a Python application and which URL proves it came up — console scripts, FastAPI/Starlette, Flask, Django, `python -m <package>` — by reading what the project already declares ...
- **python-testing** (`agile-agents-python`) — Add or extend tests for Python code using pytest (the de-facto standard), then run them and chase coverage.
- **read-repo-context** (`agile-agents-core`) — Canonical preamble every coding-suite agent loads at the start of a turn.
- **refactor** (`agile-agents-core`) — Surgical code refactoring to improve maintainability without changing behavior.
- **release-notes** (`agile-agents-core`) — Generate release notes (CHANGELOG entry + GitHub release body) from commit history between two refs.
- **reviewer-read-only-rules** (`agile-agents-core`) — Defence-in-depth read-only contract that every review agent enforces.
- **ruff-recursive-fix** (`agile-agents-python`) — Run Ruff checks with optional scope and rule overrides, apply safe and unsafe autofixes iteratively, review each change, and resolve remaining findings with targeted edits or user decisions.
- **run-event-log** (`agile-agents-core`) — Emit one JSON Lines event per phase boundary, tool call, and completion to `.copilot-runs/<run-id>/events.jsonl` for audit, cost tracking, and post-hoc analysis.
- **security-reviewer** (`agile-agents-core`) — AI-powered codebase security scanner that reasons about code like a security researcher — tracing data flows, understanding component interactions, and catching vulnerabilities that pattern-matchin...
- **solution-profile-interview** (`agile-agents-core`) — Bootstrap or repair `.github/solution-profile.yaml` by discovering what the repo already tells you and interviewing the human only for what it can't.
- **terraform-azure-implementation** (`agile-agents-terraform`) — Implement Azure infrastructure using Terraform (azurerm + AzAPI providers), preferring Azure Verified Modules (AVM) for Terraform and following HashiCorp + Microsoft style guides.
- **terraform-azurerm-set-diff-analyzer** (`agile-agents-terraform`) — Analyze Terraform plan JSON output for AzureRM Provider to distinguish between false-positive diffs (order-only changes in Set-type attributes) and actual resource changes.
- **test-bar-gate** (`agile-agents-core`) — Pre-reviewer automated quality gate — runs lint, type-check, unit tests, and a local smoke check (does the app actually come up?) after the implementation stage finishes and before the reviewer fan...
- **testing-practices** (`agile-agents-core`) — The verification half of the build-and-verify craft — test-behaviour-not- implementation bias, coverage of the changed behaviour, mocking discipline, determinism rules, framework routing, interacti...
- **threat-model-analyst** (`agile-agents-core`) — Full STRIDE-A threat model analysis and incremental update skill for repositories and systems.
- **trade-off-reporting** (`agile-agents-core`) — Standard format and rules for surfacing trade-offs an agent made while designing, coding, provisioning infrastructure, or writing tests.
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

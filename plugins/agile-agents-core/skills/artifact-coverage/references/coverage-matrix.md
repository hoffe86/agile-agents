# Coverage matrix — what each phase needs, and whether we have it

The worked example, and the marketplace's own current answer. Scouting is **demand-driven**: start
from what the harness's phases require, find the gaps, then look for something to fill a *named*
gap. Browsing a source and asking "is any of this useful?" finds things by luck; this finds them
by construction.

Both gaps closed in August 2026 — application startup discovery and Bicep deployment preflight —
were found reactively, after a run needed them. This matrix exists so the next one is found first.

## Reading a cell

| Cell | Means |
|---|---|
| **covered** | A skill exists and an agent (or another skill) routes to it. |
| **gap** | A phase needs this for that ecosystem and nothing provides it. A candidate to scout for. |
| **n/a** | The capability does not apply. **Not a defect** — say why, or the next reader re-opens it. |
| **built-in** | The ecosystem's own tooling covers it; a skill would add nothing. |

An empty cell is never self-explanatory. The distinction between *gap* and *n/a* is the whole
value of the matrix — the smoke slot learned the same lesson: "nothing to start here" and "I could
not work out how to start it" must not report identically.

## Delivery capabilities × ecosystem

The marketplace's coverage at the time of writing. In a consumer repo, build the same grid from
the *installed* plugins and the stack `solution-profile.yaml` declares.

| Capability | Phase | .NET | Python | Bicep | Terraform |
|---|---|---|---|---|---|
| Implement | 6 | `csharp-implementation` | `python-implementation` | `bicep-implementation` | `terraform-azure-implementation` |
| Unit test | 7 | `csharp-testing` | `python-testing` | n/a — IaC has no unit layer at this gate | n/a — same |
| **IaC test** | 6/7 | n/a | n/a | **gap** | **gap** |
| Coverage | 7 | **gap** — `csharp-testing` covers it inline; no dedicated skill | `pytest-coverage` | n/a | n/a |
| Lint / autofix | 8 | **gap** — `dotnet format` is in the gate palette, no skill | `ruff-recursive-fix` | built-in (`bicep lint`) | built-in (`fmt` / `validate`) |
| Startup discovery | 8 | `dotnet-startup-discovery` | `python-startup-discovery` | n/a — nothing to start | n/a — nothing to start |
| Deploy preflight | 8b | n/a | n/a | `azure-deployment-preflight` | **gap** — `plan` is built-in, but nothing covers policy / quota / permission preflight |
| Design-pattern review | 9 | `dotnet-design-pattern-review` | **gap** | n/a | n/a |
| Format migration | — | n/a | n/a | `update-avm-modules-in-bicep` | `import-infrastructure-as-code` |

### The IaC-test gap is the one that matters

`infrastructure.agent.md` states it "owns its own IaC tests end-to-end", `dev-lead` Stage 7 skips
testing for IaC-only changes *because* infrastructure already ran them, and `test-bar-gate` names
Terratest and Pester. **No skill covers any of it.** The harness assumes a capability it does not
ship — so an agent doing IaC tests works from the repo's conventions with no guidance, and the
Stage 7 skip hands off to something that may not exist.

## Cross-cutting capabilities

Ecosystem-neutral, all in core. Listed so a run can confirm coverage rather than assume it.

| Capability | Covered by |
|---|---|
| Repo context / preamble | `read-repo-context` |
| Code localisation | `code-localisation` |
| Quality bar | `engineering-standards`, `code-review-checklist` |
| Security lens | `security-review`, `threat-model-analyst`, `codeql` |
| Architecture | `architecture-design`, `architecture-decision-records` |
| Backlog | `backlog-item-standards` + tracker mechanics (`ado-work-items` / `github-issues`) |
| Gates | `test-bar-gate`, `deploy-verify` |
| Telemetry / cost | `run-event-log`, `cost-budget` |
| Delivery artifacts | `pr-description`, `release-notes`, `conventional-commit`, `git-commit` |
| Bootstrap | `solution-profile-interview` |

## Ecosystems with no companion at all

Go, Java, TypeScript / Node, Rust, PHP, Ruby. **Deliberate** — the declared technology scope is
Azure + .NET / Python + Bicep / Terraform, and a skill per ecosystem nobody here ships is a fork's
job. Agents fall back to the repo's own conventions and say so in their hand-off.

In a consumer repo this is the most useful thing to report: *"your stack includes Go; no companion
covers it, so expect repo-convention fallback rather than deep guidance."* Expected behaviour,
stated up front, beats the same thing discovered mid-run.

## Declined — do not re-litigate without a reason

Assessed and rejected for the marketplace. Re-open one only when its stated condition changes.

| Artifact | Source | Declined because | Would change if |
|---|---|---|---|
| quality-playbook | awesome-copilot | 41,795 words — 15× our largest artifact — and its "Council of Three" audit overlaps the five-reviewer fan-out | it were decomposed into a skill that serves a reviewer instead of replacing them |
| scoutqa-test | awesome-copilot | Hard dependency on the third-party ScoutQA CLI | it dropped the CLI dependency |
| spring-boot-testing, java-junit | awesome-copilot | Java — outside the declared technology scope | the scope changed (a human decision, not a scouting one) |
| breakdown-test | awesome-copilot | Overlaps `dev-lead` Stage 2 decomposition and `backlog-manager` task creation | never, while the harness owns planning |
| playwright-explore-website, playwright-automation-fill-in-form | awesome-copilot | Subsumed by the vendored `webapp-testing` | `webapp-testing` were dropped |
| csharp-xunit / nunit / mstest / tunit | awesome-copilot | Four skills of framework depth; `csharp-testing` already auto-detects the framework | a framework proved to need depth `csharp-testing` cannot carry |
| *instructions* / *prompts* (any) | awesome-copilot | The plugin manifest has no key for them — they would ship as inert files | the plugin schema gained one |

## Keeping it honest

Re-derive rather than trust this file: the skills on disk and the agents' routing are the truth,
and a matrix that has drifted is worse than none. When you close a gap, move the cell and name the
skill that closed it; when you decide a cell is `n/a`, write the reason in the cell.

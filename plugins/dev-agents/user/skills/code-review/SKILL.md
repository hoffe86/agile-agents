---
name: code-review
description: Perform comprehensive code reviews across architecture, clean code, security, and test quality dimensions. Produces a structured markdown report with severity-rated findings, each classified as agent-automatable or requiring human decision. USE FOR any request to review code, audit a codebase, check for security issues, analyze architecture, find code smells, assess test coverage, or produce a quality report. Also use when the user asks to "review", "audit", "assess", "analyze quality", "check security", "find issues", or "code health check" for any project or repository.
applies_to: all
---

# Code Review Skill

Perform deep, multi-dimensional code reviews that produce actionable, classified reports. The review runs 4 parallel analysis streams, synthesizes findings into a single ranked report, and classifies every item by who should fix it.

## When to Use

- User asks to review, audit, or assess a codebase or project
- User asks about code quality, security posture, architecture health, or test coverage
- User wants a quality gate report before a release or PR
- User says "find issues", "code smells", "tech debt", or "what should we fix"

## Review Process

### Phase 1: Understand the Codebase

Before launching reviews, orient yourself:

1. Read any project-level copilot instructions (`.github/copilot-instructions.md`, `CLAUDE.md`, etc.)
2. Identify the tech stack, framework, and language conventions
3. Map the project structure — source layout, test layout, config files, CI/CD
4. Identify the key architectural patterns (DI framework, layering, API style)

This context is critical — pass it to every review agent so they understand what "correct" looks like for this specific project.

### Phase 2: Launch 4 Parallel Review Agents

Launch all 4 as **background explore agents simultaneously**. Each agent should receive:
- The project root path
- Tech stack summary from Phase 1
- Specific files and areas to focus on
- The exact checklist for their dimension (see `references/review-checklists.md`)

#### Agent 1: Architecture & Design

Focus areas:
- SOLID principle violations (especially SRP and DIP)
- Layer boundary violations (check .csproj / package.json / go.mod references)
- God classes and service locator anti-patterns
- DI registration issues (duplicates, lifetime mismatches, sync-over-async)
- Configuration patterns (options pattern, hardcoded values)
- Async/await correctness (sync-over-async, fire-and-forget, missing cancellation)
- Error handling consistency (global vs per-controller, exception swallowing)
- Circular dependencies

#### Agent 2: Security

Focus areas:
- Authentication & authorization gaps (unprotected endpoints, weak JWT config, permissive fallback policies)
- Input validation (DTOs, prompt injection, URL encoding, SQL injection)
- Secrets management (hardcoded secrets, Docker build args, pipeline variables, logged tokens)
- CORS configuration (overly permissive origins)
- HTTP security headers (HSTS, X-Content-Type-Options, X-Frame-Options, CSP)
- Logging security (tokens in logs, PII exposure, HttpLoggingFields)
- Dependency vulnerabilities (outdated packages, suppressed warnings)
- Rate limiting and DoS protection (missing limits, wrong paths, no timeouts)

#### Agent 3: Clean Code & Quality

Focus areas:
- Dead code, unused references, stale documentation
- Naming convention consistency
- Method complexity (>30 lines, deep nesting)
- Code duplication across modules
- Testability issues (static calls, hidden dependencies, large constructors)
- Resource management (IDisposable, Channel completion, HttpClient)
- Documentation accuracy (README, XML docs, instruction files vs actual code)
- TODO/HACK/FIXME debt

#### Agent 4: Test Quality

Focus areas:
- Coverage gaps — list source classes with no test counterpart
- Test quality — AAA pattern, naming conventions, assertion density
- Mock quality — over-mocking, fragile setup, reflection-based testing
- Missing edge cases for critical paths (error handling, null inputs, auth failures)
- Test isolation — shared state, ordering dependencies, integration tests mixed with units
- Duplicate tests across test projects

### Phase 3: Synthesize the Report

After all 4 agents complete, synthesize findings into a single markdown report. Read `references/report-template.md` for the exact output format.

#### Classification Rules

Every finding gets two labels:

**Severity** (based on impact and exploitability):
- 🔴 **Critical** — Security vulnerability, data loss risk, or production-breaking bug
- 🟠 **High** — Significant architectural flaw, correctness issue, or security weakness
- 🟡 **Medium** — Code quality issue, maintainability concern, or minor security gap
- 🟢 **Low** — Style, documentation, naming, or minor cleanup

**Owner** (who should fix it):
- 🤖 **Agent** — Can be fixed autonomously by Copilot. The fix is mechanical, well-scoped, and doesn't require design decisions. Examples: removing a log parameter, adding `.RequireAuthorization()`, deduplicating a DI registration, fixing a typo.
- 👤 **User** — Requires human judgment: design decisions, team alignment, access to external systems, capacity planning, or choosing between multiple valid approaches. Examples: CORS origin allowlists, rate limit thresholds, class decomposition boundaries, startup architecture changes.

**Classification heuristics:**
- If the fix touches only 1-3 files with a clear before/after → 🤖 Agent
- If the fix requires choosing between approaches → 👤 User
- If the fix impacts multiple teams or shared libraries → 👤 User
- If the fix needs external system access (ADO, Key Vault, ACR) → 👤 User
- Security fixes that are purely code changes → 🤖 Agent
- Security fixes that need secret rotation or infra changes → 👤 User

#### Finding Format

Each finding must include:
- **ID**: Category prefix + number (e.g., SEC-01, ARCH-03, CODE-07, TEST-02)
- **Title**: Short description
- **Severity**: 🔴/🟠/🟡/🟢
- **Category**: Dimension — Sub-category (e.g., "Security — Logging")
- **Files**: Specific file paths with line numbers
- **Issue**: What's wrong and why it matters
- **Fix**: Concrete remediation steps
- **Owner**: 🤖 Agent or 👤 User (with reason if User)

### Phase 4: Build the Action Plan

After the findings table, produce a **Prioritized Action Plan** with phases:

1. **Security Quick Wins** — All 🤖 Agent items from Critical + High security findings
2. **Architecture Quick Wins** — All 🤖 Agent items from High architecture findings
3. **Code Quality** — Remaining 🤖 Agent items
4. **Requires User Decision** — All 👤 User items, grouped by decision needed

Each phase is a table with columns: ID, Action, Effort (S/M/L).

### Phase 5: Summary Statistics

End with two summary tables:

**By category and severity:**
| Category | 🔴 Critical | 🟠 High | 🟡 Medium | 🟢 Low | Total |

**By owner:**
| Owner | Count |

### Phase 6: Save and Track

1. Save the report to the project's `docs/` folder (create if needed)
2. Create SQL todos for all 🤖 Agent items so they can be executed later
3. Present the plan summary to the user

## Adapting to Tech Stacks

The review checklists in `references/review-checklists.md` are organized by concern, not by language. Adapt the specific checks to the project's stack:

- **.NET**: Check DI registrations, async patterns, `IOptions<T>`, middleware pipeline order, EF Core usage
- **Node.js/TypeScript**: Check dependency injection patterns, promise handling, Express middleware, package vulnerabilities
- **Python**: Check import hygiene, type hints, exception handling, requirements pinning
- **Go**: Check error handling patterns, goroutine leaks, context propagation, interface compliance

## Tips for High-Quality Reviews

- Always read the actual source code, not just file names. Explore agents should `view` key files.
- Focus review agents on the most architecturally important files first (adapters, factories, middleware, DI setup, controllers/handlers)
- Cross-reference findings between agents — a security finding may also be an architecture issue
- Don't flag style issues that are consistent with the project's `.editorconfig` or established conventions
- If the project has custom instructions, respect those conventions even if they differ from general best practices
- Verify findings are real — if an agent reports "unused dependency", confirm it's actually unused
- Distinguish between "definitely wrong" and "could be improved" in severity ratings

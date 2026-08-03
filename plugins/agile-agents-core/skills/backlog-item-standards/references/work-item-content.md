# Work-item content standards

Tracker-agnostic. Defines the body structure, writing rules, BDD format, and the
Definition of Ready gate for any backlog item.

## Structure by type

**Product Backlog Item / Feature / Epic:**

```markdown
## Goal
{One paragraph stating the purpose}

## Description
{Context and background}

### Scope
- {Bullet list of what's in scope}

### Out of Scope
- {What is explicitly excluded, to prevent scope creep}

## Key Objectives
- {Measurable, actionable objectives}

## Success Metrics
- {Measurable outcome that signals the work delivered value — e.g. "p95 latency < 2s", "20% fewer support tickets"}

## External Dependencies
- {Services, teams, or systems required}

## Acceptance Criteria
- {Testable conditions for completion}
```

Add these **level-specific** elements when they apply:

- **Epic** — lead with a one-line **Business Goal**; keep `## Success Metrics` focused on outcome / business KPIs.
- **Feature** — include a **User Impact** statement (who benefits and how) and a short **Technical Approach** paragraph when the implementation direction is known.
- **PBI / Story** — `## Success Metrics` is optional; omit when value is already obvious from the Goal.

**Issue:**

```markdown
## Description
{Problem statement and context}

### Investigation Timeline
1. {Chronological events}

### Root Cause
{Analysis and findings}

### Impact
- {Who/what is affected}

## Acceptance Criteria
- {Conditions for resolution}
```

For a **reproducible bug**, add these elements (they make the Issue actionable):

- **Repro Steps** — numbered steps to reproduce
- **Expected Behavior** vs **Actual Behavior**
- **Environment** — OS / browser / version / build

## Writing rules

- **Title**: action-oriented and verb-first where possible; concise and specific so the deliverable is clear from the title alone. Avoid vague verbs ("improve", "update", "fix") without a concrete qualifier.
- **Clarity**: clear, direct language. No jargon without explanation.
- **Consistency**: Description, Key Objectives, and Acceptance Criteria must align — every objective maps to at least one AC, and vice versa.
- **Completeness**: each AC must be testable and verifiable.
- **Acceptance Criteria depth**: target 5–10 focused, binary criteria per item. Cover these categories when applicable: functional behaviour (core capability), edge cases (boundaries, error states, empty inputs), performance (latency / throughput thresholds), and observability (logging / metrics / alerting).
- **Evidence source**: when a requirement rests on a team hypothesis rather than user research, analytics, or stakeholder input, label it explicitly as an *unvalidated assumption* so reviewers understand the confidence level.
- **No user story format**: do not use "As a …, I want …" phrasing.
- **Markdown formatting**: bold for emphasis, bullet lists for enumerables, numbered lists for sequences.
- **Open Points**: when parts of the Definition of Ready are not yet fulfilled, add a separate `## Open Points` section listing the gaps.

## BDD / Gherkin scenarios

When a work item includes or warrants behavioural specifications, generate Gherkin
scenarios and store them in the **dedicated BDD field**
(`GravityScrum.GherkinBDDScenarios` on ADO), **not** in Acceptance Criteria.

**When to include**

- If the user explicitly requests BDD or Gherkin scenarios, generate them.
- If the user does **not** mention BDD, **ask** whether they want scenarios included before generating them. Do not silently skip or silently include them.

**Scenario sources** — read from whichever is available:

- **Tracker work items**: parse existing Gherkin from the BDD field.
- **Local markdown drafts**: read from `docs/` draft files in the workspace.
- If neither contains Gherkin, draft new scenarios from the acceptance criteria and implementation details.

**Output format**

- Standard Gherkin syntax: `Feature`, `Background`, `Scenario`, `Given`, `When`, `Then`, `And`.
- Group under **Positive Scenarios** and **Negative Scenarios** subheadings.
- Keep each scenario concise — aim for 3 lines (Given/When/Then).
- Use a `Background` block for shared preconditions.
- Output as markdown with fenced `gherkin` code blocks.

**Writing rules**

- Each scenario must be independently understandable.
- Use concrete values and tool / method names (e.g. `get_table_schema`, `execute_query`) rather than abstract descriptions.
- Negative scenarios cover bypass / circumvention attempts, not just invalid input.
- Positive scenarios validate the full happy-path chain.
- Do not invent scenarios that are not grounded in the provided acceptance criteria, implementation details, or user instructions.

## Definition of Ready checklist

The **structural gate** — flag any of these that are missing in an
`## Open Points` section:

- [ ] Clear title that summarises the work
- [ ] Goal / description explains the *why*
- [ ] Scope is defined (what's in and out)
- [ ] Acceptance criteria are testable
- [ ] Dependencies are identified
- [ ] Parent link is set
- [ ] Area Path is assigned
- [ ] Tags are set (e.g. Prototype version)

Definition of Ready answers *"can we start?"*; INVEST (see the agent's *Review
Criteria*) answers *"is it well-formed?"*. Both are checked during Review — DoR
drives `## Open Points`, INVEST drives the quality column in the comparison table.

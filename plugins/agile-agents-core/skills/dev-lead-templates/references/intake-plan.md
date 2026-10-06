# Intake and planning recipes

Read only the section required by the current stage. `dev-lead` owns stage
transitions, delegates, approval decisions, stop conditions and retry budgets.
These recipes prepare its inputs and records; they do not authorise advancement.

## Stage 0

### Read the input and capture the requirement

| Input kind | What you were handed | Preparation |
|---|---|---|
| Requirement text or tracker item | a statement of the outcome | capture the outcome and criteria |
| Requirements file (`docs/…/<name>.md`) | the same, living in the repo | read the source, then capture it |
| Plan file (a planning-mode `plan.md`, typically `~/.copilot/session-state/<session-id>/plan.md`) | an outcome and a decomposition someone already reasoned through | retain the decomposition for reconciliation and derive candidate criteria from its claimed outcomes |

Recognise a plan file by its **content, not its filename**: it states *how* —
ordered steps, files to touch, an approach — where a requirement states *what*.
Its path must be handed to you: it lives in another session's state folder.
Read the actual file with `read`; a prose summary cannot supply its steps.

Record:

- **Observable outcome:** one sentence — the Definition of Done.
- **Requirement acceptance criteria:** verbatim, numbered; this is the record
  Stage 9 compares with delivery, not a checklist reverse-engineered from tasks.
- **Explicitly out of scope:** protects against drift.
- **Load-bearing ambiguities:** acceptance criteria, deployment target, data
  shape, security posture and performance budget change what gets built. Target
  framework and error semantics are usually already answered by the profile and
  repo. Read `tech_stack.*`, code and documentation first; label the calls you
  can settle and carry them to the plan.
- **Parent work-item id:** the prepared item the planned child tasks link under.

Persist the criteria before delegating requirement work:

```sql
CREATE TABLE IF NOT EXISTS requirement_acs (
  ac_id TEXT PRIMARY KEY, text TEXT, covered_by TEXT, evidence TEXT,
  status TEXT DEFAULT 'uncovered');   -- uncovered | covered | out-of-scope
INSERT INTO requirement_acs (ac_id, text) VALUES ('ac-1', '<verbatim>'), ('ac-2', '<verbatim>');
```

For a source with no stated criteria (including a plan that states steps), draft
numbered candidates from the outcomes it describes and mark each **derived**.
Use the existing Stage 4 **Acceptance criteria I derived** field for confirmation;
store what the human confirms or corrects, thereafter treating it as verbatim.
Never present an inferred criterion as source text. An unconfirmed list would
measure your own reading rather than what the human asked for.

### Prepare specialist context

Prepend the relevant profile subset, not the entire profile:

- Coding: `tech_stack.*` + `documentation.*` +
  `compliance_security.allowed_oss_licenses`.
- Infrastructure: `infrastructure.*` + `cicd.*` + `compliance_security.*` +
  `operational.slo`.
- Backlog-manager: `backlog.*` + `team_communication.code_language`.

### Run-start record

Use UUIDv7 for `run_id`; pass it explicitly on every script call, never through
an exported shell variable (each tool call starts a fresh process). Events land
in `.copilot-runs/<run-id>/events.jsonl`. Emit `run_start` via the loaded
`run-event-log` skill's `scripts/emit-event.sh` / `.ps1`, with `agent=dev-lead`,
`phase=intake`, and `payload.requirement_summary` plus boolean
`payload.profile_loaded`. Persist its UTC timestamp as `run_started_at` alongside
`run_id` in the session DB for all later cost collection, including resume.

Read `solution-profile.yaml: cost_envelope`; record `max_aiu_per_run`,
`max_aiu_per_phase`, `max_tokens_per_run` and per-phase overrides in the budget
tracker. The loaded `cost-budget` skill supplies commands and cap resolution;
the supervisor supplies the missing-envelope decision.

## Stage 1

### Research preparation and reporting

The prepared concept uses `documentation.framework`; binding decisions come
from accepted ADRs where used, otherwise design docs / work items. Verify
relevant codebase, APIs and existing patterns against these sources, not a newly
invented design.

**Verification means technical research, not only reading this repo.** For an
API shape, service limit, version behaviour or capability, establish the fact
with available `context7/*`, `microsoft-docs/*`, `web`, browser or vendor MCP
tooling. `read-repo-context` §9 gives the source order. The lightweight path owes
the same verified-fact / assumption accounting as delegated research: "small
change" describes the diff, not the certainty.

For delegated research, send the requirement, in-scope / out-of-scope, intake
constraints and binding decision ids / references. Collect a verification sketch
in the declared framework, follow-on implementation tasks, facts verified with
sources, assumptions with impacts, and decision gaps. A material decision can be
captured in the sketch's decision section (arc42 §9 by default); lack of an ADR
alone is not a gap in a project that does not use them.

For data requirements, Research establishes whether the source exists, may be
used, is fit for purpose, its contract and physical landing place, and what must
be settled by analysis before building. It does **not** analyse the data:
"is the signal there?" belongs in the planned feasibility work, not an
optimistic research conclusion.

Carry assumptions forward to Stage 2, Stage 4 and the final report. Relay
`Key tradeoffs`, `Open questions / risks`, `Decision gaps`, and
`Data questions to answer before building` in substance, plus your own calls;
do not digest manageable risks into silence. The human may weigh them differently.
Record the **approach summary** for the comment on the parent work item.

Spend the effort understanding the requirement here. A fact checked now costs a
paragraph; the same check after implementation costs tests and corrective work.
Right-sizing reduces artifacts and ceremony, not understanding.

## Stage 2

### Task preparation

A well-formed task is small enough to implement and review on its own, large
enough to deliver observable value, and carries:

- **Clear title:** imperative, scoped.
- **Acceptance criteria:** testable bullets (Gherkin when
  `tech_stack.test_discipline == bdd`) defining that task's completion.
- **Approach note:** self-contained spec naming files / components, chosen
  pattern with binding decision reference, and that task's out-of-scope work.

Plan on verified ground: check the Stage 1 verified list before writing an
approach instruction a worker will follow literally. Where it still rests on an
assumption, write **"assumes `<fact>`; unverified"** in the note itself. Check a
cheap fact now rather than phrase a guess as settled.

Sequence around unknowns. A single check that settles the highest uncertainty
belongs first, with what it resolves stated. When only building can settle it,
make that task small and provisional; flag dependent tasks at Stage 4.

Apply the supervisor's decomposition judgement:

- Slice vertically, not by layer: "Add endpoint X end-to-end", not separate DTO,
  repository and controller tasks that cannot be reviewed or reverted independently.
- Riskiest task first; keep a forced low-risk predecessor minimal.
- Fewest tasks that slice cleanly: two tasks that always ship together and touch
  the same files are one. Task count is not a progress metric.
- Ask of each task: does DoD fail if it is dropped? Otherwise propose Follow-ups.

### Data decomposition

Turn `Data findings` / `Data questions to answer before building` into explicit
tasks, not hidden parts of a feature:

- A feasibility question ("signal present?", "labels reliable?", "source complete
  enough?") delivers an **answer**, possibly no. Explain at Stage 4 which dependent
  tasks die if it returns ❌.
- Never bundle a model task and its feasibility check: a negative answer must not
  arrive entangled with half-built code.
- Separate transformation logic (`coding`), its storage/warehouse/orchestration
  (`infrastructure`), and semantics/quality judgement/modelling (`data-scientist`).
  Join those tasks with the dataset contract (`data-engineering-practices` §1).
- Producing-task ACs include dataset grain, keys, schema and freshness so consumers
  do not start from a guess.

### Reconciliation and SQL cache

Set each `requirement_acs.covered_by` to its delivering task id(s). Record the
reason for an `out-of-scope` row for Stage 4. Reconcile every architect follow-on
task as present, merged (name the task), or dropped (one-line reason); on the
lightweight path there is no architect list.

For a supplied plan, account for **every step** as carried, merged or dropped
with its task / reason. Splitting coarse steps, merging inseparable ones and
risk-first reordering are legitimate edits; report each at Stage 4 instead of
silently replacing the source decomposition.

Record applicability per task: coding is inapplicable for pure design or IaC-only
work (infrastructure owns IaC); testing is inapplicable for pure docs or a config
rename with no behavioural impact. IaC tests belong to infrastructure, not an
application-testing delegation. Review is always applicable.

Mirror the task list into `todos` + `todo_deps`, with descriptive kebab-case ids
and a dependency row for every ordering constraint:

```sql
INSERT INTO todos (id, title, description) VALUES
  ('task-<slug>', 'Implement <task title>', 'ACs + approach note + tracker child id once created'),
  ...;
INSERT INTO todo_deps VALUES
  ('task-b', 'task-a'),
  ...;
```

Track status as `pending` → `in_progress` → `done` / `blocked`. The SQL todos
and local handover files are ephemeral, rebuildable caches; tracker child items
remain the source of truth and win on conflict.

## Stage 3

### Tracker creation payload

Send `backlog-manager` the **parent work-item id**, task list (title + ACs +
approach note for each), Stage 1 approach summary and propagated `backlog.*` +
`team_communication.code_language`.

Each child links to the parent, starts in the tracker's own entry state and is
tagged `pending-approval`. The overall approach is a comment on the parent;
each child holds its own approach note. Creation does not progress state,
estimate or prioritise.

Record returned child ids in the todo descriptions. Validate the returned
`TASKS PLANNED` against the shared hand-off contract, not a second schema here.
For inline planning, prepare the same task list for the plan-approval rendering.

## Tracker mechanics

Read this section only when the supervisor needs a tracker transition or
provisional-task cleanup; it is not a mandatory cookbook preload.

Send `backlog-manager` **"set task <tracker id> to `<neutral state>`"**, plus one
factual sentence of context. It translates via `backlog.task_states`, otherwise
discovers the tracker's vocabulary, otherwise posts a status comment. It owns
the API call. Do not hardcode `Active`, `Resolved`, `Closed`, `Doing`, `open` or
`closed`: those belong to one tracker's process, not the harness.

`implemented` often has no matching state; a comment instead of a transition is
the designed outcome, not grounds to claim `done`. Record any unapplied
transition for the final report so the human can correct the board in one pass.

For provisional-tag removal, plan revisions or cancellation cleanup, send only
the affected child ids created in this run and the human's decision. Capture
any ids the tracker could not clean up. The supervisor, not this recipe, decides
when those operations are authorised and how a failure affects the run.

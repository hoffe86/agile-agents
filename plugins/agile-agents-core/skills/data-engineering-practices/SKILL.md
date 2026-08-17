---
name: data-engineering-practices
description: >-
  The craft bar for moving and shaping data — data contracts, schema evolution,
  idempotent and replayable loads, partitioning, backfills, quality gates that
  fail loudly, lineage, orchestration hygiene, and PII handling inside
  pipelines. Technology-neutral: names no warehouse, no orchestrator and no
  transformation framework, and applies equally to SQL, notebooks, dataframe
  code or a managed pipeline service. Loaded by `coding` when the task is
  transformation logic, by `infrastructure` when it is the platform or
  orchestration that runs it, and by `data-scientist` when consuming or
  producing a dataset others depend on. USE FOR: building or changing an
  ingestion, transformation or export pipeline; designing a table or dataset
  others will consume; adding a data quality check; planning a backfill or a
  schema change. DO NOT USE FOR: analysing data or building models (that is
  `data-science-practices`), or provisioning cloud resources generally (that is
  `iac-best-practices`).
applies_to: all
---

# Data-engineering practices

The bar for work that **other people's work depends on**. A pipeline's failures are
asymmetric: a job that crashes gets fixed within the hour, while a job that quietly writes
wrong data corrupts every downstream consumer, every dashboard built on it, and every model
trained from it — and is usually discovered weeks later by someone who cannot explain why a
number moved.

So the governing principle here is **fail loudly, never silently**. Everything below is a
variation on it.

`engineering-standards` and `development-practices` cover the code. `iac-best-practices`
covers provisioning the platform. This skill covers the data.

## 1. The contract comes before the pipeline

A dataset other teams read is an **interface**, and changing it breaks people who are not in
the room. Before building, establish and record:

- **Schema** — fields, types, units, nullability, and what each field actually *means* (not
  just its name).
- **Grain** — what exactly one row represents. Ambiguous grain is the most common cause of
  silently double-counted metrics.
- **Keys** — the natural key, the uniqueness guarantee, and whether it truly holds.
- **Freshness and latency** — how current the data is expected to be, and by when.
- **Volume expectations** — so an anomalous run is detectable as anomalous.
- **Ownership** — who to ask when it looks wrong.

When a consumer exists, changing this is a coordinated change, not a unilateral one.

## 2. Schema evolution is a compatibility question

- **Additive changes** (a new nullable column) are usually safe. **Removals, renames, type
  narrowing and semantic redefinition are breaking** — even when the pipeline still runs.
- **A silent semantic change is the most dangerous edit in data engineering:** the column name
  and type stay identical while the meaning shifts (currency, timezone, inclusion rule). No
  schema check catches it. Rename the field or version the dataset instead.
- Version the dataset or the contract when a breaking change is genuinely needed, and give
  consumers a migration window rather than a surprise.
- Say explicitly what happens to an unexpected new field: ignored, passed through, or rejected.

## 3. Idempotency and replay

Assume every job will be re-run — after a failure, a late-arriving file, or a backfill.

- **Re-running a load for the same window must produce the same result, not duplicates.** Prefer
  a deterministic overwrite of a partition, or a merge on a stable key, over blind append.
- Make the **processing window explicit** (a parameter), never implicit in "now" — a job whose
  behaviour depends on when it happened cannot be replayed.
- Handle **late-arriving and out-of-order data** deliberately: define how late is accepted, and
  what happens to data arriving after the window closed.
- Prefer recomputable derived state. If a value can only be produced once, its loss is
  permanent — say so, and treat it as a risk.

## 4. Partitioning and layout

- Partition on the column consumers actually filter by — usually an event or business date,
  not the load timestamp. Confusing those two is a common and expensive mistake, because it
  makes correct reprocessing impossible.
- Keep partitions large enough to be efficient and small enough to reprocess in isolation.
- Prefer a stable, documented layout; changing it is a breaking change for anything reading
  the files directly.

## 5. Quality gates that stop bad data

Checks that log a warning nobody reads are theatre. A quality gate must be able to **stop the
data**, and someone must be told:

- **Structural** — schema matches, required fields present, types as declared.
- **Volume** — row counts within expected bounds; an empty load and a 10× load are both
  suspicious and neither should pass silently.
- **Uniqueness and referential integrity** — the key is actually unique; foreign keys resolve.
- **Domain** — ranges, allowed values, and the impossibilities specific to this data.
- **Freshness** — the newest record is as recent as the contract promises.

For each check, decide deliberately: **fail the run, quarantine the bad rows, or pass with an
alert** — and record which, because "we didn't decide" defaults to the worst option, which is
passing silently. Quarantined data needs a route back; a quarantine nobody drains is a
deletion with extra steps.

## 6. Lineage and observability

- It must be answerable, without archaeology: **where did this number come from, through which
  transformations, from which source, at which version?**
- Log per run: window processed, row counts in/out, rejects, duration, and the code version.
- A row count that only ever goes up tells you nothing. Compare against expectation.
- Emit failures where humans will see them, with enough context to act — a silent retry that
  eventually gives up at 3am is an outage nobody was told about.

## 7. Orchestration hygiene

- **Dependencies are explicit.** A job that works because it happens to run after another is a
  latent failure waiting for a schedule change.
- Retries with backoff for transient failures — but only where the step is idempotent (§3).
  Retrying a non-idempotent load duplicates data.
- Set timeouts. A hung job holding a lock is worse than a failed one.
- Failure must be **loud and attributable**: which run, which window, which step.
- Backfills run through the same code path as regular loads. A separate backfill script drifts
  from the pipeline it is meant to reproduce, and then reproduces something else.

## 8. PII and access inside pipelines

- Personal data is minimised at the **earliest** point it can be — do not carry a column
  through five layers to drop it at the end, because every intermediate table becomes a copy
  to secure, audit and eventually forget about.
- Honour `solution-profile.yaml: data_science.data_privacy.pii_policy` and
  `compliance_security.*`; where the pipeline crosses a jurisdiction or tenancy boundary, that
  is an architecture decision, not an implementation detail — escalate it.
- Intermediate and debug outputs are real data with real obligations. A temporary table with
  raw personal data is a breach waiting for someone to forget it exists.
- Deletion and retention must be *implementable*: if a subject's data cannot be found and
  removed across every layer, say so before building, not after the request arrives.

## 9. Testing a pipeline

Pipeline tests are ordinary tests (`testing-practices` applies) with three additions worth
calling out:

- **Test the transformation logic on fixtures**, not on production data — small, synthetic,
  and including the nasty cases: nulls, duplicates, late arrivals, an empty input, a
  malformed row.
- **Test the quality gates themselves.** A check that never fires has never been shown to
  work; feed it bad data and assert it stops the run.
- **Assert on the contract** — grain, uniqueness and schema — so a change that breaks a
  consumer fails here rather than downstream.

Never use real personal data as a test fixture. Synthesise it.

## 10. Who owns what

- **`coding`** — transformation logic, quality-check implementation, pipeline application code
  and its tests.
- **`infrastructure`** — the platform, storage, compute and orchestration that runs it, plus
  their IaC tests.
- **`data-scientist`** — the semantics: what the fields mean, whether the data supports the
  question, and whether quality is fit for the intended analysis.

When a task needs two of these, it is two tasks. The contract in §1 is the hand-off between
them — write it down, because it is what the next agent works from.

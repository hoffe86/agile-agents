---
name: acceptance-grading
description: >-
  How to grade produced work against acceptance criteria — the judgement contract for
  an evaluation harness. Covers verifying rather than inferring, the sandbox exception
  that lets a grader execute verification commands without ever repairing what it
  grades, treating skills as the owner of house conventions (and reporting criterion vs
  skill drift as an eval defect rather than an agent failure), refusing to invent
  requirements stricter than the criterion states, and the PASS / FAIL / UNVERIFIED +
  VERDICT output contract. USE FOR grading an agent's output against acceptance
  criteria, scoring an eval task, or any "did this work meet the stated bar" judgement.
  DO NOT USE FOR reviewing a diff destined for a real repository — that is the review
  agents and `reviewer-read-only-rules`.
applies_to: all
---

# Acceptance grading

You are deciding whether produced work meets a stated bar. Your output is a verdict and
the evidence behind it — never a repair.

Load **`reviewer-read-only-rules`** alongside this skill. That contract still holds, with
exactly one documented exception (§2).

## 1. Verify — do not infer

**A criterion is decided by evidence you gathered.** Not by what the source *looks like*
it would do, and not by what a competent implementation *would* contain.

| Criterion is about… | Decide it by |
|---|---|
| behaviour — builds, tests pass, lints clean, renders, validates | **running it** and reading the output |
| a file's presence, name, or content | reading the filesystem |
| a convention — template shape, required sections, naming, commit format | the **skill that owns it** (§3) |
| quality of reasoning — is the trade-off explained, is the model coherent | your own judgement over the artifacts |

If you were handed an inlined listing of files, treat it as an **index, not the
workspace**. It is capped for size. Never conclude something is missing because it is not
in the listing — look.

## 2. The sandbox exception, and the line it does not cross

An eval workspace is a disposable copy. Running the project's own verification commands
there — `dotnet build`, `dotnet test`, `pytest`, `bicep build`, `kubectl kustomize`,
`terraform validate`, a linter — is **allowed and expected**, even though those commands
write build output. That is the only way "it builds" can be established, and
`reviewer-read-only-rules`' ban on workspace-mutating builds exists for a real repository,
not for a throwaway grading sandbox.

**What you must never do is change the thing you are grading.** No editing source, no
fixing a failing test, no adding a missing file, no installing a dependency to make a
build succeed, no regenerating a snapshot. A grader that repairs the work and then passes
it has destroyed the measurement while producing a plausible number — the most damaging
failure available to an evaluation, because nothing errors and the score looks fine.

If a build fails for an environmental reason (no toolchain, no network), that is
`UNVERIFIED` (§5). It is not licence to fix the environment and try again.

## 3. Conventions are owned by skills, not by checklists

Where a criterion refers to a house convention — an ADR template, arc42 structure,
conventional commits, a review rubric — **load the skill that defines it and grade against
that.** A checklist that restates a convention has forked it, and forks drift.

**When the criterion's wording and the skill disagree, the skill wins**, and you say so in
your reason. That disagreement is a defect in the *eval*, not in the work: report it so it
gets fixed, rather than charging it to the agent. This is not hypothetical — an acceptance
criterion once enumerated "the six MADR sections" as a list that upstream MADR does not
use, and failed work that had correctly followed the repo's own ADR skill.

So, concretely, when a criterion names a convention and also asserts *how* that convention
looks — a required section, a field's placement, an exact wording:

- grade the **substance** the criterion asks for (was the fact recorded at all?);
- grade the **form** against the skill that owns it, never against the criterion's
  restatement;
- if the work matches the skill but not the restatement, that is a **PASS**, with the
  drift named in your reason so the criterion gets repaired.

This does not license grading leniently (§4). It is narrower: the criterion decides *what
must be true*, the skill decides *what that looks like*. A criterion cannot redefine a
convention it does not own.

## 4. Grade the criterion as written

**Do not invent a stricter requirement than the criterion states.** If it asks that the
build succeed with warnings-as-errors, a build you ran with `-warnaserror` reporting zero
warnings **passes** — do not additionally demand a particular project property unless the
criterion names one. Substituting a static proxy for a behavioural fact is how a correct
solution that took a different route gets marked wrong.

This governs *scope*: never add requirements the criterion did not ask for. It does not
make the criterion's wording authoritative over a convention a skill owns — that is §3.

Equally, give no credit for intent: TODOs, comments promising work, and empty stubs are
not implementations.

## 5. Absence of evidence is not evidence of absence

If you genuinely could not check something — toolchain unavailable, command failed for
environmental reasons, artifact outside the sandbox — mark it `UNVERIFIED` and say what
stopped you. **Never convert "I could not look" into "it was not done".**

`UNVERIFIED` is not a pass and not a fail. Grade the remaining criteria and let it stand;
it is a signal that the harness, not the work, needs attention.

## 6. Output contract

List each criterion on its own line, then the verdict as the **very last line**:

```
1. PASS - <evidence, 15 words or fewer>
2. FAIL - <evidence>
3. UNVERIFIED - <what stopped you>

VERDICT: RESOLVED
```

- **RESOLVED** — every criterion passes.
- **PARTIAL** — at least one passes and nothing is catastrophically broken (no
  syntactically broken code that could not build).
- **FAILED** — no criterion passes, or the output is broken, empty, or missing.

State evidence, not impression: *"ran dotnet test, 2/2 passed"*, not *"tests look
correct"*. A reason that could have been written without opening the workspace is a sign
you inferred instead of verifying.

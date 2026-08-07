---
name: pr-description
description: Generate a high-signal pull-request description from a diff and the run's hand-off context. Produces a structured PR body with a one-line summary, the why, what changed (grouped by intent — feature / fix / refactor / chore / docs / test / ci / iac), risk and rollback notes, test evidence, breaking-change callouts, linked issues, and a reviewer-checklist. Loaded by dev-lead at PR-open time. Composes with conventional-commit (commit subject style) and read-repo-context (repo conventions, ADRs, solution-profile).
applies_to: all
---

# pr-description

Author a pull-request description that is **scannable in 30 seconds** and **complete enough to merge from**. Reviewers should not need to re-derive intent from the diff.

## When to invoke

- `dev-lead` is closing a Done run and needs a PR body.
- Any agent or human is opening a PR and wants a structured description rather than a raw bullet list.

## Inputs you read first

1. The accumulated **stage hand-offs** for this run (architect / coding / testing / infrastructure / review reports). The "WHY" comes from these — not from the diff.
2. The **diff** (`git --no-pager diff <base>..<head> --stat` for the file map, then targeted `--patch` reads for the largest hunks).
3. **Repo conventions** via `read-repo-context` — especially:
   - PR-template path — GitHub reads `.github/pull_request_template.md`; Azure DevOps reads `.azuredevops/pull_request_template.md`, `docs/pull_request_template.md`, or one at the repo root. If present, **conform to its structure** and add the sections below as additional content.
   - `CONTRIBUTING.md` PR rules.
   - Issue-tracker linkage convention (GitHub `Fixes #N` / `Closes #N`, ADO `AB#N`, Jira `PROJ-N`).
4. The **solution-profile** (if present) — to pick up the project's PR-description conventions and the issue tracker URL pattern.

## Output structure (default — overridden by the repo's PR template if one is present)

```markdown
## Summary

<One sentence — what this PR does, in plain language. No bullet list here.>

## Why

<2–4 sentences — the user-visible / business / operational reason. Reference the originating issue / requirement / ADR. If this PR is a follow-up to a larger run, name the parent.>

## What changed

Grouped by intent (omit empty groups):

- **Feature.** <short bullet per feature surface>
- **Fix.** <short bullet per fix — link the bug / issue>
- **Refactor.** <short bullet per refactor — name the pattern>
- **Docs.** <short bullet per doc surface updated>
- **Test.** <short bullet per test surface — coverage delta if known>
- **CI / IaC.** <short bullet per pipeline / infra change>
- **Chore.** <dependency bumps, formatting-only changes — keep this short>

## Risk and rollback

- **Blast radius:** <files / modules / services / users affected — be honest>
- **Rollback:** <how to revert; is a forward-fix required, or is `git revert` sufficient? Any data migration that prevents revert?>
- **Feature flag / config:** <if gated, name the flag and default state; if not, say "no flag — change is live on merge">

## Test evidence

- <command run, summarised result — e.g., `dotnet test` 412 passed, 0 failed>
- <coverage delta if reported by `pytest-coverage` / `dotnet test --collect:"XPlat Code Coverage"`>
- <manual / smoke verification steps performed, if any>

## Breaking changes

<None | Yes — describe the contract change, the migration path, and which downstream consumers were notified or coordinated. If a contract version bump applies, name the new version.>

## Linked items

- <Fixes #N / Closes #N / AB#N / PROJ-N — one per line>
- <ADR-NNN if this PR enacts a recently-accepted decision>

## Reviewer checklist

- [ ] Read **Summary** + **Why** — does the change match the stated intent?
- [ ] Spot-check **Risk and rollback** — is blast radius accurate?
- [ ] Confirm **Test evidence** is present and meaningful (not just "tests pass").
- [ ] Verify **Breaking changes** section is honest.
- [ ] If this PR introduces a new public surface, confirm docs are updated in the same PR.
```

## Tone and constraints

- **Honest, not promotional.** "Adds X" not "Massively improves Y". Reviewers distrust marketing tone in PR bodies.
- **Factual on test evidence.** Quote the actual test-runner output line, not "all green".
- **Link, don't paraphrase, ADRs and issues.** Names + IDs only; the linked source is canon.
- **Group by intent, not by file.** "Refactor: extracted policy resolver" is more useful than "src/Policy/Resolver.cs (changed)".
- **No emoji noise** unless the repo PR template uses them. One verdict / status emoji at the top is fine.
- **No "TODO: write description later".** If you cannot write a full section, write `_n/a — <brief reason>_` so reviewers know it was considered, not skipped.

## Hand-off

Return the rendered PR body as a fenced markdown block. The orchestrator (or human) is responsible for actually opening the PR — `gh pr create --body-file <file>` on GitHub, `az repos pr create --description "$(Get-Content <file> -Raw)"` on Azure DevOps, or the platform UI. Pick from `identity.repo_url`, not from the tracker: the code host and the board host are independent.

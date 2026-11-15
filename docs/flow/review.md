# Review and completion

## Independent review

`review-lead` triages the diff and dispatches specialist lenses in parallel:

| Lens | Runs |
|---|---|
| `code-reviewer` | Always |
| `security-reviewer` | Always, including documentation-only diffs, with secret scanning |
| `test-reviewer` | When tests or testable code change |
| `architecture-reviewer` | When boundaries or contracts change, or many files are touched |
| `infrastructure-reviewer` | When IaC, pipelines or Dockerfiles change |
| `data-reviewer` | When analysis, models or evaluation sets change |

Findings are merged into one severity-ranked report with stable ids, an owner per
finding and one verdict: ✅ Approve, 🔁 Request changes or ❌ Block.

Only the findings owned by each fixer are routed back, verbatim. Fixers account
for each id as fixed, disputed or not theirs. Review runs at most three
corrective rounds, and stops early when a round closes nothing. A ❌ Block gets
one corrective loop for the author to answer it, then the run stops for a human
decision regardless of the remaining round budget.

## Done

A run is Done only when every acceptance criterion is covered by a delivered task
**and** evidence, the build and tests are green, the verdict is ✅ Approve with no
open Critical or unaccepted Major findings, and trade-offs are reported. Task
status alone is not delivery evidence.

The final report states the outcome against the Definition of Done, consolidated
trade-offs, accepted risks, follow-ups and measured cost. Pull-request text is
prepared, but the pull request is opened only with your approval.

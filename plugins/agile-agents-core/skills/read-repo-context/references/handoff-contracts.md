# Hand-off contracts

The sole field definitions for the seven canonical hand-offs. Read only the
section for the block you are producing or receiving, plus **Corrective accounting**
when handling review findings. Sections end at the next level-two heading.
Keep field names, sentinel spelling and the stated applicability unchanged.
These schemas do not replace role-specific gates, review rubrics or retry policy.

## ARCHITECTURE DESIGN COMPLETE

Producer: `architect`. Research/design evidence, not permission to invent a decision.

```
ARCHITECTURE DESIGN COMPLETE
- Topic: <one-line>
- Deliverables: <the artifacts you produced and where they landed, resolved from `documentation.platform` + `location` (or `ai_documentation_dir`) — or, when the platform is not writable from the workspace, "content in this hand-off → publish to <platform> → <location>">
- Framework used: <what `documentation.framework` declared, or "arc42 + C4 — profile silent, defaulted">

- Recommendation: <chosen approach, one line>
- Key tradeoffs: <2-3 bullets>
- NFRs to honour: <bulleted list of concrete, measurable NFRs the implementer must meet — e.g. P95 latency < 200 ms, RTO ≤ 4 h, RPO ≤ 15 min, data residency = EU, throughput ≥ 100 RPS, availability SLO ≥ 99.9%, monthly cost band ≤ €X. Pulls from arc42 §10. "None additional" only if the requirement was already explicit.>
- Decisions honoured: <binding ADR ids the design respects; or the design-doc / work-item decisions it conforms to when the project does not use ADRs; or "none found / none applicable">
- Decision gaps (need a human decision before coding): <list — for each: decision needed · why it matters · candidate options · recommendation. "none" if every materially-shaping decision is already captured *somewhere* — an accepted ADR, the framework's decision section, or the work item.>
- Facts verified: <the load-bearing facts you checked rather than recalled — for each: fact · source · the version / region / date it applies to. E.g. "Container Apps supports scale-to-zero on the Consumption plan · Microsoft Learn · retrieved <date>". "none needed — design rests on no external fact" is a valid answer on a purely internal design, but it is a claim, not a default.>
- Assumptions (unverified): <every load-bearing fact you could NOT confirm — for each: assumption · why verification failed (no such doc, tooling unavailable and which cause, ambiguous source) · what breaks if it is wrong. "none" only when every load-bearing fact is in the list above. Never promote an assumption to a verified fact to empty this field.>
- Well-architected assessment (cloud designs): ✅ aligned / ⚠️ trade-offs called out per pillar / n/a — not cloud-hosted
- Data findings (when the change touches data, else "n/a — no data surface"): <for each dataset or source: does it exist · may we use it, under what agreement · fit for purpose (volume / history / freshness / quality / do the required labels exist) · contract (grain, keys, schema, existing consumers) · where it physically lands and any residency, retention or deletion obligation. **State blockers first** — a required source that does not exist, or personal data with no permitting policy, outranks every other finding in this hand-off.>
- Data questions to answer before building (else "none"): <feasibility questions that must be settled by analysis rather than by design — "is the signal present at all?", "are the labels reliable enough?". Each becomes a `data-scientist` task sequenced ahead of anything that depends on the answer.>
- Estimated monthly cost band (if cloud-hosted): <currency><low> – <currency><high>
- Open questions / risks: <list with owners>
- Findings addressed: <corrective rounds only — one line per id: "<id>: fixed in <deliverable/location>" | "<id>: disputed — <reason>" | "<id>: not mine — owned by <agent>". Omit on a first pass.>
- Recommended next step:
    → human (to settle any reported decision gaps — as ADRs only if the project uses them), then
    → infrastructure (to provision the topology)
    → coding (to scaffold the application)
    → review (to audit the design against existing code)
```

## IMPLEMENTATION COMPLETE

Producer: `coding`. Application code and its tests are one hand-off.

```
IMPLEMENTATION COMPLETE
- Files changed: <production files>
- Test files changed: <test files — "none" only when the change is genuinely untestable, with the reason>
- ADRs honoured: <list of ADR ids your change is constrained by, or "none found / none applicable">
- Docs updated: <list of README / docs/ / instruction-file paths touched, or "none — no existing docs reference the changed area" / "asked user — pending answer">
- Behavior added/modified: <bulleted list of observable behaviors, each with the test that asserts it: "<behaviour> → <test name>">
- Public surface added/changed: <new or changed public types, methods, HTTP routes, CLI flags, config keys, exported symbols — anything an external caller can see; "none" if internal-only>
- Internal-only changes: <refactors, private helpers, plumbing not visible to callers; "none" if everything is in the Public surface list>
- Build status: ✅ passes  /  ⚠️ warnings: <list>  /  ❌ failures: <list>
- Test run: ✅ <N>/<N> passing  /  ❌ <N> failing — <why, and why you stopped rather than weakening them>
- Coverage on touched files: <%> (was <%>)
- Existing tests modified: ⚠️ <none | one line each: what the old assertion claimed and why it was invalid>
- Startup verified: <✅ app starts — <how you checked> | n/a — change doesn't touch startup | ⚠️ couldn't determine — <reason>>
- Findings addressed: <corrective rounds only — one line per finding: "<id>: fixed in <file:line>" | "<id>: disputed — <reason>" | "<id>: not mine — owned by <agent>". Omit the field entirely on a first pass.>
- Unmet design constraint (if any): <only fill in if you could not deliver inside the architect's locked design without a new dependency, boundary, contract, or cloud resource — describe the gap so dev-lead can route back to architect>
- Open questions for review: <if any>
```

## INFRASTRUCTURE COMPLETE

Producer: `infrastructure`. IaC validation and IaC tests, not application build/test fields.

```
INFRASTRUCTURE COMPLETE
- Technology: <IaC tool / orchestrator / pipeline platform>
- Files changed: <list>
- ADRs honoured: <list of ADR ids constraining this change, or "none found / none applicable">
- Docs updated: <list of README / docs/ / runbook paths touched, or "none — no existing docs reference the changed area" / "asked user — pending answer">
- Scope: <subscription / project / resource group / cluster namespace / workflow>
- Plan / what-if summary: +<N> add, ~<N> change, -<N> destroy
- Verified modules used (with versions): <list, or "none — custom resources, reason: …">
- Validation: ✅ lint clean, ✅ plan clean / ⚠️ warnings: <list>
- Secrets touched: <list — all as references into the declared secrets store>
- Findings addressed: <corrective rounds only — one line per finding: "<id>: fixed in <file:line>" | "<id>: disputed — <reason>" | "<id>: not mine — owned by <agent>". Omit the field entirely on a first-pass implementation.>
- Open items for review: <if any>
- IaC tests authored / run: <count, framework, ✅ pass | ❌ fail | n/a>
- Behavior added/modified: <each observable infrastructure/pipeline behavior → IaC test name; n/a only with a reason no executable test applies>
- Existing tests modified: <none | one line per changed/deleted/newly-skipped test: old assertion and why it was invalid>
- Recommended next step: hand off to infrastructure-reviewer | review | deploy
```

## ANALYSIS COMPLETE

Producer: `data-scientist`. An answer plus evidence; negative and inconclusive
outcomes are completed work, not a request to manufacture a positive result.

```
ANALYSIS COMPLETE
- Question: <the question you actually answered, and the decision it informs>
- Outcome: ✅ supported — <one line> | ⚠️ inconclusive — <what is missing> | ❌ not supported — <why>
      (⚠️ and ❌ are legitimate completed outcomes, not failures. Do not retry to manufacture a ✅.)
- Files changed: <notebooks, analysis modules, evaluation sets, model artifacts, model card>
- Data used: <source, version / snapshot date, row count, and the profile field or approval that permits its use>
- Method: <approach, and why it is proportionate to the question>
- Baseline: <the trivial comparator> → <its score>
- Result: <metric(s) with uncertainty> vs baseline; state the metric and its averaging convention explicitly
- Split & leakage: <split rule, seed, and the leakage checks you ran — name them>
- Cohort breakdown: <performance across the populations this affects, or "n/a — affects no people" with the reason>
- Reproducibility: <seed, data version, environment, and the command that re-runs it>
- Dataset status (if you produced one): ai-generated | expert-reviewed | mixed
- Unmeasured risks: <risks with no detecting metric — never omit; write "none identified" only if you looked>
- Not verifiable from this diff: <anything a reviewer cannot check from what you committed — an external dashboard, a run in a tracker, a manual inspection — so `data-reviewer` reports it as a gap rather than assuming it was done. "nothing" is a valid answer.>
- Code verification: <n/a — no reusable code changed, with reason | build/test commands and results; each code behavior → test name; existing tests modified: none or old assertion and why it was invalid>
- Interface for `coding` (if a model ships): <inputs, outputs, failure modes, latency, and what to do when it abstains>
- Findings addressed: <corrective rounds only — one line per finding id. Omit on a first pass.>
- Open questions for review: <if any>
```

## REVIEW COMPLETE

Producer: `review-lead`. Append this block to the merged report; keep the full
specialist reports and the role's merging rubric.

```
REVIEW COMPLETE
- Verdict: ✅ Approve | 🔁 Request changes | ❌ Block
- Specialists invoked: <list — Quality/Security/Tests/Data/Architecture/Infrastructure, with skip reasons>
- Open findings: 🔴 <N> Critical, 🟠 <N> Major, 🟡 <N> Minor, 🔵 <N> Nits
- Findings by owner: coding: <ids> | data-scientist: <ids> | infrastructure: <ids> | architect: <ids>
- Files changed: <N>, lines: +<X> / −<Y>
- Recommended next step: ready to merge | route fixes back to <agent(s)> | escalate to human
```

## TASKS PLANNED

Producer: `backlog-manager`, on the Plan workflow only.

```markdown
## TASKS PLANNED

**Tracker platform:** <github-issues | ado-boards | jira | linear>
**Parent work item:** <id> — <link>
**Link pattern:** <e.g. AB#<n> / parent-child relation>
**Tasks created (provisional, tag `pending-approval`):**
| Task id | Title | ACs | State |
|---|---|---|---|
| <id> | <title> | <n> | <entry state> |
| ... | ... | ... | ... |
**Approach comment posted on parent:** yes — <comment link or id>
**Open items / could not link:** <list, or "none">
```

## BOOTSTRAP COMPLETE

Producer: `bootstrapper`. `Ready for delivery: no` blocks entry to Stage 1.

```
BOOTSTRAP COMPLETE
- Profile: <path> — <created | repaired | already valid>
- Required fields: <n>/6 populated <list any still empty>
- Plugins installed this run: <list, or "none — user deferred">
- Plugins already present: <list, or "none">
- Declared but unsupported: <technology → "falls back to repo conventions", or "none">
- Gaps for the user: <profile fields left empty, deferred installs, decisions still needed, or "none">
- Ready for delivery: yes | no — <what blocks it>
```

## Corrective accounting

Applies to `architect`, `coding`, `infrastructure` and `data-scientist` when
fixing review findings, and to receivers of those corrective hand-offs.
`Findings addressed` is omitted on a first pass; in a corrective round account
for **every routed finding id**, one line per id, with one of:

- `fixed` — evidence at the changed file:line or deliverable/location, using the
  producer's field format; analysis fixes identify the changed artifact and evidence.
- `disputed` — the reason the finding is wrong or already handled.
- `not mine` — the named owner to whom it must be routed.

A fixer's claim does not close a finding. `dev-lead` checks every routed id,
re-routes `not mine` to the named owner, and carries disputed reasons into
re-review; `review-lead` adjudicates with the independent specialists. Missing ids
are a malformed hand-off, not silently accepted fixes. Preserve original finding
ids across re-review. The supervisor alone owns the findings ledger, retry budgets
and corrective re-verification; this section grants no extra retry or gate bypass.

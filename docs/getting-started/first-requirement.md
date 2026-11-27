# Your first requirement

Start `dev-lead` and give it one prepared requirement — free text, a tracker
item, a requirements file, or a `plan.md` from planning mode:

```shell
copilot --agent agile-agents-core:dev-lead
```

## What to expect

1. **Intake.** `dev-lead` confirms the profile, captures the Definition of Done,
   out-of-scope items and acceptance criteria. If the source states no criteria,
   it derives candidates and marks them for your confirmation.
2. **Research and plan.** It verifies the requirement against your concept and
   decision records, then proposes tasks — creating linked tracker items first
   when `backlog.create_tasks` is enabled.
3. **Approve the plan.** This is the only mandatory approval. Choose *Approve*,
   *Adjust* or *Cancel*. Read the assumptions, risks and trade-offs it lists.
4. **Autonomous delivery.** After approval, it implements, runs the deterministic
   test bar and obtains independent review without further questions, unless a
   [stop condition](../flow/plan.md#when-the-run-stops) fires.
5. **Done report.** Every acceptance criterion is mapped to a delivered task and
   evidence, or reported as out of scope.

## One criterion from intake to Done

Suppose the requirement is: **“From the concepts page, a reader can find the
purpose and source of every shipped skill.”** This is an example, not a
recorded run.

1. **Research** finds where the manifest discovers skills and where the site
   publishes its navigation. A successful site build can detect a broken
   link, but cannot detect a skill that nobody linked.
2. **Plan** therefore proposes two checks: follow the path from Concepts to the
   guide, and compare the set of documented skill links against the shipped
   definitions in both directions. The human approves this criterion, task and
   verification approach. An inline plan needs the same approval as a tracked one.
3. **Implement** adds purpose and source links. The author hands the lead the
   changed pages, the set comparison and the build result. If a shipped skill
   has no entry, the criterion fails even if every link that *does* exist works.
4. **Verify and review.** The lead runs the configured checks on the combined
   content. Reviewers can still find that a link names the right skill but
   describes the wrong responsibility. The author corrects that finding by ID;
   the changed content goes through applicable checks before re-review.
5. **Reconcile.** The lead can now point from the original sentence to the
   delivered guide, the matching sets, and the independent assessment of the
   descriptions. Without that evidence it reports what is missing instead of
   treating “task finished” as Done.

See [the handovers](../flow/handoffs.md#what-crosses-a-phase-boundary) for what
each receiver needs and [budget checkpoints](../flow/budget.md) for when an
otherwise healthy run can pause for a resource decision.

## Good first requirements

- Small, observable behaviour changes with clear acceptance criteria.
- Work inside existing boundaries — no new service, dependency or public contract.

Opening the resulting pull request needs your explicit approval; merging it is
always yours. Follow the [Flow](../flow/index.md) section for stage details.

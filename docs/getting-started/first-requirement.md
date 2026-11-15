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

## Good first requirements

- Small, observable behaviour changes with clear acceptance criteria.
- Work inside existing boundaries — no new service, dependency or public contract.

Opening the resulting pull request needs your explicit approval; merging it is
always yours. Follow the [Flow](../flow/index.md) section for stage details.

# Verification and evaluation

**Verifying a solution change** and **evaluating the harness** answer different
questions. A team can have a well-formed run log and a failing feature. It can
also solve a task without demonstrating that a particular skill caused the result.

| Question | Owner and evidence | Limit |
|---|---|---|
| Did this task deliver the agreed behavior? | An application author maps behavior to tests. An IaC author supplies validation **and** maps behavior to an IaC test, or names the specific reason no executable test applies. Analysis supplies method, baseline and limitations. | A clean IaC preview alone does not prove behavior. A worker's completion marker is not independent verification. |
| Do all the changes still work together? | The lead invokes the configured [test bar](../flow/implement.md) over the combined content: check results, explicit skips and applicable startup evidence. | A reachable HTTP endpoint does not establish that a user journey works. Disabled checks do not pass. |
| Is the result acceptable against the requirement? | Independent reviewers examine the current diff and test evidence. The lead maps each original criterion to a delivered result and supporting evidence. | A tracker item marked complete or an approval on older content is insufficient. |
| Did a recorded run follow the expected process? | [L0 trajectory checks](../../eval/pipeline/trajectory/README.md) validate the event log's ordering, gate and telemetry contracts. | Conformance is not outcome quality. |
| What skill use was recorded? | The offline [DeepEval scorer](../../eval/deepeval/README.md) compares named skill invocations in existing traces to expected identities. | It neither reruns recorded commands nor proves correct skill use or task acceptance. |
| Is a skill artifact useful for a given task? | [Skill evaluation](../../eval/skills/README.md) separates deterministic hygiene from a manual outcome check using Waza. | Passing hygiene, a small prompt, or one synthetic example does not establish effectiveness across solutions. |
| Can an entire scenario be scored? | [Custom-eval](../../eval/pipeline/custom-eval/README.md) separates recorded command evidence from grading; missing evidence stays unverified. | Simulated approval is eval-only. Without verifiable approval transport the scenario blocks; it is not a live end-to-end pass. |

## Maintaining this repository

`python scripts/run-repo-checks.py lint` checks definitions and repository
contracts. `python scripts/run-repo-checks.py unit` composes unittest, pytest
and Node tests using the repository's locked evaluation environment. Fixtures
exercise the harness or scorer, not a production customer's solution. The
canvas packaging tests, for example, exercise shipped files with a stubbed SDK
connection; they do not prove discovery in every host.

The [site build](../site/README.md) validates repository link targets,
anchors and allowlisted assets. It does not fetch external URLs to prove they
are reachable. The [repository profile](../../.github/solution-profile.yaml)
also configures a local docs smoke target. It does not enable browser E2E,
coverage or mutation thresholds; these are solution choices, not universal
defaults. See [operating limits](CONCERNS.md) before interpreting a green result.

**Evidence:** [repository checks](../../scripts/run-repo-checks.py),
[test-bar contract](../../plugins/agile-agents-core/skills/test-bar-gate/SKILL.md),
[evaluation boundaries](../../eval/README.md),
[layered evaluation decision](../adr/0008-layered-evaluation-strategy.md).

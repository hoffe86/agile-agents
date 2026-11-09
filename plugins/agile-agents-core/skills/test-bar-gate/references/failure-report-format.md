# Failure report format

Relay runner evidence unchanged. Execution failures use the bounded retry policy
in `../SKILL.md`; configuration gaps (exit 2) stop for solution setup.

````markdown
**Test-bar gate failed: <check>**

- **Stack detected:** (solution-declared commands)
- **Command run:** `<argv joined with spaces>`
- **Exit code:** <child code, 127 for missing executable, 2 for configuration gap>
- **Reason:** <when available>
- **Working directory:** <absolute path>

### stderr (last 30 lines)

```text
<stderr tail; smoke uses last 20 startup stdout/stderr lines;
configuration gaps name missing settings>
```

### Suggested next action

Return to `coding` or `infrastructure` with this report, within the supervisor's
remaining retry budget. Stop for unresolved configuration.
````

`coding` owns application code **and tests**; `infrastructure` owns IaC/pipelines.
A changed assertion must state its old claim and why it was invalid. The event
contains the tail, not full output; do not imply an unavailable log was retained.

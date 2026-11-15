# Bootstrap a repository

`bootstrapper` configures the harness for one solution. Run it once before the
first delivery, and again whenever the profile needs repair.

```shell
copilot --agent agile-agents-core:bootstrapper
```

Then ask it to set up the harness for the repository.

## What it does

1. **Reads the repository first** — languages, CI commands, existing instructions,
   local skills and installed plugins.
2. **Interviews you only for what no scan can answer**, such as lifecycle stage,
   test discipline, compliance scope and where documentation lives.
3. **Proposes and writes `.github/solution-profile.yaml`** with your approval.
4. **Proposes plugins** that fill real gaps, and installs only those you approve.
5. **Reports what is still missing** and which fallback agents will use.

It finishes with a `BOOTSTRAP COMPLETE` block whose `Ready for delivery` field
tells you whether `dev-lead` can start.

## The six required fields

| Field | Why it matters |
|---|---|
| `identity.project_name` | Names the run and generated documents. |
| `identity.lifecycle_stage` | Calibrates how much rigour and ceremony applies. |
| `documentation.location` | Where agents read and update documentation. |
| `backlog.platform` | Which tracker, if any, `backlog-manager` writes to. |
| `tech_stack.primary_languages` | Which conventions and checks apply. |
| `tech_stack.test_discipline` | How authors are expected to write tests. |

Enabled quality gates must declare their commands; a disabled gate stays visible
as an explicit skip. The [repository overview](../../README.md#solution-profile)
summarizes the remaining profile sections.

Next: [run a first requirement](first-requirement.md).

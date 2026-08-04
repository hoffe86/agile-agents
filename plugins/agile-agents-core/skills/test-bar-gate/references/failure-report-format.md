# Failure report format

The `test-bar-gate` runner prints this markdown block to stdout when any of the three checks fails. The `dev-lead` supervisor copies it verbatim into the next prompt to `coding` (or `testing`) for the one allowed corrective retry.

## Template

```markdown
❌ **Test-bar gate failed: <check>**

- **Stack detected:** <stack>
- **Command run:** `<argv joined with spaces>`
- **Exit code:** <int>
- **Working directory:** <repo root absolute path>

### stderr (last 30 lines)

```text
<up to 30 lines of stderr; if more was emitted, append the line below>
... (truncated, full output in $COPILOT_EVENT_LOG)
```

### Suggested next action

Return to `<coding|testing>` with this report and one corrective retry. If the gate fails again on the same task, halt and ask the user how to proceed.
```

## Field rules

| Field            | Source                                                                 |
|------------------|------------------------------------------------------------------------|
| `<check>`        | First failing check name: `lint`, `typecheck`, or `test`               |
| `<stack>`        | Resolved stack key (e.g. `python`, `csharp`, `typescript`)             |
| `<argv ...>`     | The exact command list, joined with single spaces, with no shell quoting beyond what the runner uses |
| `<int>`          | Process exit code                                                      |
| stderr block     | Last 30 lines of stderr; if stdout-only tools, fall back to last 30 lines of stdout |
| Suggested action | `coding` for lint/typecheck failures and most test failures; `testing` only when the failing assertion clearly belongs to the test layer |

## Sample populated report (Python typecheck failure)

```markdown
❌ **Test-bar gate failed: typecheck**

- **Stack detected:** python
- **Command run:** `pyright .`
- **Exit code:** 1
- **Working directory:** /workspace/example-app/api

### stderr (last 30 lines)

```text
/workspace/example-app/api/src/orders/service.py
  /workspace/example-app/api/src/orders/service.py:42:13 - error: Object of type "None" is not subscriptable (reportOptionalSubscript)
  /workspace/example-app/api/src/orders/service.py:88:9  - error: Argument of type "str | None" cannot be assigned to parameter "order_id" of type "str" in function "fulfil"
    Type "str | None" is not assignable to type "str"
      Type "None" is not assignable to type "str" (reportArgumentType)
2 errors, 0 warnings, 0 informations
```

### Suggested next action

Return to `coding` with this report and one corrective retry. If the gate fails again on the same task, halt and ask the user how to proceed.
```

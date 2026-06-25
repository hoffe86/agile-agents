# Task 05 — Write a PR description from a multi-file diff

## User story

As a developer about to open a pull request, I want a high-quality PR description generated
from my diff so reviewers immediately understand what changed and why, without reading the
diff first.

## Context

The diff (provided as `diff.patch` in the task workspace at run-time) modifies 4 files:

- `src/Orders/OrderService.cs` — added `CancelAsync(Guid orderId)` method
- `src/Orders/IOrderRepository.cs` — added `MarkCancelledAsync` method on the interface
- `src/Orders/OrderRepository.cs` — implemented `MarkCancelledAsync` against EF Core
- `tests/Orders.Tests/OrderServiceTests.cs` — added 3 unit tests for cancellation paths

The change implements user story `JIRA-4421` — *"Customer can cancel a Placed or Paid
order; Shipped or Delivered orders cannot be cancelled."*

## Requested deliverable

A single Markdown PR description (no body of a PR — the description text only) that:

1. Has a short, imperative title at the top (≤ 72 chars).
2. Has sections: **What**, **Why**, **How**, **Testing**, **Risk & rollback**.
3. Cross-references the JIRA ticket (`JIRA-4421`).
4. Calls out any breaking change or migration concern (or states "none" explicitly).
5. Is written for a reviewer who **has not read the diff** — explain the new behaviour, not
   the syntax.

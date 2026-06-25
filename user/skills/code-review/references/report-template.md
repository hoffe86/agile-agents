# Report Template

Use this exact structure for the code review report. Replace placeholders with actual findings.

---

```markdown
# [Project Name] — Code Review Report

**Date:** [YYYY-MM-DD]  
**Scope:** Architecture, Clean Code, Security, Test Quality  
**Branch:** `[branch-name]` (current state)

---

## Executive Summary

[2-3 sentences describing overall health. State the finding counts: **N critical**, **N high**, **N medium**, **N low**. Call out the top 3 most urgent issues by name.]

Each finding is classified as:
- 🤖 **Agent** — Can be implemented by Copilot autonomously
- 👤 **User** — Requires human decision, team discussion, or access to external systems

---

## 🔴 Critical Findings

### [ID]: [Title]
| | |
|---|---|
| **Severity** | 🔴 Critical |
| **Category** | [Dimension] — [Sub-category] |
| **Files** | `[file:line-range]` |
| **Issue** | [What's wrong and why it matters] |
| **Fix** | [Concrete remediation steps] |
| **Owner** | 🤖 Agent / 👤 User — [reason if User] |

[Repeat for each critical finding]

---

## 🟠 High Findings

[Same format as Critical]

---

## 🟡 Medium Findings

[Same format, but findings can use a more compact single-table row if there are many]

---

## 🟢 Low Findings

[Same compact format]

---

## 📊 Test Coverage Gaps

### High-Priority Untested Areas

| Class / Area | Priority | Why It Matters |
|---|---|---|
| `[ClassName]` | 🔴 High | [Brief reason] |

### Test Quality Issues

| Issue | Severity | Files |
|---|---|---|
| [Description] | 🟡 Medium | [Files] |

---

## 📋 Prioritized Action Plan

### Phase 1 — Security Quick Wins (🤖 Agent)
| ID | Action | Effort |
|---|---|---|
| [SEC-XX] | [Action description] | S/M/L |

### Phase 2 — Architecture Quick Wins (🤖 Agent)
| ID | Action | Effort |
|---|---|---|

### Phase 3 — Code Quality (🤖 Agent)
| ID | Action | Effort |
|---|---|---|

### Phase 4 — Requires User Decision (👤 User)
| ID | Action | Decision Needed |
|---|---|---|
| [SEC-XX] | [Action] | [What decision is needed] |

---

## Summary Statistics

| Category | 🔴 Critical | 🟠 High | 🟡 Medium | 🟢 Low | Total |
|---|---|---|---|---|---|
| Security | | | | | |
| Architecture | | | | | |
| Clean Code | | | | | |
| Testing | | | | | |
| **Total** | | | | | |

| Owner | Count |
|---|---|
| 🤖 Agent (can be automated) | |
| 👤 User (needs human decision) | |
```

---

## Effort Sizing Guide

- **S (Small)**: Single-file change, <10 lines, no design decisions. Examples: remove a log parameter, add an attribute, fix a typo.
- **M (Medium)**: Multi-file change, 10-50 lines, may require reading related code. Examples: standardize error handling, deduplicate registrations, update documentation.
- **L (Large)**: Structural change, >50 lines, may affect multiple components. Examples: extract a class, refactor a builder pattern, merge duplicate test suites.

## ID Prefix Convention

- `SEC-` — Security findings
- `ARCH-` — Architecture and design findings
- `CODE-` — Clean code and quality findings
- `TEST-` — Test quality findings

Number sequentially within each prefix: SEC-01, SEC-02, ARCH-01, etc.

---
name: release-notes
description: Generate release notes (CHANGELOG entry + GitHub release body) from commit history between two refs. Groups commits by Conventional Commit type (feat / fix / perf / refactor / docs / test / build / ci / chore), highlights breaking changes, surfaces security fixes prominently, links contributors, and outputs a Keep-a-Changelog-compatible markdown block. Loaded by dev-lead at release-tag time. Composes with conventional-commit (parsing) and read-repo-context (repo conventions, version scheme).
---

# release-notes

Author release notes that are **useful to users**, not just a commit log. Users care about: what's new, what's broken, what to do before upgrading, and what's been silently fixed (especially security).

## When to invoke

- `dev-lead` is finalising a tagged release.
- A human asks for release notes between two refs (`v1.2.0..v1.3.0`, `main..release/2026.05`, last-tag..HEAD).
- A monthly / sprint-end summary is needed across many merged PRs.

## Inputs you read first

1. **Commit range** — provided by the caller. If only one ref is given, default to `<previous-tag>..<ref>`. If no tags exist, default to `<merge-base of main, ref>..<ref>`.
2. **Commit log** — `git --no-pager log <range> --pretty=format:"%H%x09%s%x09%an%x09%ae" --no-merges` (or include merges with `--first-parent` for squash-merge workflows; choose based on the repo's merge style — detect via `read-repo-context`).
3. **Repo conventions** via `read-repo-context`:
   - `CHANGELOG.md` — does it exist? If yes, **prepend** a new section in the existing format. If using Keep a Changelog, conform exactly.
   - Version scheme (SemVer / CalVer / pinned-major) — derive from existing tags.
   - Contributor attribution policy (do they want `@handle` or full names; do they want first-time-contributor callouts?).
   - The solution-profile (if present) — project-specific release-note rules (e.g., "no internal handle names, only public display names").

## Parsing rules

- Treat each commit subject as a **Conventional Commit** (`type(scope): subject`). If the repo does not use Conventional Commits, fall back to grouping by linked PR labels, then by directory of the largest changed file.
- Recognised types and their headings:
  - `feat` → **✨ Features**
  - `fix` → **🐛 Bug fixes**
  - `perf` → **⚡ Performance**
  - `refactor` → **♻️ Refactors** (only include if user-visible — silent refactors should be omitted)
  - `docs` → **📚 Documentation**
  - `test` → omit (internal, not user-facing)
  - `build` / `ci` / `chore` → **🔧 Build / chore** (collapse to a single section, list dependency bumps as "Dependency updates: N packages")
  - `revert` → **⏪ Reverts** (always surface — users need to know)
- **Breaking changes** — any commit with `!` in the type (e.g., `feat!:`) or a `BREAKING CHANGE:` footer goes to a top-level **💥 Breaking changes** section *as well as* its category section.
- **Security fixes** — any commit with `(sec)` scope or a body mentioning CVE / OWASP / CWE goes to a top-level **🔒 Security** section. Be conservative — over-surface rather than miss.

## Output structure

```markdown
## [<version>] — <YYYY-MM-DD>

<One sentence — the headline of this release. Skip if you cannot honestly summarise.>

### 💥 Breaking changes

- <subject> ([#<PR>](url)) — **migration:** <one-line guidance>

### 🔒 Security

- <subject> ([#<PR>](url)) — <CVE / advisory id if known>

### ✨ Features

- <subject> ([#<PR>](url)) — @<author>

### 🐛 Bug fixes

- <subject> ([#<PR>](url)) — @<author>

### ⚡ Performance

- <subject> ([#<PR>](url))

### ♻️ Refactors

- <subject> ([#<PR>](url))

### 📚 Documentation

- <subject> ([#<PR>](url))

### 🔧 Build / chore

- Dependency updates: N packages bumped.
- <other notable infra / CI items>

### Contributors

Thanks to @<handle1>, @<handle2>, … for contributions to this release.
<First-time contributors: @<new1>, @<new2> — if any.>

### Upgrade notes

<Concrete upgrade steps if any. Skip the section entirely if upgrade is a no-op `git pull` / `dotnet add package … --version <new>`.>
```

## Tone and constraints

- **User-facing language.** "Login now persists across browser restarts" not "Refactored AuthService to use IPersistedTokenStore".
- **Be specific about breaking changes.** Always include a one-line migration. If migration is non-trivial, link to a longer doc; do not inline a 30-line guide.
- **Security surfacing is a duty, not an option.** A fix that is "just a bug fix" but happened to close an injection or auth bypass goes under **🔒 Security** even if the commit message did not flag it — re-read the diff if uncertain.
- **No marketing.** "Improved performance" is uselessly vague — quote a number ("p95 latency on `/orders` dropped from 220 ms → 95 ms in benchmarks") or skip the bullet.
- **Omit empty sections.** A release with no breaking changes should not show an empty Breaking-changes header.
- **Link every entry.** PR number + URL. Without a link, a reader cannot dig deeper.
- **Dates in ISO 8601** (`YYYY-MM-DD`).

## Hand-off

Return:
1. The new section ready to **prepend** to `CHANGELOG.md`.
2. Optionally, a separate **GitHub release body** version (often shorter — drops the dependency-update bullet, keeps everything else). Caller supplies the GitHub release via `gh release create … --notes-file -`.

The skill never edits `CHANGELOG.md` itself — `dev-lead` (or a human) decides whether to commit and tag.

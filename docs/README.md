# Documentation

- [Repository overview and commands](../README.md)
- [Customization ownership, activation and rollback](customization-ownership.md)
- [Generated AGENTS mapping](AGENTS-MD-MAPPING.md)
- [Solution-profile canvas](#solution-profile-canvas)
- [Architecture decisions](adr/)
- [Evaluation overview](../eval/README.md)
- [Custom-eval inputs and evidence limits](../eval/pipeline/custom-eval/README.md)

## Solution-profile canvas

The optional project extension in
[`.github/extensions/solution-profile/`](../.github/extensions/solution-profile/)
edits this checkout's `.github/solution-profile.yaml` in the Copilot app. It is
repository tooling, not part of the `agile-agents-core` plugin or a replacement
for the profile interview. The app/runtime must expose extension and canvas
tools to the selected agent; a skill alone does not grant those tools.

With Node.js 22+ available, install its single locked dependency explicitly.
Generation also needs Bash and Python 3 on Unix, or PowerShell (`pwsh`) on Windows:

```sh
npm ci --prefix .github/extensions/solution-profile --ignore-scripts --no-bin-links
npm test --prefix .github/extensions/solution-profile
```

The extension's `.npmrc` also disables npm binary links. The canvas uses the YAML
library, not its CLI; npm's optional `node_modules/.bin/yaml` symlink would prevent
Copilot from accepting the project extension. Do not copy symlinks into the
extension or bypass its trust check.

In the app, ask the default agent to reload extensions and open the
**Solution profile** canvas. Its native type is `solution-profile`; the only
agent-facing action, `status`, is read-only. No Copilot SDK package installation
is needed: the runtime supplies it.

The **Fields** view puts the six required values and verification configuration
first; advanced groups are collapsed. Origin labels distinguish existing,
unknown, edited and unconfirmed template values. Read-only discovery suggests
only root language manifests and a `docs/` directory; it never infers commands,
compliance decisions or budgets. **YAML** supports missing/custom keys and manual
structure changes. Structured edits patch the selected source range without
reformatting other lines. Collection editors expose their original YAML,
including comments; preserve them when editing.

Edits persist in the session's artifact directory, keyed by the checkout path,
not the panel ID. **Apply YAML to draft** persists raw edits, even invalid ones;
unapplied text is only in the page and warns before leaving. Multiple panels
share a versioned draft. The profile remains unchanged until the user reviews
the current diff, approves both saving and derived `AGENTS.md` generation, and
clicks **Save profile**.

Save validates syntax, duplicate keys, required values, template-derived types,
selected enums, enabled check commands and the five E2E fields. Disabled checks
remain visible skips; missing smoke setup is a warning, not verified startup.
This is not a full profile-policy validator or permission to run the harness.
Unsupported anchors, aliases, explicit tags and YAML 1.1 require manual editing
outside the canvas. Invalid input stays recoverable in the draft.

Stale disk or panel revisions block writes. Save retains the previous file as
an ignored sibling `solution-profile.yaml.canvas-backup-<id>` and uses an
exclusive replacement so a concurrent file is not overwritten. If recovery is
needed, the error names the retained file; inspect both before restoring.
Backups are not removed automatically. A crash may leave a
`solution-profile.yaml.canvas-lock`; inspect the file, backups and draft before
removing a genuinely abandoned lock. This is a local editor, not protection
against another process with filesystem access intentionally replacing parent
directories. Each panel serves only on loopback with a private capability,
origin checks and no external assets or requests.

Saving runs only the [skill-bundled generator](AGENTS-MD-MAPPING.md#re-generation-policy)
with fixed arguments and a private parsed JSON snapshot, as required by ADR 0005.
It executes **no profile commands, installs, commits or deployments**.
`AGENTS.md` must be absent or have this generator's ownership marker; hand-maintained,
linked or concurrently changed files are preserved. Previous generated content
is retained in an ignored `AGENTS.md.canvas-backup-<id>` file.

The two writes are not a transaction. If generation fails, the profile remains
saved, the UI reports the failure and the session retains it across reloads.
Resolve the cause, review again and click Save to retry generation; do not
relabel hand-maintained instructions to bypass the ownership check.
Closing a panel stops its listener; reopening or reloading the extension
restores its saved session draft. To remove the extension, close its panels,
remove only its project folder deliberately, then reload extensions; the
profile and recovery files remain untouched.

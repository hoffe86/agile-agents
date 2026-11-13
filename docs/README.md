# Documentation

- [Repository overview and commands](../README.md)
- [Customization ownership, activation and rollback](customization-ownership.md)
- [Generated AGENTS mapping](AGENTS-MD-MAPPING.md)
- [Solution-profile canvas](#solution-profile-canvas)
- [Architecture decisions](adr/)
- [Evaluation overview](../eval/README.md)
- [Custom-eval inputs and evidence limits](../eval/pipeline/custom-eval/README.md)

## Solution-profile canvas

`agile-agents-core` ships the optional
[Solution profile canvas](../plugins/agile-agents-core/extensions/solution-profile/)
through its native `extensions` manifest entry. Installing and enabling core
makes it discoverable in hosts that support Copilot runtime extensions and
canvas rendering. A skill alone does not grant those tools. Other clients keep
using the profile-interview skill; the canvas does not replace that interview.

The canvas edits `.github/solution-profile.yaml` in the active session's working
directory, never in the installed plugin. Templates and generators are read
from the plugin. Run the session from the solution root. Missing profiles start
as drafts; even `.github/` is created only on an explicit Save.

Consumers do not run npm or install dependencies. The committed `yaml.cjs`
bundle includes the locked YAML parser and its `yaml.LICENSE`; the runtime
supplies the Copilot SDK. The extension requires Node.js 22+. Saving and
generating `AGENTS.md` also needs Bash and Python 3 on Unix, or PowerShell
(`pwsh`) on Windows.

For maintainers, rebuild only when the dependency or bundling inputs change:

```sh
npm ci --prefix scripts/solution-profile-canvas --ignore-scripts --no-bin-links
npm run build --prefix scripts/solution-profile-canvas
npm run check:bundle --prefix scripts/solution-profile-canvas
npm test --prefix scripts/solution-profile-canvas
```

`esbuild` and `yaml` are pinned build-only dependencies under
`scripts/solution-profile-canvas/`, outside the distributed plugin. Include the
generated bundle and license in the same change; plugin installation does not build them.
CI tests the shipped files before installing build dependencies, then rejects
bundle drift on Linux and Windows. Packaging tests copy core outside this
checkout without `node_modules`, stub only the SDK connection, and exercise
opening, editing, saving and generation against an unrelated consumer directory.
They do not substitute for checking native discovery in a supported host.

The small [project loader](../.github/extensions/solution-profile/extension.mjs)
forwards to the same implementation for development in this repository. It is
not needed in consuming solutions. If an installed core also registers the
canvas here, use `extensionId: project:solution-profile` for the checkout or
`extensionId: plugin:agile-agents-core:solution-profile` for the installed release.
The build package's `.npmrc` disables binary
links for local builds; do not copy symlinks or `node_modules` into releases or
bypass the runtime's trust checks.

After installing or updating core, ask the default agent to reload extensions and open the
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
a sibling `solution-profile.yaml.canvas-backup-<id>` and uses an
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
is retained in an `AGENTS.md.canvas-backup-<id>` file. This repository ignores
these recovery files. Consumers should add `.github/solution-profile.yaml.canvas-*`
and `AGENTS.md.canvas-*` to their own ignore rules; the canvas does not change
their `.gitignore`.

The two writes are not a transaction. If generation fails, the profile remains
saved, the UI reports the failure and the session retains it across reloads.
Resolve the cause, review again and click Save to retry generation; do not
relabel hand-maintained instructions to bypass the ownership check.
Closing a panel stops its listener; reopening or reloading the extension
restores its saved session draft. To turn off the canvas, close its panels and
disable that extension in the host, or disable/uninstall core deliberately,
then reload extensions. The profile and recovery files remain untouched.

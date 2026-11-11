# Regenerate the portable agent context

The generator scripts and `agents-md-template.md` ship with this skill. Resolve
`<skill-dir>` from the loaded `SKILL.md`, not a guessed installation path.
Run after each approved profile write, including repairs. Profile approval
must explicitly cover the derived `AGENTS.md` write.

From the consuming checkout, use one runner:

```powershell
& "<skill-dir>/scripts/generate-agents-md.ps1" -RepoRoot "<consumer-root>"
```

```bash
bash "<skill-dir>/scripts/generate-agents-md.sh" --repo-root "<consumer-root>"
```

PowerShell requires 5.1+; Bash uses standard Unix utilities. The scripts read
template-style YAML; JSON snapshots are also supported (Bash needs Python 3 for
JSON). The canvas passes a private parsed JSON snapshot, preserving flow YAML
and quoted values without rewriting the source profile.

Defaults always target the consumer's `.github/solution-profile.yaml` and
`AGENTS.md`, never the plugin installation. Without an explicit root, they use
the current Git checkout or current directory. `-ProfilePath` / `--profile`,
`-AgentsDir` / `--agents-dir`, `-SkillsDir` / `--skills-dir` and
`-Output` / `--output` remain available. Paths supplied explicitly are relative
to the working directory. `-DryRun` / `--dry-run` prints instead of writing.

Discovery prefers this marketplace's plugin folders when present, then the
consumer's local agent/skill folders, then the bundled core folders. It does
not inventory every installed plugin or prove runtime availability. Confirm
the intended sources; use directory arguments for other layouts.

An absent output may be created. An existing output must carry the exact
`<!-- GENERATED-BY: scripts/generate-agents-md.ps1 -->` first line; linked files
and hand-maintained instructions are refused. Keep this marker stable for older
generated files. Do not remove instructions or add a marker just to bypass the
guard; ask the human to resolve ownership.

Verify exit status and the generated diff. Report missing runtimes, failures or
ownership conflicts explicitly; retain the profile and report bootstrap as
incomplete until resolved. Never commit or install a runtime as a side effect.
The scripts render context only; profile command values are data, not commands.

The harness repository keeps `scripts/generate-agents-md.ps1` and `.sh` as
thin wrappers for existing local commands and GitHub CI. Edit the bundled
implementations and template, not duplicate copies. CI's existing skill-path
filters cover these resources; it still checks drift and runner parity.

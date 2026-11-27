# Runtime and tools

Installing the plugin and developing this repository are different jobs. A
team using core does **not** need to install the documentation website or the
evaluation environment to run its own solution.

| Where | What runs there | Configuration and dependencies |
|---|---|---|
| Consuming solution | GitHub Copilot CLI loads Markdown agent and skill definitions from the plugin manifest. Some skills invoke local helpers. | The solution supplies its own toolchain and check commands in `.github/solution-profile.yaml`. A language name alone is not a runnable command. |
| Local verification | A Bash or PowerShell test-bar runner executes those commands and, where applicable, starts a local smoke target. Python reads measured usage for budget checks. | Bash uses `yq` v4 and `curl`; PowerShell uses `powershell-yaml`. See the [runner prerequisites](../../plugins/agile-agents-core/skills/test-bar-gate/SKILL.md) for platform-specific smoke requirements. |
| Optional profile editor | A runtime extension renders the Solution profile canvas in a supporting host. The host supplies the SDK; the YAML parser ships bundled with its license. | Node.js 22+ for the extension; saving invokes the bundled profile generator. No consumer npm install. See [canvas behavior and recovery](../README.md#solution-profile-canvas). |
| Documentation development | Docusaurus builds canonical Markdown and approved assets into a static site with local search. | Node.js 24, npm 12 and the site's lockfile. The [site guide](../site/README.md) has build, preview and publication commands. |
| Harness maintenance | PowerShell, shell, Python and JavaScript check contracts, packaging and fixtures. DeepEval scores existing traces; Waza evaluates skills. | Maintainer tools, not requirements imposed on every consuming solution. The [evaluation guide](../../eval/README.md) explains the distinct environments. |

For a first run, follow [install](../getting-started/installation.md),
[bootstrap](../getting-started/bootstrap.md) and [give the lead a
requirement](../getting-started/first-requirement.md). No harness application
server or cloud deployment is part of that sequence.

**Evidence:** [plugin manifest](../../plugins/agile-agents-core/.github/plugin/plugin.json),
[solution profile](../../.github/solution-profile.yaml),
[site package](../site/package.json), [repository check runner](../../scripts/run-repo-checks.py).

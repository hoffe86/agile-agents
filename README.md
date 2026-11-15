# Agile Agents

The **Agentic Agile Harness** is a GitHub Copilot CLI plugin that guides a
prepared requirement through **Research → Plan → Implement → Review**. It
combines specialist agents, technology-neutral skills, human approval,
deterministic checks and independent review.

**[Documentation website](https://hoffe86.github.io/agile-agents/)** —
Introduction, Getting started, Flow and Evaluation. The site becomes available
after GitHub Pages deployment; the [documentation hub](docs/README.md) is also
available in this repository.

## Install

Install the core plugin:

```shell
copilot plugin marketplace add hoffe86/agile-agents
copilot plugin install agile-agents-core@agentic-universe
```

Existing `agile-agents-marketplace` registrations are not automatically
migrated to `agentic-universe`. For prerequisites and optional personal
guidance, see [installation](docs/getting-started/installation.md).

Run the bootstrapper for your repository:

```shell
copilot --agent agile-agents-core:bootstrapper
```

Ask it to set up the harness. It discovers existing guidance and commands,
interviews you for missing facts, and writes the approved solution profile.
Plugin installation and profile changes require your approval. See
[bootstrap](docs/getting-started/bootstrap.md) and the
[first requirement](docs/getting-started/first-requirement.md).

## What you get

Core provides 15 agents and 25 repository-scope skills:

| Group | Agents |
|---|---|
| Supervisor | `dev-lead` |
| Authors | `architect`, `coding`, `infrastructure`, `data-scientist` |
| Reviewers | `review-lead`, `code-reviewer`, `security-reviewer`, `architecture-reviewer`, `infrastructure-reviewer`, `test-reviewer`, `data-reviewer` |
| Support | `backlog-manager`, `bootstrapper`, `capability-scout` |

See [concepts and roles](docs/introduction/concepts.md), the
[agent definitions](plugins/agile-agents-core/agents/), and the generated
[skill inventory](AGENTS.md). Reviewers are read-only by effect;
`capability-scout` proposes improvements but does not adopt them.

The optional [`agentic-persona`](https://github.com/hoffe86/agentic-persona)
plugin is independently maintained and is not required by core. See
[customization ownership](docs/customization-ownership.md) for activation and
rollback.

## How it works

`dev-lead` checks the solution profile and the prepared requirement, researches
the approach, and creates a plan for human approval. After approval, it
implements approved tasks directly or delegates them to specialists. Authors
own their tests; deterministic checks precede independent review.

Creating a pull request requires separate user approval. Merging or closing a
pull request, rewriting shared history and deploying to production are
human-only operations. See the [flow overview](docs/flow/index.md),
[approvals](docs/flow/plan.md), and
[review and completion](docs/flow/review.md).

## Solution profile

`.github/solution-profile.yaml` records the solution's operational facts,
including its stack, tracker, quality-gate commands and cost envelope.
`bootstrapper` discovers and prepares it; `dev-lead` requires six fields before
delivery. See the [bootstrap guide](docs/getting-started/bootstrap.md).

The optional [Solution profile canvas](docs/README.md#solution-profile-canvas)
is available in supported hosts. The generated [AGENTS.md](AGENTS.md) is
maintained by the generators, not edited by hand.

## Evaluation and development

[Evaluation](eval/README.md) describes the evidence and its limits. DeepEval
scores recorded skill usage; trajectory checks assess process events; Waza
provides skill evaluations. Full live RPI evaluation remains blocked at
approval transport.

For repository development, follow
[the contributor instructions](.github/copilot-instructions.md). The
repository test bar requires the hash-locked
[DeepEval environment](eval/deepeval/README.md#install-and-verify), PowerShell,
Node.js 24 and npm 12. Install the documentation site's locked dependencies
before running the configured checks:

```shell
npm ci --prefix docs/site --ignore-scripts --no-audit --no-fund
python scripts/run-repo-checks.py lint
python scripts/run-repo-checks.py unit
pwsh -NoProfile -File scripts/check-skill-tokens.ps1
```

The profile's smoke check starts the documentation site; it is not an
application deployment for the harness. Run the full profile gate with
`pwsh -NoProfile -File plugins/agile-agents-core/skills/test-bar-gate/scripts/run-gate.ps1 -ProfilePath .github/solution-profile.yaml`
or
`bash plugins/agile-agents-core/skills/test-bar-gate/scripts/run-gate.sh --profile .github/solution-profile.yaml`.
PowerShell requires `powershell-yaml` and version 7.2+ for smoke cleanup; Bash
requires mikefarah `yq` v4. Site commands and Pages setup are documented in the
[site maintainer guide](docs/site/README.md).

## License

[MIT](LICENSE). Vendored skills retain their upstream licenses; see
[plugins/VENDORED.md](plugins/VENDORED.md). The canvas's bundled YAML parser
retains its [ISC license](plugins/agile-agents-core/extensions/solution-profile/yaml.LICENSE).

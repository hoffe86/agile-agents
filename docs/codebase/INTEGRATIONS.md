# Integration boundaries

The host makes tools available; the plugin tells an agent **when and for what
purpose** it may use them. Neither grants access to an external account. In
particular, the open `tools: ["*"]` declaration does not install a server,
authenticate a user or turn a reviewer into an author.

| Boundary | Information crossing it | Failure or consent boundary |
|---|---|---|
| Solution profile and canvas | The team edits facts and commands for the current checkout. The optional canvas holds a draft; explicit Save writes the profile and generates `AGENTS.md`. | Agent-facing `status` is read-only. Validation or a stale revision blocks Save. If generation fails after saving, the profile remains saved and the failure is reported. Saving runs no profile command. |
| Documentation and browser tools | Core's MCP configuration declares Context7 for library docs, Microsoft Learn for Microsoft documentation, and Playwright for browser interactions. The host may provide other tools. | A declaration is not a successful connection. Match capabilities to the task; read-only roles may inspect, not submit forms or mutate state. |
| Work-item tracker | When enabled, `backlog-manager` translates neutral task states into the solution's tracker and links provisional child items to a parent. | Creation/link failure stops planning; a later state-mirror failure is reported without declaring the work failed. With inline planning there are no tracker writes. |
| Git and code host | Authors work on feature branches; `identity.repo_url` identifies the PR host, independently of `backlog.platform`. | Respect stricter personal consent. Opening a PR needs explicit per-run permission. Merge, close, force-push and rewriting shared history are human-only. |
| Project pipeline | Opt-in `deploy-verify` considers only `environment_chain[0]`, never the final or a prod-named stage. | A prod-named first entry stops; a docs-only diff or an unreachable dev stage skips. No search for another target. The docs site's Pages workflow is not the plugin's deployment path. |
| Evidence storage | A session ledger holds tasks, dependencies, findings and criterion coverage. A separate append-only run log records phase windows and gates; the collector reads the selected session's CLI usage. | An empty valid window can measure zero; an unreadable store cannot. Never log secrets, or PII unless explicitly requested in the solution profile. No central monitoring service is required. |

Use the access already configured for the solution and host. If an operation
is not permitted, distinguish lack of service access from an unregistered tool
and from a deliberate role boundary. Adding tools does not change a human-only
operation into an allowed one.

**Evidence:** [MCP configuration](../../plugins/agile-agents-core/.mcp.json),
[profile editor](../README.md#solution-profile-canvas), [tracker hand-offs](../flow/handoffs.md),
[deploy-verify](../../plugins/agile-agents-core/skills/deploy-verify/SKILL.md),
[run log](../../plugins/agile-agents-core/skills/run-event-log/SKILL.md).

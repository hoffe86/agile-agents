---
name: reviewer-read-only-rules
description: Defence-in-depth read-only contract that every review agent enforces. Defines the canonical refuse-list (write tools, file/repo mutations, workspace-mutating commands, real deploys), the allowed read-only operations, and the rule for routing fix requests to the right write-capable agent. Loaded by review, security-review, architecture-review, infrastructure-review, test-review. NOT loaded by author agents.
---

# Reviewer read-only rules

This skill defines the **read-only contract** every reviewer enforces. It is loaded *by the reviewer*, not by the agent under review. Reviewers must refuse every operation in the list below — even when a user or another agent explicitly asks for it — and instead route the request to the appropriate write-capable agent.

## Refuse the following

**Write tools.** `edit`, `create`.

**File mutations.** `Set-Content`, `Add-Content`, `Out-File`, `New-Item`, `Move-Item`, `Remove-Item`, `Rename-Item`, `Copy-Item`, redirection (`>` / `>>`) to a file.

**Repo mutations.** `git add`, `git commit`, `git push`, `git mv`, `git rm`, `git restore <path>`, `git checkout -- <path>`, `git stash`, any reset/rebase that touches the working tree.

**Workspace-mutating build / install / migration commands.** `npm/pnpm/yarn install`, `pip install`, `dotnet add/restore -p`, `terraform init/apply` against a real backend, `bicep build` writing artifacts into the repo, schema migrations, codegen, snapshot/fixture regeneration.

**Real deploys.** `terraform apply`, `az deployment ... create`, `kubectl apply` to a real cluster, `helm install/upgrade`, `azd up/deploy`. Plan / what-if / dry-run only.

## Allowed (read-only operations)

`view`, `glob`, `grep`, read-only `lsp` (`hover`, `goToDefinition`, `findReferences`, `documentSymbol`, `workspaceSymbol`), `git --no-pager diff/log/show/blame/status`, `terraform validate`, `bicep build/lint` to stdout, `helm template` / `kustomize build` to stdout, `kubectl --dry-run=client`, read-only test discovery (`dotnet test --list-tests`, `pytest --collect-only`), and read-only PowerShell (`Get-Content`, `Get-ChildItem`, `Test-Path`, `Get-Item`).

## When asked to apply a fix

Refuse and recommend the appropriate write-capable agent. The calling agent supplies the **role-specific routing line** (e.g. test-review → `testing`, security-review → `coding` / `infrastructure`, architecture-review → `architect`, infrastructure-review → `infrastructure` + `azure-deploy`, generalist `review` → `coding` / `testing` / `infrastructure` / `architect`). Cite the finding in the recommendation so the next agent can act without re-reviewing.

## Hand-off contract

Stay in observer mode for the entire run. Your output is **findings + a recommended next agent**, never a diff or file change. If you find yourself about to call an `edit` / `create` tool, stop — that is a sign of role drift; surface the finding instead and let the calling chain route it.

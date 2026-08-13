<#
.SYNOPSIS
    Fail if an agent references a skill or MCP server that nothing ships.

.DESCRIPTION
    Six times now an agent has instructed "always load skill X" or granted tool
    "server/*" where X or server shipped nowhere in this repo. Unmatched grants
    are inert and missing skills degrade silently, so every instance survived
    review and only surfaced when someone read the file closely.

    Two checks:

      skills  Every skill named anywhere in an agent body must either ship under
              plugins/*/skills, be hedged on the same line as optional ("not
              bundled", "when installed", "if installed", "when available",
              "when present", "separately installed"), or be listed in
              $NotSkills below as a name that is not a skill at all. Hedged is
              fine — that is the documented contract for a skill the user may
              install themselves. Unhedged, unshipped and unlisted is the bug.

      servers Every namespaced tool grant (foo/bar) in an agent's `tools:`
              frontmatter must name a server defined in some plugin's .mcp.json,
              or appear in $ExternalServers below.

    The skills check reads the **whole** agent body. It used to read only the
    "Skills you compose with" section, which covered 53 of 173 references: four
    agents (architect, backlog-manager, bootstrapper, capability-scout) have no
    such heading at all and were audited not one line, and every reference made
    in stage prose — where dev-lead makes most of its own — was invisible. The
    cost of widening is small and was measured: exactly 14 non-skill kebab-case
    names surface, of which 5 are genuinely optional skills already carrying a
    hedge, leaving 9 for $NotSkills.

    Known limits — measured, not assumed:

      * A name that is both an agent and a skill (today: code-review,
        security-review) can never be validated, because backticked agent names
        are skipped so that "delegate to `test-review`" is not read as a skill.
        Delete such a skill and this script stays green. A purely name-based
        rule cannot tell "agent named in prose" from "skill that vanished".

      * The hedge list contains broad bare phrases ("external", "only when")
        that fire incidentally in prose. 71 of 2103 agent lines match a hedge,
        and on those lines every name is skipped — so a dangling reference
        sharing a line with the word "external" still slips through. Tightening
        the list is a separate change: it would re-expose every reference
        currently relying on those phrases, so it needs its own measurement.
#>
[CmdletBinding()]
param(
    [string] $RepoRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'

# Servers the harness deliberately does not ship: the user wires these up
# themselves (org-specific endpoints, credentials, subscriptions).
$ExternalServers = @(
    'ado', 'azure-devops', 'azure-devops-mcp', 'microsoft/azure-devops-mcp',
    'azure', 'azure-mcp', 'azure-mcp-server',
    'github'
)

# Pseudo-tools that are not MCP servers.
$NotServers = @('agent', 'browser', 'edit', 'execute', 'read', 'search', 'todo', 'vscode', 'web')

# Backticked kebab-case names in an agent body that are not skills: tracker
# tags, solution-profile values, ledger states, tool operations and backends.
# Kept deliberately short — every entry is a name this script can no longer
# protect, so prefer rewording the reference over adding to the list. An
# optional *skill* does not belong here: hedge it on its line instead, which
# keeps it checked against the day it ships.
$NotSkills = @(
    'what-if',          # Azure CLI / Bicep deployment operation
    'tree-sitter',      # code-localisation backend, a solution-profile value
    'pending-approval', # tracker tag on provisional tasks
    'ado-boards',       # backlog.platform value
    'azure-devops',     # platform / server name in prose
    'in-repo',          # documentation.platform value
    'c4-only',          # documentation.diagram_convention value
    'mermaid-c4',       # documentation.diagram_convention value
    'out-of-scope',     # requirement_acs status
    'accepted-risk',    # findings-ledger status
    'built-in'          # prose ("built-in fixtures")
)

$hedge = 'not bundled|when installed|is installed|if installed|when available|is available|if available|when present|is present|separately installed|may install|not shipped|does not ship|none of them ship|only when|external|without vendoring'

$agentFiles = Get-ChildItem (Join-Path $RepoRoot 'plugins') -Recurse -Filter '*.agent.md' -File -Force
if (-not $agentFiles) { throw "No agent files found under $RepoRoot/plugins" }

# Agent names and plugin names also appear in backticks inside the skills
# section ("delegate to `test-review`") and are not skills.
$agentNames  = $agentFiles | ForEach-Object { $_.BaseName -replace '\.agent$', '' }
$pluginNames = Get-ChildItem (Join-Path $RepoRoot 'plugins') -Directory | ForEach-Object { $_.Name }

$shippedSkills = Get-ChildItem (Join-Path $RepoRoot 'plugins') -Recurse -Filter 'SKILL.md' -File -Force |
    ForEach-Object { $_.Directory.Name } | Sort-Object -Unique

# -Force matters: on Linux PowerShell treats dot-files as hidden, so without it
# .mcp.json is invisible, $shippedServers comes back empty, and every grant in
# the repo is reported as unshipped.
$shippedServers = Get-ChildItem (Join-Path $RepoRoot 'plugins') -Recurse -Filter '.mcp.json' -File -Force |
    ForEach-Object { (Get-Content $_.FullName -Raw | ConvertFrom-Json).mcpServers.PSObject.Properties.Name } |
    Sort-Object -Unique
if (-not $shippedServers) { throw "No MCP servers discovered - .mcp.json lookup is broken, not the agents." }

$failures = [System.Collections.Generic.List[string]]::new()

foreach ($file in $agentFiles) {
    $rel   = $file.FullName.Substring($RepoRoot.Length + 1)
    $lines = Get-Content $file.FullName

    # --- skills -----------------------------------------------------------
    # The whole body is in scope. Section-scoping was the earlier design and it
    # audited 53 of 173 references — four agents have no skills heading at all,
    # and references made in stage prose were never read. Names that are not
    # skills (tags, profile values, ledger states) live in $NotSkills; optional
    # skills stay checked by carrying a hedge on their line.
    for ($i = 0; $i -lt $lines.Length; $i++) {
        $line = $lines[$i]
        if (-not $line.Trim()) { continue }
        if ($line -match $hedge) { continue }

        # A hedge on the line that introduces a group covers the whole
        # group, so "Skills from separately installed plugins:" followed
        # by twenty entries needs saying once, not twenty times.
        $covered = $false
        for ($j = $i - 1; $j -ge 0; $j--) {
            if (-not $lines[$j].Trim()) { continue }
            if ($lines[$j] -match '^\s*[-*]\s' -and $line -match '^\s*[-*]\s') { continue }
            $covered = $lines[$j] -match $hedge
            break
        }
        if ($covered) { continue }

        foreach ($m in [regex]::Matches($line, '`([a-z][a-z0-9]+(?:-[a-z0-9]+)+)`')) {
            $skill = $m.Groups[1].Value
            if ($skill -in $agentNames -or $skill -in $pluginNames -or $skill -in $NotSkills) { continue }
            if ($skill -notin $shippedSkills) {
                $failures.Add("$rel`:$($i + 1)  '$skill' is referenced but ships nowhere: it is not a skill under plugins/*/skills, the line does not mark it optional, and it is not listed in `$NotSkills as a non-skill name.")
            }
        }
    }

    # --- servers ----------------------------------------------------------
    $toolsLine = $lines | Select-String -Pattern '^tools:' | Select-Object -First 1
    if ($toolsLine) {
        foreach ($m in [regex]::Matches($toolsLine.Line, "['\`"]?([A-Za-z0-9._/-]+)/\*?[A-Za-z0-9._-]*['\`"]?")) {
            $grant  = $m.Groups[1].Value
            $server = $grant -replace '/.*$', ''
            if ($server -in $NotServers) { continue }
            # A server name may itself contain a slash (`microsoft/azure-devops-mcp`,
            # `microsoftdocs/mcp`), so match the whole grant before falling back to the
            # first segment. Verified: a server registered as `vendor/probesrv` is reached
            # by the grant `vendor/probesrv/*`.
            if ($grant -in $ExternalServers) { continue }
            if ($server -in $ExternalServers) { continue }
            if ($server -notin $shippedServers) {
                $failures.Add("$rel`:$($toolsLine.LineNumber)  tool grant '$grant' names server '$server', which no plugin .mcp.json defines and which is not in the external allow-list.")
            }
        }
    }
}

if ($failures.Count) {
    Write-Host "Reference audit failed:`n" -ForegroundColor Red
    $failures | Sort-Object -Unique | ForEach-Object { Write-Host "  $_" -ForegroundColor Red }
    Write-Host "`nPick the one that is true:"
    Write-Host "  * it should be a skill      -> ship it under plugins/<plugin>/skills/<name>/SKILL.md"
    Write-Host "  * it is an optional skill   -> hedge the reference on its line ('when installed',"
    Write-Host "                                 'not bundled', ...) so it degrades gracefully"
    Write-Host "  * it is not a skill at all  -> add it to `$NotSkills (names) or `$ExternalServers"
    Write-Host "                                 (MCP servers) in this script, with a comment"
    Write-Host "  * it is just prose          -> reword it so it is not in backticks"
    exit 1
}

Write-Host "Reference audit passed: $($agentFiles.Count) agents, $($shippedSkills.Count) skills, $($shippedServers.Count) MCP servers." -ForegroundColor Green

<#
.SYNOPSIS
    Fail if an agent references a skill or MCP server that nothing ships.

.DESCRIPTION
    Six times now an agent has instructed "always load skill X" or granted tool
    "server/*" where X or server shipped nowhere in this repo. Unmatched grants
    are inert and missing skills degrade silently, so every instance survived
    review and only surfaced when someone read the file closely.

    Two checks:

      skills  Every skill named in an agent's "Skills you compose with" section
              must either ship under plugins/*/skills, or be hedged
              on the same line as optional ("not bundled", "when installed",
              "if installed", "when available", "when present", "separately
              installed"). Hedged is fine — that is the documented contract for
              a skill the user may install themselves. Unhedged and unshipped
              is the bug.

      servers Every namespaced tool grant (foo/bar) in an agent's `tools:`
              frontmatter must name a server defined in some plugin's .mcp.json,
              or appear in $ExternalServers below.
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
    # Scope to the "Skills you compose with" section: elsewhere in an agent
    # body, backticked names are agent names, MCP tools, tags and prose.
    $start = ($lines | Select-String -Pattern '^#+\s*Skills you compose with' | Select-Object -First 1).LineNumber
    if ($start) {
        $end = $lines.Length
        for ($i = $start; $i -lt $lines.Length; $i++) {
            if ($lines[$i] -match '^#+\s' ) { $end = $i; break }
        }

        for ($i = $start; $i -lt $end; $i++) {
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
                if ($skill -in $agentNames -or $skill -in $pluginNames) { continue }
                if ($skill -notin $shippedSkills) {
                    $failures.Add("$rel`:$($i + 1)  skill '$skill' is referenced but ships nowhere, and neither the line nor its group lead-in marks it optional.")
                }
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
    Write-Host "`nEither ship the artifact, add it to the external allow-list in this script,"
    Write-Host "or reword the reference so the agent degrades gracefully when it is absent."
    exit 1
}

Write-Host "Reference audit passed: $($agentFiles.Count) agents, $($shippedSkills.Count) skills, $($shippedServers.Count) MCP servers." -ForegroundColor Green

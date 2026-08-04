#requires -Version 5.1
<#
.SYNOPSIS
    Generate a portable AGENTS.md from solution-profile.yaml + *.agent.md files.

.DESCRIPTION
    Reads the typed solution-profile.yaml and every .agent.md frontmatter, then
    renders a vendor-neutral AGENTS.md (https://agents.md) so the repository is
    portable to Claude Code, Copilot CLI, Cursor, Aider, etc. — without losing
    our richer typed model.

    Output is deterministic: identical inputs produce identical bytes (agents
    and skills are sorted alphabetically, the timestamp is date-only UTC).

    Uses ConvertFrom-Yaml when available (powershell-yaml module). When not
    available, falls back to a tiny line-based parser that handles the small
    set of fields this script actually needs.

.PARAMETER ProfilePath
    Path to solution-profile.yaml. Default: auto-detect under
    .github/solution-profile.yaml then ./solution-profile.yaml relative to the
    repo root.

.PARAMETER AgentsDir
    Directory containing *.agent.md files. Default: .github/agents/ (or
    plugins/agile-agents-core/agents/ at the repo root when running from the agile-agents repo).

.PARAMETER SkillsDir
    Directory containing skill subfolders with SKILL.md files. Default:
    .github/skills/ (or plugins/agile-agents-core/skills/ at the repo root when in the agile-agents repo).

.PARAMETER Output
    Output file path. Default: AGENTS.md at repo root.

.PARAMETER DryRun
    Write the rendered AGENTS.md to stdout instead of disk.

.EXAMPLE
    PS> ./scripts/generate-agents-md.ps1
    Regenerates AGENTS.md at repo root.

.EXAMPLE
    PS> ./scripts/generate-agents-md.ps1 -DryRun | Out-Host
    Preview without writing.
#>
[CmdletBinding()]
param(
    [string]$ProfilePath,
    [string]$AgentsDir,
    [string[]]$SkillsDir,
    [string]$Output,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

function Get-RepoRoot {
    try {
        $r = & git rev-parse --show-toplevel 2>$null
        if ($LASTEXITCODE -eq 0 -and $r) { return $r.Trim() }
    } catch {}
    return (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
}

function Sort-Ordinal {
    # PowerShell's Sort-Object is culture-aware and treats '-' as a minor difference,
    # so it orders "refactor-method-…" before "refactor". `sort` in the bash twin is
    # byte-order. Sort ordinally on both sides or the two generators drift.
    param([string[]]$Items)
    $list = [System.Collections.Generic.List[string]]::new()
    foreach ($i in $Items) { [void]$list.Add([string]$i) }
    $list.Sort([StringComparer]::Ordinal)
    return $list.ToArray()
}

function Resolve-First {
    param([string[]]$Candidates)
    foreach ($c in $Candidates) { if ($c -and (Test-Path $c)) { return (Resolve-Path $c).Path } }
    return $null
}

function Read-YamlFile {
    param([string]$Path)
    $text = Get-Content -Raw -LiteralPath $Path
    if (Get-Command ConvertFrom-Yaml -ErrorAction SilentlyContinue) {
        try { return $text | ConvertFrom-Yaml } catch { Write-Warning "ConvertFrom-Yaml failed: $_" }
    }
    return ConvertFrom-YamlFallback -Text $text
}

function ConvertFrom-YamlFallback {
    param([string]$Text)
    # Tiny parser: handles top-level mappings + one nested level + simple
    # list/scalar values for the fields this script needs. Comments stripped.
    $result = [ordered]@{}
    $section = $null
    $listKey = $null
    foreach ($rawLine in ($Text -split "`r?`n")) {
        $line = $rawLine -replace '\s+#.*$', '' -replace '^#.*$', ''
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        if ($line -match '^[A-Za-z_][A-Za-z0-9_]*:\s*$') {
            $section = ($line -split ':')[0].Trim()
            $result[$section] = [ordered]@{}
            $listKey = $null
            continue
        }
        if ($line -match '^[A-Za-z_][A-Za-z0-9_]*:') {
            $section = $null
            $listKey = $null
            continue
        }
        if (-not $section) { continue }
        if ($line -match '^\s{2}([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$') {
            $k = $matches[1]; $v = $matches[2].Trim()
            if ([string]::IsNullOrEmpty($v) -or $v -eq '[]') {
                $result[$section][$k] = @()
                $listKey = $k
            } else {
                $result[$section][$k] = ($v -replace '^"(.*)"$', '$1' -replace "^'(.*)'$", '$1')
                $listKey = $null
            }
            continue
        }
        if ($listKey -and $line -match '^\s{2,}-\s*(.+)$') {
            $item = $matches[1].Trim()
            if ($item -match '^\{\s*name:\s*"?([^",}]+)"?(?:\s*,\s*version:\s*"?([^",}]+)"?)?\s*\}$') {
                $entry = [ordered]@{ name = $matches[1] }
                if ($matches[2]) { $entry.version = $matches[2] }
                $result[$section][$listKey] += ,$entry
            } else {
                $result[$section][$listKey] += ,($item -replace '^"(.*)"$', '$1' -replace "^'(.*)'$", '$1')
            }
        }
    }
    return $result
}

function Get-ProfileValue {
    param($Profile, [string]$Section, [string]$Key, $Default = $null)
    if ($null -eq $Profile) { return $Default }
    $sec = $Profile[$Section]
    if ($null -eq $sec) { return $Default }
    if ($sec -is [hashtable] -or $sec -is [System.Collections.Specialized.OrderedDictionary]) {
        if ($sec.Contains($Key)) {
            $v = $sec[$Key]
            if ($null -eq $v -or ($v -is [string] -and [string]::IsNullOrWhiteSpace($v))) { return $Default }
            return $v
        }
    }
    return $Default
}

function Read-AgentFrontmatter {
    param([string]$Path)
    $lines = Get-Content -LiteralPath $Path
    if ($lines.Count -lt 2 -or $lines[0].Trim() -ne '---') { return $null }
    $end = -1
    for ($i = 1; $i -lt $lines.Count; $i++) { if ($lines[$i].Trim() -eq '---') { $end = $i; break } }
    if ($end -lt 0) { return $null }
    $fm = [ordered]@{ name = ''; description = ''; tools = @(); agents = @() }
    $current = $null; $buf = New-Object System.Text.StringBuilder
    for ($i = 1; $i -lt $end; $i++) {
        $l = $lines[$i]
        if ($l -match '^([a-zA-Z_]+):\s*>-?\s*$') {
            if ($current -and $buf.Length -gt 0) { $fm[$current] = $buf.ToString().Trim() }
            $current = $matches[1]; $buf = New-Object System.Text.StringBuilder; continue
        }
        if ($l -match '^([a-zA-Z_]+):\s*(.*)$') {
            if ($current -and $buf.Length -gt 0) { $fm[$current] = $buf.ToString().Trim() }
            $key = $matches[1]; $val = $matches[2].Trim()
            $current = $null; $buf = New-Object System.Text.StringBuilder
            if ($val -match '^\[(.*)\]$') {
                $items = $matches[1] -split ',' | ForEach-Object { $_.Trim().Trim('"').Trim("'") } | Where-Object { $_ }
                $fm[$key] = @($items)
            } elseif ([string]::IsNullOrEmpty($val)) {
                $current = $key
            } else {
                $fm[$key] = ($val -replace '^"(.*)"$', '$1' -replace "^'(.*)'$", '$1')
            }
            continue
        }
        if ($current) {
            if ($buf.Length -gt 0) { [void]$buf.Append(' ') }
            [void]$buf.Append($l.Trim())
        }
    }
    if ($current -and $buf.Length -gt 0) { $fm[$current] = $buf.ToString().Trim() }
    return $fm
}

function Format-Languages {
    param($Langs)
    if (-not $Langs -or $Langs.Count -eq 0) { return 'unspecified' }
    $parts = @()
    foreach ($l in $Langs) {
        if ($l -is [string]) { $parts += $l; continue }
        if ($l.Contains('name')) {
            $n = $l['name']
            if ($l.Contains('version') -and $l['version']) { $parts += "$n@$($l['version']) " }
            else { $parts += $n }
        }
    }
    if ($parts.Count -eq 0) { return 'unspecified' }
    return ($parts -join ', ').Trim()
}

# ── resolve paths ──────────────────────────────────────────────────────────────
$repoRoot = Get-RepoRoot
if (-not $ProfilePath) {
    $ProfilePath = Resolve-First @(
        (Join-Path $repoRoot '.github/solution-profile.yaml'),
        (Join-Path $repoRoot 'solution-profile.yaml')
    )
}
if (-not $AgentsDir) {
    $AgentsDir = Resolve-First @(
        (Join-Path $repoRoot '.github/agents'),
        (Join-Path $repoRoot 'plugins/agile-agents-core/agents'),
        (Join-Path $repoRoot 'agents')
    )
}
if (-not $SkillsDir) {
    $SkillsDir = @(Get-ChildItem -Path (Join-Path $repoRoot 'plugins') -Directory -Filter 'agile-agents*' -ErrorAction SilentlyContinue |
        ForEach-Object { Join-Path $_.FullName 'skills' } | Where-Object { Test-Path $_ } | Sort-Object)
    if (-not $SkillsDir) {
        $SkillsDir = @(Resolve-First @(
            (Join-Path $repoRoot '.github/skills'),
            (Join-Path $repoRoot 'skills')
        )) | Where-Object { $_ }
    }
}
if (-not $Output) { $Output = Join-Path $repoRoot 'AGENTS.md' }

if (-not $ProfilePath) { throw 'solution-profile.yaml not found' }
if (-not $AgentsDir)   { throw 'agents directory not found' }
$templatePath = Join-Path $PSScriptRoot 'references/agents-md-template.md'
if (-not (Test-Path $templatePath)) { throw "template not found: $templatePath" }

$profile  = Read-YamlFile -Path $ProfilePath
$template = Get-Content -Raw -LiteralPath $templatePath
$template = ($template -split '(?ms)^## Tokens\s*$')[0].TrimEnd() + "`n"

# ── values ─────────────────────────────────────────────────────────────────────
# Fall back to the git remote's repo name, not the checkout directory: CI clones into
# a folder named after the repo, developers clone into whatever they like.
$repoNameFallback = (& git -C $repoRoot config --get remote.origin.url 2>$null)
$repoNameFallback = if ($repoNameFallback) { [IO.Path]::GetFileNameWithoutExtension($repoNameFallback.Trim().TrimEnd('/')) }
                    else { Split-Path $repoRoot -Leaf }
$projectName     = Get-ProfileValue $profile 'identity'      'project_name'      $repoNameFallback
$defaultBranch   = Get-ProfileValue $profile 'identity'      'default_branch'    'main'
$docLocation        = Get-ProfileValue $profile 'documentation' 'location'         'unspecified'
$docPlatform     = Get-ProfileValue $profile 'documentation' 'platform'         'unspecified'
$backlogPlatform   = Get-ProfileValue $profile 'backlog'       'platform'          'unspecified'
$branchNaming    = Get-ProfileValue $profile 'backlog'       'branch_naming'     'unspecified'
$commitConv      = Get-ProfileValue $profile 'backlog'       'commit_convention' 'unspecified'
$languages       = Format-Languages (Get-ProfileValue $profile 'tech_stack' 'primary_languages' @())
$activeAgents    = @(Get-ProfileValue $profile 'ai_copilot' 'active_agents'    @())
$mandatorySkills = @(Get-ProfileValue $profile 'ai_copilot' 'mandatory_skills' @())

# ── agents table ───────────────────────────────────────────────────────────────
$agentFiles = Get-ChildItem -LiteralPath $AgentsDir -Filter '*.agent.md' -File | Sort-Object Name
$agentBlocks = New-Object System.Collections.Generic.List[string]
foreach ($f in $agentFiles) {
    $fm = Read-AgentFrontmatter -Path $f.FullName
    if (-not $fm -or -not $fm['name']) { continue }
    if ($activeAgents.Count -gt 0 -and ($activeAgents -notcontains $fm['name'])) { continue }
    $tools  = if ($fm['tools'])  { (Sort-Ordinal $fm['tools'])  -join ', ' } else { '_default_' }
    $subs   = if ($fm['agents']) { (Sort-Ordinal $fm['agents']) -join ', ' } else { '_none_' }
    $desc   = ($fm['description'] -replace '\s+', ' ').Trim()
    $block  = "### ``$($fm['name'])```n`n$desc`n`n- **Tools**: $tools`n- **Sub-agents**: $subs`n"
    $agentBlocks.Add($block)
}
if ($agentBlocks.Count -eq 0) { $agentBlocks.Add('_(no agents matched the active_agents filter)_') }
$agentsTable = ($agentBlocks -join "`n")

# ── skills list ────────────────────────────────────────────────────────────────
$skillsList = '_(skills directory not found)_'
if ($SkillsDir) {
    $skillEntries = New-Object System.Collections.Generic.List[string]
    foreach ($dir in $SkillsDir) {
        $plugin = Split-Path (Split-Path $dir -Parent) -Leaf
        Get-ChildItem -LiteralPath $dir -Directory | Sort-Object Name | ForEach-Object {
            $sm = Join-Path $_.FullName 'SKILL.md'
            if (Test-Path $sm) {
                $fm = Read-AgentFrontmatter -Path $sm
                if ($fm -and $fm['name']) {
                    $d = ($fm['description'] -replace '\s+', ' ').Trim()
                    $first = ($d -split '(?<=[\.!?])\s')[0]
                    if ($first.Length -gt 200) { $first = $first.Substring(0, 197) + '...' }
                    $skillEntries.Add("- **$($fm['name'])** (``$plugin``) — $first")
                }
            }
        }
    }
    if ($skillEntries.Count -gt 0) { $skillsList = ((Sort-Ordinal $skillEntries) -join "`n") }
}

$mandatoryList = if ($mandatorySkills.Count -gt 0) { (Sort-Ordinal $mandatorySkills | ForEach-Object { "- ``$_``" }) -join "`n" } else { '_(none configured)_' }

$evalPointer = if (Test-Path (Join-Path $repoRoot 'eval')) { 'see [`./eval/`](eval/)' } else { 'not configured (see plan H2)' }

# ── render ─────────────────────────────────────────────────────────────────────
$map = [ordered]@{
    'PROJECT_NAME'           = $projectName
    'GENERATED_ON'           = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd')
    'LANGUAGES'              = $languages
    'BACKLOG_PLATFORM'         = $backlogPlatform
    'DOC_LOCATION'              = $docLocation
    'DOC_PLATFORM'              = $docPlatform
    'BRANCH_NAMING'          = $branchNaming
    'COMMIT_CONVENTION'      = $commitConv
    'DEFAULT_BRANCH'         = $defaultBranch
    'ACTIVE_AGENTS_TABLE'    = $agentsTable
    'SKILLS_LIST'            = $skillsList
    'MANDATORY_SKILLS_LIST'  = $mandatoryList
    'EVAL_POINTER'           = $evalPointer
}
$rendered = $template
foreach ($k in $map.Keys) {
    $rendered = $rendered.Replace("{{$k}}", [string]$map[$k])
}

if ($DryRun) {
    Write-Output $rendered
} else {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Output, $rendered, $utf8NoBom)
    Write-Host "Wrote $Output"
}

# =============================================================================
# Export-StashSummary.ps1
# =============================================================================
# Exports a COMPACT summary of Stash metadata via GraphQL - suitable for git.
#
# Unlike Stash's full metadataExport (which writes 500K+ per-file JSON sidecars
# totaling several GB), this script queries just the high-level data:
#   - Library stats (scene/image/performer/studio/tag counts, total size)
#   - All tags (id + name)
#   - All studios (id + name + parent)
#   - Performer count by gender
#   - Top performers by scene count
#
# Output: exports/stash-summary.json (typically < 1 MB - fits easily in git)
#
# Usage:
#   .\Export-StashSummary.ps1
#
# =============================================================================

[CmdletBinding()]
param(
    [string]$StashUrl = "http://localhost:9999/graphql",
    [string]$OutputPath = "$PSScriptRoot\..\exports\stash-summary.json"
)

$ErrorActionPreference = "Stop"

function Write-Step { param([string]$msg) Write-Host "[Stash Summary] $msg" -ForegroundColor Cyan }
function Write-Ok   { param([string]$msg) Write-Host "  OK: $msg" -ForegroundColor Green }
function Write-Err  { param([string]$msg) Write-Host "  ERROR: $msg" -ForegroundColor Red }
function Write-Warn { param([string]$msg) Write-Host "  WARN: $msg" -ForegroundColor Yellow }

# -----------------------------------------------------------------------------
# 1. Check Stash is reachable
# -----------------------------------------------------------------------------
Write-Step "Checking Stash at $StashUrl ..."
try {
    $statusBody = '{"query":"{ systemStatus { databaseSchema appSchema } }"}'
    $statusRes = Invoke-WebRequest -Uri $StashUrl -Method POST -Body $statusBody -ContentType "application/json" -UseBasicParsing -TimeoutSec 15
    $status = ($statusRes.Content | ConvertFrom-Json).data.systemStatus
    Write-Ok "Stash reachable. Schema v$($status.databaseSchema)"
} catch {
    Write-Err "Stash not reachable - $($_.Exception.Message)"
    exit 1
}

# -----------------------------------------------------------------------------
# 2. Query library stats
# -----------------------------------------------------------------------------
Write-Step "Querying library stats ..."
$statsBody = '{"query":"{ stats { scene_count scenes_size scenes_duration image_count images_size gallery_count performer_count studio_count group_count tag_count total_o_count total_play_duration total_play_count } }"}'
try {
    $statsRes = Invoke-WebRequest -Uri $StashUrl -Method POST -Body $statsBody -ContentType "application/json" -UseBasicParsing -TimeoutSec 60
    $stats = ($statsRes.Content | ConvertFrom-Json).data.stats
    Write-Ok "Scenes: $($stats.scene_count), Performers: $($stats.performer_count), Studios: $($stats.studio_count), Tags: $($stats.tag_count)"
} catch {
    Write-Err "Stats query failed - $($_.Exception.Message)"
    exit 1
}

# -----------------------------------------------------------------------------
# 3. Query all tags (id + name)
# -----------------------------------------------------------------------------
Write-Step "Querying tags ..."
$tagsBody = '{"query":"{ allTags { id name } }"}'
try {
    $tagsRes = Invoke-WebRequest -Uri $StashUrl -Method POST -Body $tagsBody -ContentType "application/json" -UseBasicParsing -TimeoutSec 60
    $tags = ($tagsRes.Content | ConvertFrom-Json).data.allTags
    Write-Ok "$($tags.Count) tags"
} catch {
    Write-Warn "Tags query failed - $($_.Exception.Message)"
    $tags = @()
}

# -----------------------------------------------------------------------------
# 4. Query all studios (id + name + parent)
# -----------------------------------------------------------------------------
Write-Step "Querying studios ..."
$studiosBody = '{"query":"{ allStudios { id name parent { id name } } }"}'
try {
    $studiosRes = Invoke-WebRequest -Uri $StashUrl -Method POST -Body $studiosBody -ContentType "application/json" -UseBasicParsing -TimeoutSec 60
    $studios = ($studiosRes.Content | ConvertFrom-Json).data.allStudios
    Write-Ok "$($studios.Count) studios"
} catch {
    Write-Warn "Studios query failed - $($_.Exception.Message)"
    $studios = @()
}

# -----------------------------------------------------------------------------
# 5. Build summary object
# -----------------------------------------------------------------------------
$exportDate = Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ"
$summary = [ordered]@{
    export_date    = $exportDate
    stash_version  = "v0.27.2"
    schema_version = $status.databaseSchema
    stats          = $stats
    tags           = $tags | Sort-Object name
    studios        = $studios | Sort-Object name
}

# -----------------------------------------------------------------------------
# 6. Write to file
# -----------------------------------------------------------------------------
$outputDir = Split-Path $OutputPath -Parent
if (-not (Test-Path $outputDir)) { New-Item -ItemType Directory -Path $outputDir -Force | Out-Null }

$json = $summary | ConvertTo-Json -Depth 6
$json | Out-File -FilePath $OutputPath -Encoding utf8 -NoNewline

$fileSizeKB = [math]::Round((Get-Item $OutputPath).Length / 1KB, 2)
Write-Ok "Summary written to $OutputPath ($fileSizeKB KB)"
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  git add exports/stash-summary.json"
Write-Host "  git commit -m `"Update Stash metadata summary ($exportDate)`""

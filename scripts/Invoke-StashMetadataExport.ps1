# =============================================================================
# Invoke-StashMetadataExport.ps1
# =============================================================================
# Triggers Stash's built-in JSON metadata export via GraphQL.
# Output goes to the configured export directory (defaults to D:\Stash\metadata\export
# based on the metadata path in config.yml).
#
# The JSON export is small, text-based, and diffable - safe to commit to git.
# It contains performers, scenes, studios, tags, galleries, markers, groups.
#
# Usage:
#   .\Invoke-StashMetadataExport.ps1
#   .\Invoke-StashMetadataExport.ps1 -PollInterval 10 -Timeout 600
#
# After export completes, copy the JSON files into ./exports/ and commit:
#   Copy-Item "D:\Stash\metadata\export\*" -Destination ".\exports\" -Recurse -Force
#   git add exports/
#   git commit -m "Update Stash metadata export"
#
# =============================================================================

[CmdletBinding()]
param(
    [string]$StashUrl = "http://localhost:9999/graphql",
    [int]$PollInterval = 5,
    [int]$Timeout = 600
)

$ErrorActionPreference = "Stop"

function Write-Step { param([string]$msg) Write-Host "[Stash Export] $msg" -ForegroundColor Cyan }
function Write-Ok   { param([string]$msg) Write-Host "  OK: $msg" -ForegroundColor Green }
function Write-Err  { param([string]$msg) Write-Host "  ERROR: $msg" -ForegroundColor Red }
function Write-Warn { param([string]$msg) Write-Host "  WARN: $msg" -ForegroundColor Yellow }

# -----------------------------------------------------------------------------
# 1. Trigger metadataExport mutation
# -----------------------------------------------------------------------------
Write-Step "Triggering metadataExport mutation ..."
$exportBody = '{"query":"mutation { metadataExport }"}'
try {
    $res = Invoke-WebRequest -Uri $StashUrl -Method POST -Body $exportBody -ContentType "application/json" -UseBasicParsing -TimeoutSec 30
    $jobId = ($res.Content | ConvertFrom-Json).data.metadataExport
    Write-Ok "Export job started (job ID: $jobId)"
} catch {
    Write-Err "metadataExport mutation failed - $($_.Exception.Message)"
    exit 1
}

# -----------------------------------------------------------------------------
# 2. Poll job status until complete
# -----------------------------------------------------------------------------
Write-Step "Polling job status (every $PollInterval s, timeout $Timeout s) ..."
$elapsed = 0
$jobBody = "{`"query`":`"query { jobStatus(input: { id: \`"$jobId\`" }) { status progress } }`"}"

while ($elapsed -lt $Timeout) {
    Start-Sleep -Seconds $PollInterval
    $elapsed += $PollInterval
    try {
        $jobRes = Invoke-WebRequest -Uri $StashUrl -Method POST -Body $jobBody -ContentType "application/json" -UseBasicParsing -TimeoutSec 10
        $jobStatus = ($jobRes.Content | ConvertFrom-Json).data.jobStatus
        $status = $jobStatus.status
        $progress = $jobStatus.progress
        if ($progress) {
            $pct = [math]::Round($progress * 100, 1)
            Write-Host "  [$($elapsed)s] $status - $pct%" -ForegroundColor Gray
        } else {
            Write-Host "  [$($elapsed)s] $status" -ForegroundColor Gray
        }
        if ($status -eq "FINISHED") {
            Write-Ok "Export complete!"
            Write-Host ""
            Write-Host "Next steps:" -ForegroundColor Yellow
            Write-Host "  1. Locate the export in your Stash metadata directory (likely D:\Stash\metadata\export\)"
            Write-Host "  2. Copy to this repo:"
            Write-Host '     Copy-Item "D:\Stash\metadata\export\*" -Destination ".\exports\" -Recurse -Force'
            Write-Host "  3. Commit:"
            Write-Host '     git add exports/ && git commit -m "Update Stash metadata export"'
            exit 0
        }
        if ($status -eq "FAILED" -or $status -eq "CANCELLED") {
            Write-Err "Export job $status"
            exit 1
        }
    } catch {
        Write-Warn "Poll failed (will retry): $($_.Exception.Message)"
    }
}

Write-Err "Timed out after $Timeout seconds. Export may still be running - check Stash UI."
exit 1

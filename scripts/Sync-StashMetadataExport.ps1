# =============================================================================
# Sync-StashMetadataExport.ps1
# =============================================================================
# Copies curated Stash metadata from the full export to the git repo,
# stripping regenerable data so it fits in git.
#
# What gets copied (curated, non-regenerable):
#   - scenes/      (minus cover images - base64 bloat)
#   - performers/
#   - studios/
#   - tags/
#   - galleries/
#   - movies/
#
# What is NOT copied (regenerable by re-scanning):
#   - files/       (technical file metadata: codec, duration, fingerprints)
#   - images/      (per-image file paths and gallery associations)
#   - cover images (base64 in scene JSONs - re-extracted during scan)
#
# Usage:
#   .\Sync-StashMetadataExport.ps1
#   .\Sync-StashMetadataExport.ps1 -SourceDir "D:\Stash\metadata" -DestDir "..\exports"
#
# =============================================================================

[CmdletBinding()]
param(
    [string]$SourceDir = "D:\Stash\metadata",
    [string]$DestDir = "$PSScriptRoot\..\exports",
    [string[]]$CuratedDirs = @("scenes", "performers", "studios", "tags", "galleries", "movies")
)

$ErrorActionPreference = "Stop"

function Write-Step { param([string]$msg) Write-Host "[Sync] $msg" -ForegroundColor Cyan }
function Write-Ok   { param([string]$msg) Write-Host "  OK: $msg" -ForegroundColor Green }
function Write-Warn { param([string]$msg) Write-Host "  WARN: $msg" -ForegroundColor Yellow }
function Write-Err  { param([string]$msg) Write-Host "  ERROR: $msg" -ForegroundColor Red }

# -----------------------------------------------------------------------------
# 1. Verify source exists
# -----------------------------------------------------------------------------
if (-not (Test-Path $SourceDir)) {
    Write-Err "Source directory not found: $SourceDir"
    Write-Err "Run the Stash metadata export first (Invoke-StashMetadataExport.ps1)"
    exit 1
}

$destFull = (Resolve-Path -Path $DestDir -ErrorAction SilentlyContinue).Path
if (-not $destFull) {
    $destFull = (New-Item -ItemType Directory -Path $DestDir -Force).FullName
}
Write-Step "Source: $SourceDir"
Write-Step "Dest:   $destFull"

# -----------------------------------------------------------------------------
# 2. Process each curated directory
# -----------------------------------------------------------------------------
$totalFiles = 0
$totalSavedBytes = 0
$stripCover = $true  # Only scenes have cover images

foreach ($dirName in $CuratedDirs) {
    $srcPath = Join-Path $SourceDir $dirName
    $destPath = Join-Path $destFull $dirName

    if (-not (Test-Path $srcPath)) {
        Write-Warn "$dirName : source directory not found, skipping"
        continue
    }

    $files = Get-ChildItem -LiteralPath $srcPath -File -ErrorAction SilentlyContinue
    if ($files.Count -eq 0) {
        Write-Warn "$dirName : no files (export may not have reached this type yet)"
        continue
    }

    # Create destination directory
    if (-not (Test-Path $destPath)) {
        New-Item -ItemType Directory -Path $destPath -Force | Out-Null
    }

    $shouldStripCover = ($dirName -eq "scenes")
    $dirFiles = 0
    $dirSavedBytes = 0

    Write-Step "Processing $dirName ($($files.Count) files)$(if ($shouldStripCover) { ' - stripping cover images' })..."

    foreach ($f in $files) {
        $destFile = Join-Path $destPath $f.Name

        if ($shouldStripCover) {
            # Read raw text, strip cover field via string manipulation
            # The cover field is: "cover":"<base64 string>",
            # Using [System.IO.File] for speed with large files
            $raw = Get-Content -LiteralPath $f.FullName -Raw -Encoding UTF8
            $originalLen = $raw.Length

            # Find "cover": " and remove everything up to the closing quote+comma
            # Stash exports use: "cover": "<base64>",
            $coverKey = '"cover"'
            $coverIdx = $raw.IndexOf($coverKey)
            if ($coverIdx -ge 0) {
                # Find the colon after "cover"
                $colonIdx = $raw.IndexOf(':', $coverIdx + $coverKey.Length)
                # Find the opening quote of the value (skip whitespace)
                $openQuoteIdx = $raw.IndexOf('"', $colonIdx + 1)
                # Find the end of the base64 value (next quote - base64 has no quotes)
                $valueStart = $openQuoteIdx + 1
                # Base64 strings don't contain quotes, so the next quote is the end
                $valueEnd = $raw.IndexOf('"', $valueStart)
                if ($valueEnd -ge 0) {
                    # Check if there's a comma after the closing quote
                    $afterQuote = $valueEnd + 1
                    if ($afterQuote -lt $raw.Length -and $raw[$afterQuote] -eq ',') {
                        $afterQuote++
                    }
                    # Remove from coverIdx to afterQuote (includes the comma)
                    $cleanJson = $raw.Substring(0, $coverIdx) + $raw.Substring($afterQuote)
                    Set-Content -LiteralPath $destFile -Value $cleanJson -Encoding UTF8 -NoNewline
                    $dirSavedBytes += ($originalLen - $cleanJson.Length)
                } else {
                    # Can't find end - copy as-is
                    Copy-Item -LiteralPath $f.FullName -Destination $destFile -Force
                }
            } else {
                # No cover field - copy as-is
                Copy-Item -LiteralPath $f.FullName -Destination $destFile -Force
            }
        } else {
            # Copy as-is for non-scene directories
            Copy-Item -LiteralPath $f.FullName -Destination $destFile -Force
        }

        $dirFiles++
    }

    $totalFiles += $dirFiles
    $totalSavedBytes += $dirSavedBytes
    $savedMB = [math]::Round($dirSavedBytes / 1MB, 1)
    Write-Ok "$dirName : $dirFiles files copied$(if ($shouldStripCover -and $dirSavedBytes -gt 0) { ", $savedMB MB saved by stripping covers" })"
}

# -----------------------------------------------------------------------------
# 3. Summary
# -----------------------------------------------------------------------------
Write-Host ""
Write-Host "=== Sync complete ===" -ForegroundColor Green
Write-Host "  Files copied:  $totalFiles"
if ($totalSavedBytes -gt 0) {
    $savedMB = [math]::Round($totalSavedBytes / 1MB, 1)
    Write-Host "  Space saved:   $savedMB MB (by stripping cover images)"
}
$destSize = [math]::Round((Get-ChildItem -LiteralPath $destFull -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum / 1MB, 1)
Write-Host "  Total in repo: $destSize MB"
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  git add exports/"
Write-Host "  git commit -m `"Add Stash curated metadata export (covers stripped)`""

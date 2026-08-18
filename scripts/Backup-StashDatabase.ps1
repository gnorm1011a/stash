# =============================================================================
# Backup-StashDatabase.ps1
# =============================================================================
# Safely backs up the Stash SQLite database while Stash is running.
#
# Flow:
#   1. Call Stash GraphQL backupDatabase mutation (SQLite online backup API)
#   2. Find the timestamped backup file Stash created
#   3. Compress with 7-Zip (4 GB -> ~1-1.5 GB)
#   4. Copy the .7z to the NAS backup directory
#   5. Clean up the uncompressed backup (keep the .7z)
#
# Usage:
#   .\Backup-StashDatabase.ps1
#   .\Backup-StashDatabase.ps1 -KeepLocalCopy   # also keep .7z in .stash\backups
#
# Scheduled Task (run weekly, Sundays 3 AM):
#   $action = New-ScheduledTaskAction -Execute "powershell.exe" `
#       -Argument "-NoProfile -ExecutionPolicy Bypass -File `"C:\Users\adam\Repos\stash-config\scripts\Backup-StashDatabase.ps1`""
#   $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 3am
#   $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries
#   Register-ScheduledTask -TaskName "Stash DB Backup" -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest
#
# =============================================================================

[CmdletBinding()]
param(
    [string]$StashUrl = "http://localhost:9999/graphql",
    [string]$StashConfigDir = "C:\Users\adam\.stash",
    [string]$BackupDestDir = "\\192.168.0.31\Media\Backups\Stash",
    [string]$SevenZipPath = "C:\Program Files\7-Zip\7z.exe",
    [switch]$KeepLocalCopy,
    [int]$RetainRemoteBackups = 8
)

$ErrorActionPreference = "Stop"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

function Write-Step { param([string]$msg) Write-Host "[Stash Backup $timestamp] $msg" -ForegroundColor Cyan }
function Write-Ok   { param([string]$msg) Write-Host "  OK: $msg" -ForegroundColor Green }
function Write-Warn { param([string]$msg) Write-Host "  WARN: $msg" -ForegroundColor Yellow }
function Write-Err  { param([string]$msg) Write-Host "  ERROR: $msg" -ForegroundColor Red }

# -----------------------------------------------------------------------------
# 1. Verify Stash is reachable
# -----------------------------------------------------------------------------
Write-Step "Checking Stash at $StashUrl ..."
try {
    $statusBody = '{"query":"{ systemStatus { databaseSchema databasePath appSchema configPath } }"}'
    $statusRes = Invoke-WebRequest -Uri $StashUrl -Method POST -Body $statusBody -ContentType "application/json" -UseBasicParsing -TimeoutSec 10
    $status = ($statusRes.Content | ConvertFrom-Json).data.systemStatus
    Write-Ok "Stash reachable. Schema v$($status.databaseSchema), DB: $($status.databasePath)"
} catch {
    Write-Err "Stash not reachable at $StashUrl - $($_.Exception.Message)"
    exit 1
}

# -----------------------------------------------------------------------------
# 2. Record pre-backup file list (to detect the new backup file)
# -----------------------------------------------------------------------------
$dbDir = Split-Path $status.databasePath -Parent
$dbName = Split-Path $status.databasePath -Leaf
$preBackupFiles = Get-ChildItem -Path $dbDir -Filter "$dbName.*" -File | Where-Object { $_.Name -notmatch '-(shm|wal)$' } | Select-Object -ExpandProperty Name

# -----------------------------------------------------------------------------
# 3. Call backupDatabase mutation (safe on live DB via SQLite online backup API)
# -----------------------------------------------------------------------------
Write-Step "Triggering backupDatabase mutation (SQLite online backup) ..."
$backupBody = '{"query":"mutation { backupDatabase(input: { download: false }) }"}'
try {
    $backupRes = Invoke-WebRequest -Uri $StashUrl -Method POST -Body $backupBody -ContentType "application/json" -UseBasicParsing -TimeoutSec 600
    $backupResult = ($backupRes.Content | ConvertFrom-Json).data.backupDatabase
    # Mutation returns null on success (file written to disk); path is in the filesystem
    if ($backupResult) {
        Write-Ok "Backup returned path: $backupResult"
    } else {
        Write-Ok "Backup mutation completed (null return is normal - file written to disk)"
    }
} catch {
    Write-Err "backupDatabase mutation failed - $($_.Exception.Message)"
    exit 1
}

# -----------------------------------------------------------------------------
# 4. Find the new backup file (newest timestamped copy, excluding live DB + WAL/SHM)
# -----------------------------------------------------------------------------
Start-Sleep -Seconds 2  # let filesystem settle
$postBackupFiles = Get-ChildItem -Path $dbDir -Filter "$dbName.*" -File | Where-Object { $_.Name -notmatch '-(shm|wal)$' }
$newFiles = $postBackupFiles | Where-Object { $_.Name -notin $preBackupFiles }

if (-not $newFiles) {
    # Fallback: pick the newest timestamped file that isn't the live DB
    $newFiles = $postBackupFiles | Where-Object { $_.Name -ne $dbName } | Sort-Object LastWriteTime -Descending | Select-Object -First 1
}

if (-not $newFiles) {
    Write-Err "Could not locate the backup file Stash created."
    exit 1
}

$backupFile = $newFiles | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$backupSizeGB = [math]::Round($backupFile.Length / 1GB, 2)
Write-Ok "Backup file: $($backupFile.FullName) ($backupSizeGB GB)"

# -----------------------------------------------------------------------------
# 5. Compress with 7-Zip
# -----------------------------------------------------------------------------
if (-not (Test-Path $SevenZipPath)) {
    Write-Err "7-Zip not found at $SevenZipPath. Install 7-Zip or update `$SevenZipPath."
    exit 1
}

$archiveName = "stash-db_$timestamp.7z"
$localBackupsDir = Join-Path $StashConfigDir "backups"
if (-not (Test-Path $localBackupsDir)) { New-Item -ItemType Directory -Path $localBackupsDir -Force | Out-Null }
$archivePath = Join-Path $localBackupsDir $archiveName

Write-Step "Compressing with 7-Zip -> $archivePath ..."
$7zArgs = @("a", "-t7z", "-mx5", "-mmt=on", $archivePath, $backupFile.FullName)
$7zOut = & $SevenZipPath @7zArgs 2>&1
$7zExit = $LASTEXITCODE
if ($7zExit -ne 0) {
    Write-Err "7-Zip failed (exit $7zExit). Output:"
    $7zOut | ForEach-Object { Write-Host "    $_" }
    exit 1
}
$archiveSizeGB = [math]::Round((Get-Item $archivePath).Length / 1GB, 2)
$ratio = [math]::Round((Get-Item $archivePath).Length / $backupFile.Length * 100, 1)
Write-Ok "Archive: $archivePath ($archiveSizeGB GB, $ratio% of original)"

# -----------------------------------------------------------------------------
# 6. Copy to NAS backup directory
# -----------------------------------------------------------------------------
if (-not (Test-Path $BackupDestDir)) {
    Write-Step "Creating remote backup dir: $BackupDestDir ..."
    try {
        New-Item -ItemType Directory -Path $BackupDestDir -Force | Out-Null
    } catch {
        Write-Warn "Could not create $BackupDestDir - $($_.Exception.Message)"
        Write-Warn "Archive kept locally at $archivePath"
        if (-not $KeepLocalCopy) {
            Write-Warn "Re-run with -KeepLocalCopy to retain it, or copy manually."
        }
        exit 2
    }
}

Write-Step "Copying to NAS: $BackupDestDir ..."
try {
    Copy-Item -Path $archivePath -Destination $BackupDestDir -Force
    $remoteArchive = Join-Path $BackupDestDir $archiveName
    if (Test-Path $remoteArchive) {
        $remoteSizeGB = [math]::Round((Get-Item $remoteArchive).Length / 1GB, 2)
        Write-Ok "Remote copy: $remoteArchive ($remoteSizeGB GB)"
    } else {
        Write-Warn "Remote copy verification failed - check NAS manually."
    }
} catch {
    Write-Warn "Copy to NAS failed - $($_.Exception.Message)"
    Write-Warn "Archive kept locally at $archivePath"
    exit 2
}

# -----------------------------------------------------------------------------
# 7. Clean up uncompressed backup file
# -----------------------------------------------------------------------------
Write-Step "Cleaning up uncompressed backup ..."
try {
    Remove-Item $backupFile.FullName -Force
    Write-Ok "Removed $($backupFile.Name)"
} catch {
    Write-Warn "Could not remove $($backupFile.FullName) - $($_.Exception.Message)"
}

# Remove local .7z unless -KeepLocalCopy
if (-not $KeepLocalCopy) {
    try {
        Remove-Item $archivePath -Force
        Write-Ok "Removed local archive (remote copy retained)"
    } catch {
        Write-Warn "Could not remove local $archivePath - $($_.Exception.Message)"
    }
}

# -----------------------------------------------------------------------------
# 8. Rotate remote backups (keep last N)
# -----------------------------------------------------------------------------
if ($RetainRemoteBackups -gt 0) {
    Write-Step "Rotating remote backups (keep last $RetainRemoteBackups) ..."
    $remoteBackups = Get-ChildItem -Path $BackupDestDir -Filter "stash-db_*.7z" | Sort-Object LastWriteTime -Descending
    $toRemove = $remoteBackups | Select-Object -Skip $RetainRemoteBackups
    if ($toRemove) {
        $toRemove | ForEach-Object {
            try {
                Remove-Item $_.FullName -Force
                Write-Ok "Removed old remote backup: $($_.Name)"
            } catch {
                Write-Warn "Could not remove $($_.FullName) - $($_.Exception.Message)"
            }
        }
    } else {
        Write-Ok "No old backups to rotate ($($remoteBackups.Count) retained)"
    }
}

# -----------------------------------------------------------------------------
# Done
# -----------------------------------------------------------------------------
Write-Host ""
Write-Host "=== Backup complete ===" -ForegroundColor Green
Write-Host "  Archive:  $archiveName ($archiveSizeGB GB compressed from $backupSizeGB GB)"
Write-Host "  Remote:   $BackupDestDir\$archiveName"
Write-Host "  Retained: $RetainRemoteBackups remote backups"

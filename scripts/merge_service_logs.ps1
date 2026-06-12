# merge_service_logs.ps1
# Run as Administrator to merge integrity_log.jsonl from the NSSM service
# profile (LocalSystem) into the canonical user path.
#
# Usage (Admin PowerShell):
#   cd "C:\Users\riley\OneDrive\Documents\Python Project\finlens"
#   .\scripts\merge_service_logs.ps1

$canonicalLog  = "C:\Users\riley\.finlens\integrity_log.jsonl"
$serviceLog    = "C:\Windows\System32\config\systemprofile\.finlens\integrity_log.jsonl"
$cvCacheCanon  = "C:\Users\riley\.finlens\cv_cache.json"
$cvCacheSvc    = "C:\Windows\System32\config\systemprofile\.finlens\cv_cache.json"
$timestamp     = Get-Date -Format "yyyyMMdd_HHmmss"

function Backup-File($path) {
    if (Test-Path $path) {
        $bak = "$path.merge_backup_$timestamp"
        Copy-Item $path $bak -Force
        Write-Output "  Backed up: $path -> $bak"
    }
}

# ── integrity_log.jsonl merge ────────────────────────────────────────────────
Write-Output "`n=== Merging integrity_log.jsonl ==="

if (-not (Test-Path $serviceLog)) {
    Write-Output "Service log not found at: $serviceLog"
    Write-Output "Nothing to merge."
} else {
    Backup-File $canonicalLog
    Backup-File $serviceLog

    # Read all lines from both files, parse timestamps, sort, deduplicate
    $canonLines  = if (Test-Path $canonicalLog) { Get-Content $canonicalLog -Encoding UTF8 } else { @() }
    $svcLines    = Get-Content $serviceLog -Encoding UTF8
    $allLines    = ($canonLines + $svcLines) | Where-Object { $_.Trim() -ne "" }

    $parsed = @()
    foreach ($line in $allLines) {
        try {
            $obj = $line | ConvertFrom-Json
            $ts  = [datetime]::Parse($obj.timestamp)
            $parsed += [PSCustomObject]@{ Line = $line; Ts = $ts }
        } catch {
            Write-Output "  Skipping unparseable line: $($line.Substring(0, [Math]::Min(60, $line.Length)))..."
        }
    }

    # Deduplicate by exact line content, then sort by timestamp
    $deduped = $parsed | Sort-Object -Property { $_.Line } -Unique | Sort-Object Ts

    $mergedLines = $deduped | ForEach-Object { $_.Line }
    $mergedLines | Set-Content $canonicalLog -Encoding UTF8
    Write-Output "  Merged $($canonLines.Count) canonical + $($svcLines.Count) service lines -> $($mergedLines.Count) unique entries"
    Write-Output "  Written to: $canonicalLog"
}

# ── cv_cache.json merge ──────────────────────────────────────────────────────
Write-Output "`n=== Merging cv_cache.json ==="

if (-not (Test-Path $cvCacheSvc)) {
    Write-Output "Service cv_cache not found. Nothing to merge."
} else {
    Backup-File $cvCacheCanon
    Backup-File $cvCacheSvc

    $canonCache = if (Test-Path $cvCacheCanon) { (Get-Content $cvCacheCanon -Raw | ConvertFrom-Json) } else { @{} }
    $svcCache   = Get-Content $cvCacheSvc -Raw | ConvertFrom-Json

    # Merge: service entries fill gaps; canonical entries win on conflict
    $svcCache.PSObject.Properties | ForEach-Object {
        if (-not $canonCache.PSObject.Properties[$_.Name]) {
            $canonCache | Add-Member -NotePropertyName $_.Name -NotePropertyValue $_.Value
        }
    }

    $canonCache | ConvertTo-Json -Depth 10 | Set-Content $cvCacheCanon -Encoding UTF8
    Write-Output "  Merged cv_cache.json -> $cvCacheCanon"
}

Write-Output "`nDone. Verify with /integrity-log."

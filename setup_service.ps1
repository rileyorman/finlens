# FinLens Windows Service Setup
# Run this in an Administrator PowerShell window.

$ErrorActionPreference = "Stop"

$NssmDir     = "C:\nssm"
$NssmExe     = "$NssmDir\nssm.exe"
$ServiceName = "FinLens"
$AppDir      = "C:\Users\riley\OneDrive\Documents\Python Project\finlens"
$PythonExe   = "C:\Users\riley\AppData\Local\Programs\Python\Python313\python.exe"
$AppArgs     = "-m streamlit run `"$AppDir\app.py`" --server.headless true --browser.serverAddress localhost --server.port 8501"

# -- Step 1: Download and extract NSSM if not already present -----------------
if (-not (Test-Path $NssmExe)) {
    Write-Host "Downloading NSSM..." -ForegroundColor Cyan
    $ZipPath = "$env:TEMP\nssm.zip"
    Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile $ZipPath
    Write-Host "Extracting to $NssmDir..." -ForegroundColor Cyan
    New-Item -ItemType Directory -Path $NssmDir -Force | Out-Null
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    foreach ($entry in $zip.Entries) {
        # Pull only the 64-bit nssm.exe
        if ($entry.FullName -like "*/win64/nssm.exe") {
            [System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $NssmExe, $true)
            break
        }
    }
    $zip.Dispose()
    Remove-Item $ZipPath
    Write-Host "NSSM installed at $NssmExe" -ForegroundColor Green
} else {
    Write-Host "NSSM already present at $NssmExe" -ForegroundColor Green
}

# -- Step 2: Remove existing service if present -------------------------------
$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing $ServiceName service..." -ForegroundColor Yellow
    & $NssmExe stop $ServiceName 2>$null
    & $NssmExe remove $ServiceName confirm
}

# -- Step 3: Register the service ---------------------------------------------
Write-Host "Registering $ServiceName service..." -ForegroundColor Cyan
& $NssmExe install $ServiceName $PythonExe $AppArgs
& $NssmExe set $ServiceName AppDirectory $AppDir
& $NssmExe set $ServiceName Description "FinLens AI Financial Analyser (Streamlit)"
& $NssmExe set $ServiceName Start SERVICE_AUTO_START
& $NssmExe set $ServiceName AppStdout "$AppDir\logs\service_stdout.log"
& $NssmExe set $ServiceName AppStderr "$AppDir\logs\service_stderr.log"
& $NssmExe set $ServiceName AppRotateFiles 1
& $NssmExe set $ServiceName AppRotateBytes 5242880   # rotate at 5 MB

# Create logs directory if it doesn't exist
New-Item -ItemType Directory -Path "$AppDir\logs" -Force | Out-Null

# -- Step 4: Start the service ------------------------------------------------
Write-Host "Starting $ServiceName..." -ForegroundColor Cyan
& $NssmExe start $ServiceName
Start-Sleep -Seconds 5

# -- Step 5: Confirm it's running ---------------------------------------------
$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -eq "Running") {
    Write-Host ""
    Write-Host "FinLens service is RUNNING." -ForegroundColor Green
    Write-Host "Open http://localhost:8501 in your browser." -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "Service did not reach Running state - check logs:" -ForegroundColor Red
    Write-Host "  $AppDir\logs\service_stderr.log" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Common cause: Python or Streamlit path is wrong." -ForegroundColor Yellow
    Write-Host "Verify with: Test-Path '$PythonExe'" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Management commands:" -ForegroundColor Cyan
Write-Host "  nssm stop    $ServiceName"
Write-Host "  nssm start   $ServiceName"
Write-Host "  nssm restart $ServiceName"
Write-Host "  nssm remove  $ServiceName confirm"

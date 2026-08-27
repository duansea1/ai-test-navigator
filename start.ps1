$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $root) { $root = $PSScriptRoot }
if (-not $root) { $root = (Get-Location).Path }
Set-Location $root

# Clear proxy env vars inherited from parent shell (avoid dead proxy => WinError 10061)
Remove-Item env:HTTP_PROXY, env:http_proxy, env:HTTPS_PROXY, env:https_proxy, env:ALL_PROXY, env:all_proxy -ErrorAction SilentlyContinue

$port = 8090
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    Write-Host 'Python 3.10+ was not found.' -ForegroundColor Red
    exit 1
}
$python = $pythonCommand.Source
$env:PYTHONPATH = Join-Path $root 'backend'

# 1. Kill any process holding the port, so backend is freshly started (code changes take effect)
$existing = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host 'Stopping existing process on port 8090...' -ForegroundColor Yellow
    $existing | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 1
}

# 2. Python dependency check
Write-Host 'Checking Python dependencies...' -ForegroundColor Cyan
& $python -c "import fastapi, pydantic, uvicorn" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Installing project dependencies...' -ForegroundColor Yellow
    & $python -m pip install -r (Join-Path $root 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

# 3. Frontend build (esbuild). frontend/dist is gitignored and not pushed,
#    so it must be rebuilt after frontend code changes. Double-click start.bat
#    => auto build + restart + open browser => see latest.
#    Use Start-Process -Wait with explicit args. PS 5.1 -File mode sometimes
#    drops the arg in `& node $var`, dropping node into its REPL and hanging
#    the whole startup chain. Start-Process passes args reliably.
$buildScript = Join-Path $root 'scripts\build-frontend.mjs'
Write-Host "buildScript = $buildScript"
if (Test-Path -LiteralPath $buildScript) {
    Write-Host 'Building frontend (esbuild)...' -ForegroundColor Cyan
    Push-Location (Join-Path $root 'frontend')
    $buildOk = $false
    try {
        $proc = Start-Process -FilePath 'node' -ArgumentList @($buildScript) -Wait -PassThru -NoNewWindow
        $buildOk = ($null -ne $proc -and $proc.ExitCode -eq 0)
    } catch {
        Write-Host "Frontend build error: $($_.Exception.Message)" -ForegroundColor Yellow
        $buildOk = $false
    } finally {
        Pop-Location
    }
    if ($buildOk) {
        Write-Host 'Frontend built OK.' -ForegroundColor Green
    } else {
        Write-Host 'Frontend build failed - backend still starts (frontend may be stale).' -ForegroundColor Yellow
    }
} else {
    Write-Host "Build script not found: $buildScript - skip frontend build." -ForegroundColor Yellow
}

# 4. Start backend in background
$url = "http://127.0.0.1:{0}/" -f $port
Write-Host ("Starting AI Test Navigator at {0}" -f $url) -ForegroundColor Green
Start-Process -FilePath $python -ArgumentList "-m uvicorn app.main:app --host 127.0.0.1 --port $port" -WorkingDirectory $root

# 5. Poll until port is ready, then open browser with cache-busting param
$cb = [DateTimeOffset]::Now.ToUnixTimeSeconds()
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        (Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 2).StatusCode | Out-Null
        $ready = $true
        break
    } catch {
        Start-Sleep -Seconds 1
    }
}
if ($ready) {
    Start-Process ("{0}?cb={1}" -f $url, $cb)
    Write-Host 'Browser opened. If the page looks stale, just press F5 once.' -ForegroundColor Green
} else {
    Write-Host ('Server did not become ready on port {0}. Check the console above.' -f $port) -ForegroundColor Red
}

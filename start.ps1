$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# 清除可能从父 shell 继承的（现已失效的）代理环境变量，避免 urllib 走死代理导致外部探测 [WinError 10061]
Remove-Item env:HTTP_PROXY, env:http_proxy, env:HTTPS_PROXY, env:https_proxy, env:ALL_PROXY, env:all_proxy -ErrorAction SilentlyContinue

$port = 8090
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    Write-Host 'Python 3.10+ was not found.' -ForegroundColor Red
    exit 1
}
$python = $pythonCommand.Source
$env:PYTHONPATH = Join-Path $root 'backend'

# 1. 关闭已占用端口的进程，确保后端是全新启动（避免旧实例掩盖代码改动）
$existing = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host 'Stopping existing process on port 8090...' -ForegroundColor Yellow
    $existing | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 1
}

# 2. 依赖检查
Write-Host 'Checking Python dependencies...' -ForegroundColor Cyan
& $python -c "import fastapi, pydantic, uvicorn" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Installing project dependencies...' -ForegroundColor Yellow
    & $python -m pip install -r (Join-Path $root 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

# 3. 后台启动后端
$url = "http://127.0.0.1:{0}/" -f $port
Write-Host ("Starting AI Test Navigator at {0}" -f $url) -ForegroundColor Green
Start-Process -FilePath $python -ArgumentList "-m uvicorn app.main:app --host 127.0.0.1 --port $port" -WorkingDirectory $root

# 4. 轮询等待端口就绪，再打开浏览器（带缓存破坏参数，确保看到最新前端）
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

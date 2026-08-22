@echo off
setlocal
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8090 .*LISTENING"') do (
  echo 正在停止端口 8090 的进程 %%p...
  taskkill /PID %%p /F >nul 2>&1
)
echo AI Test Navigator 已停止（如果端口原本未占用则无需处理）。
pause
endlocal

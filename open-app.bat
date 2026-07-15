@echo off
rem Open Carter Kitchen and Bath — starts the server first if it isn't running.
powershell -NoProfile -Command "exit @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue).Count"
if errorlevel 1 goto open

start "" /min "C:\Users\BRIANS~1\Downloads\cabinet-management\run-server.bat"
for /l %%i in (1,1,30) do (
  powershell -NoProfile -Command "exit @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue).Count"
  if errorlevel 1 goto open
  timeout /t 1 /nobreak >nul
)

:open
start "" http://localhost:8000

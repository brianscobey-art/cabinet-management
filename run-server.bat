@echo off
rem Carter Kitchen and Bath — pilot server (API + frontend on port 8000)
rem If a server is already running, exit quietly instead of fighting for the port.
powershell -NoProfile -Command "exit @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue).Count"
if errorlevel 1 (
  echo Server already running on port 8000 - nothing to do.
  goto :eof
)
rem On every start: back up the database to OneDrive, keep 30 days of copies.
set "BK=C:\Users\Brian SE6\OneDrive - carterlumber.com\Carter Kitchen and Bath\DB Backups"
if exist "%~dp0backend\dev.db" (
  powershell -NoProfile -Command "Copy-Item '%~dp0backend\dev.db' ('%BK%\kb-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.db'); Get-ChildItem '%BK%\kb-*.db' | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } | Remove-Item"
)
cd /d "%~dp0backend"

rem Watchdog: if uvicorn ever exits (crash, transient error), restart it in 5s.
:loop
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
echo [%date% %time%] server exited with code %errorlevel% - restarting in 5 seconds
timeout /t 5 /nobreak >nul
goto loop

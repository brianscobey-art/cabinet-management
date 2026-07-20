@echo off
rem Starts the CabinetTron watchdog hidden (no console window).
rem It keeps the app on http://localhost:8000 running; log: watchdog.log
rem To stop it: create an empty file named watchdog.stop in this folder.
start "" "%~dp0backend\.venv\Scripts\pythonw.exe" "%~dp0watchdog.py"

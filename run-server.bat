@echo off
rem Carter Kitchen and Bath — pilot server (API + frontend on port 8000)
cd /d "%~dp0backend"
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000

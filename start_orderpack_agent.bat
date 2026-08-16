@echo off
rem Starts the Order Pack agent hidden (no console window).
rem It watches the four "Sold Jobs\New Orders" stage folders and runs the work
rem the Order Pack page queues up. Log: agent\orderpack_agent.log
rem To stop it: create an empty file named orderpack_agent.stop in the agent folder.
start "" "%~dp0backend\.venv\Scripts\pythonw.exe" "%~dp0agent\orderpack_agent.py"

' Runs scripts\pull_domo_receipts.py with NO console window.
'
' Same reason upload_feeds_hidden.vbs exists: Task Scheduler paints a console
' for a python.exe action and it flashes over whatever Brian is typing in.
' WScript.Shell.Run with intWindowStyle = 0 launches it genuinely hidden.
' Headless Chromium paints nothing of its own.
'
' Scheduled as "CarterKB DOMO Receipts", daily 02:30 -- ahead of the 03:00 PO
' tracker push on cabinettron.com, with the 5-minute R2 upload and cloud poll
' in between carrying the CSV up. Exit code 2 means the DOMO session has
' expired: run  backend\.venv\Scripts\python.exe scripts\pull_domo_receipts.py --login
' once and it resumes.
Set sh = CreateObject("WScript.Shell")
base = "C:\Users\Brian SE6\OneDrive - carterlumber.com\AI Utilities\cabinet-management\backend"
cmd = "cmd /c cd /d """ & base & """ && "".venv\Scripts\python.exe"" -X utf8 scripts\pull_domo_receipts.py >> ""%TEMP%\carterkb_domo_receipts.log"" 2>&1"
rc = sh.Run(cmd, 0, True)
WScript.Quit rc

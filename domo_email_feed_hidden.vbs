' Runs scripts\domo_email_feed.py with NO console window (same reason as
' pull_domo_receipts_hidden.vbs). Scheduled as "CarterKB DOMO Email Feed",
' hourly 05:30-11:30: DOMO emails the three "CabinetTron feed" reports at
' 05:00 CT, Power Automate drops the attachments in AI Utilities\domo-email-feed,
' and this turns them into the receipts / accounts / job-PO files in Downloads
' that "CarterKB R2 Upload" ships -- unless the 02:30 direct pull already did.
Set sh = CreateObject("WScript.Shell")
base = "C:\Users\Brian SE6\OneDrive - carterlumber.com\AI Utilities\cabinet-management\backend"
cmd = "cmd /c cd /d """ & base & """ && "".venv\Scripts\python.exe"" -X utf8 scripts\domo_email_feed.py >> ""%TEMP%\carterkb_domo_email_feed.log"" 2>&1"
rc = sh.Run(cmd, 0, True)
WScript.Quit rc

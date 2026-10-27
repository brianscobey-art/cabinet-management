# Morning refresh of the 3.0 tracker's live Import Data table (Brian 10/26/26).
# Excel pauses automatic refresh while more than one person has the workbook
# open, so this does an explicit refresh + save every hour, starting 4:00 AM
# (wakes the PC; Brian 10/27/26). Scheduled as "CarterKB Tracker Morning
# Refresh" (name kept -- ai_health watches it). During the day anyone can also click Refresh All in Excel for the
# web (first time: Connect, Anonymous) -- that refreshes it for everyone.
#
# Rules learned the hard way (see memory "tracker-live-link"):
#  - If the tracker is already open in Brian's own Excel, refresh THAT copy
#    (found by walking the running instance's Workbooks) -- never open a
#    second copy, and never BindToMoniker (it opens the file hidden).
#  - Otherwise use a separate hidden Excel instance and quit it afterwards.
#  - Do not change AutoSaveOn (the setting sticks to the file).
#  - Make every workbook window visible before saving, so the file never
#    gets saved in a hidden state.
#  - Save only if the refresh brought back a sane number of rows.
$ErrorActionPreference = 'Stop'
$tracker = 'C:\Users\Brian SE6\OneDrive - carterlumber.com\Carter Shared File\Trackers\3.0 Online Sales Tracker 010726.xlsm'
$name = Split-Path $tracker -Leaf
$log = Join-Path $env:TEMP 'carterkb_tracker_refresh.log'
$status = 'C:\Users\Brian SE6\OneDrive - carterlumber.com\AI Utilities\ai-health\tracker_refresh.json'
function Log($m) { "$(Get-Date -f 'yyyy-MM-dd HH:mm:ss')  $m" | Tee-Object -FilePath $log -Append }
function Status($state, $rows, $note) {
  try {
    @{ state = $state; at = (Get-Date -f 's'); rows = $rows; note = $note } |
      ConvertTo-Json | Set-Content -Path $status -Encoding utf8
  } catch {}
}

function Refresh-Book($wb) {
  $imp = $wb.Worksheets.Item('Import Data').ListObjects.Item('ImportData')
  $null = $imp.QueryTable.Refresh($false)
  $rows = $imp.ListRows.Count
  if ($rows -lt 50) { throw "refresh returned only $rows rows - not saving" }
  foreach ($w in $wb.Windows) { if (-not $w.Visible) { $w.Visible = $true } }
  $wb.Save()
  return $rows
}

$xl = $null; $ownXl = $false; $wb = $null
try {
  # 1) Already open in Brian's Excel?
  try {
    $running = [Runtime.InteropServices.Marshal]::GetActiveObject('Excel.Application')
    foreach ($w in $running.Workbooks) { if ($w.Name -eq $name) { $wb = $w } }
  } catch {}
  if ($wb) {
    $rows = Refresh-Book $wb
    Log "refreshed the copy already open in Excel: $rows rows, saved"
    Status 'ok' $rows 'refreshed open copy'
    exit 0
  }
  # 2) Not open: separate hidden instance.
  $xl = New-Object -ComObject Excel.Application
  $ownXl = $true
  $xl.Visible = $false; $xl.DisplayAlerts = $false; $xl.AskToUpdateLinks = $false; $xl.EnableEvents = $false
  $wb = $xl.Workbooks.Open($tracker, 0, $false)
  if ($wb.ReadOnly) { throw 'opened read-only (locked by someone) - skipped' }
  $rows = Refresh-Book $wb
  Log "refreshed in a hidden Excel: $rows rows, saved"
  Status 'ok' $rows 'refreshed'
  exit 0
} catch {
  Log "ERROR: $_"
  Status 'error' 0 "$_"
  exit 1
} finally {
  if ($ownXl) {
    try { if ($wb) { $wb.Close($false) } } catch {}
    try { $xl.Quit() } catch {}
    try { [System.Runtime.InteropServices.Marshal]::ReleaseComObject($xl) | Out-Null } catch {}
  }
}

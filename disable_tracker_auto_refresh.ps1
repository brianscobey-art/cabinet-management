# Turn OFF the tracker's in-Excel auto refresh of Import Data (Brian 11/5/26).
# With refresh-on-open / refresh-every-N-minutes on, Excel shows the gold
# "MANUAL REFRESH REQUIRED" bar whenever someone else has the workbook open
# (co-authoring pauses automatic refresh). The hourly "CarterKB Tracker
# Morning Refresh" task (refresh_tracker_live.ps1) refreshes + saves for
# everyone, so the workbook doesn't need its own timer.
#
# Same rules as refresh_tracker_live.ps1: use the copy already open in
# Brian's Excel if there is one, else a separate hidden instance; never
# BindToMoniker; don't touch AutoSaveOn; windows visible before saving.
$ErrorActionPreference = 'Stop'
$tracker = 'C:\Users\Brian SE6\OneDrive - carterlumber.com\Carter Shared File\Trackers\3.0 Online Sales Tracker 010726.xlsm'
$name = Split-Path $tracker -Leaf

function Disable-AutoRefresh($wb) {
  $qt = $wb.Worksheets.Item('Import Data').ListObjects.Item('ImportData').QueryTable
  $conn = $qt.WorkbookConnection
  "before: on open=$($conn.RefreshWithRefreshAll) qt.open=$($qt.RefreshOnFileOpen) qt.every=$($qt.RefreshPeriod) conn.every=$($conn.OLEDBConnection.RefreshPeriod) conn.open=$($conn.OLEDBConnection.RefreshOnFileOpen)"
  $qt.RefreshOnFileOpen = $false
  $qt.RefreshPeriod = 0
  $conn.OLEDBConnection.RefreshOnFileOpen = $false
  $conn.OLEDBConnection.RefreshPeriod = 0
  "after:  qt.open=$($qt.RefreshOnFileOpen) qt.every=$($qt.RefreshPeriod) conn.every=$($conn.OLEDBConnection.RefreshPeriod) conn.open=$($conn.OLEDBConnection.RefreshOnFileOpen)"
  foreach ($w in $wb.Windows) { if (-not $w.Visible) { $w.Visible = $true } }
  $wb.Save()
  'saved'
}

$xl = $null; $ownXl = $false; $wb = $null
try {
  try {
    $running = [Runtime.InteropServices.Marshal]::GetActiveObject('Excel.Application')
    foreach ($w in $running.Workbooks) { if ($w.Name -eq $name) { $wb = $w } }
  } catch {}
  if ($wb) { 'using the copy open in Excel'; Disable-AutoRefresh $wb; exit 0 }
  $xl = New-Object -ComObject Excel.Application
  $ownXl = $true
  $xl.Visible = $false; $xl.DisplayAlerts = $false; $xl.AskToUpdateLinks = $false; $xl.EnableEvents = $false
  $wb = $xl.Workbooks.Open($tracker, 0, $false)
  if ($wb.ReadOnly) { throw 'opened read-only (locked by someone) - nothing changed' }
  'opened in a hidden Excel'
  Disable-AutoRefresh $wb
  exit 0
} catch {
  "ERROR: $_"
  exit 1
} finally {
  if ($ownXl) {
    try { if ($wb) { $wb.Close($false) } } catch {}
    try { $xl.Quit() } catch {}
    try { [System.Runtime.InteropServices.Marshal]::ReleaseComObject($xl) | Out-Null } catch {}
  }
}

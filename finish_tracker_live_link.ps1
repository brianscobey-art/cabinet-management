# Finishing pass on the tracker's live Import Data link (10/26/26).
#  - AutoSave OFF before touching anything: the workbook lives in OneDrive and
#    desktop Excel AutoSaves it, which is how the earlier "dry runs" ended up
#    saved. This pass saves explicitly, and only after it verifies clean.
#  - DATA[Last Checked]: blank (not "1/0") for houses with no phase logged.
#  - Remove data connections nothing uses (left behind by the repeat runs).
#  - Import Data refreshes on open and every 15 minutes.
$ErrorActionPreference = 'Stop'
$tracker = 'C:\Users\Brian SE6\OneDrive - carterlumber.com\Carter Shared File\Trackers\3.0 Online Sales Tracker 010726.xlsm'
$xl = New-Object -ComObject Excel.Application
$xl.Visible = $false
$xl.DisplayAlerts = $false
$xl.AskToUpdateLinks = $false
$xl.EnableEvents = $false
$saved = $false
try {
  $wb = $xl.Workbooks.Open($tracker, 0, $false)
  try { $wb.AutoSaveOn = $false; "AutoSave off" } catch { "AutoSave property not available: $($_.Exception.Message)" }
  if ($wb.ReadOnly) { throw "opened read-only - nothing changed" }

  $ws = $wb.Worksheets.Item('Import Data')
  $imp = $ws.ListObjects.Item('ImportData')
  $qt = $imp.QueryTable
  $null = $qt.Refresh($false)
  "ImportData rows after refresh: $($imp.ListRows.Count) (query: $($qt.CommandText))"

  $data = $null
  foreach ($s in $wb.Worksheets) { foreach ($lo in $s.ListObjects) { if ($lo.Name -eq 'DATA') { $data = $lo } } }
  $lc = $data.ListColumns.Item('Last Checked')
  $lc.DataBodyRange.Formula2 = '=LET(d,XLOOKUP([@[Job Code]],ImportData[Job Code],ImportData[Date Checked],""),IF(d=0,"",d))'

  # Connections: keep only the one ImportData's query table uses.
  $keep = $qt.WorkbookConnection.Name
  foreach ($c in @($wb.Connections)) {
    if ($c.Name -ne $keep) {
      $used = $false
      try { $used = ($c.Ranges.Count -gt 0) } catch {}
      if (-not $used) { "removing unused connection: $($c.Name)"; $c.Delete() }
    }
  }
  "connections now: " + ((@($wb.Connections) | ForEach-Object { $_.Name }) -join ', ')
  "queries now: " + ((@($wb.Queries) | ForEach-Object { $_.Name }) -join ', ')

  $qt.RefreshOnFileOpen = $true
  $qt.RefreshPeriod = 15
  $qt.BackgroundQuery = $true
  "refresh on open=$($qt.RefreshOnFileOpen) every=$($qt.RefreshPeriod) min"

  $xl.CalculateFull()
  $counts = @{}; $bad = 0
  foreach ($c in $lc.DataBodyRange.Cells) {
    $t = [string]$c.Text
    if ($t -like '#*') { $bad++ }
    if (-not $counts.ContainsKey($t)) { $counts[$t] = 0 }; $counts[$t]++
  }
  "Last Checked: blanks=$($counts['']) errors=$bad top=" + (($counts.GetEnumerator() | Sort-Object Value -Descending | Select-Object -First 5 | ForEach-Object { "'$($_.Key)' x$($_.Value)" }) -join ', ')
  $zero = ($counts.GetEnumerator() | Where-Object { $_.Key -match '^(0|1/0|1/0/00|1/0/1900)$' } | Measure-Object Value -Sum).Sum
  if ($bad -gt 0 -or $zero -gt 0) { throw "verification failed (errors=$bad zero-dates=$zero) - NOT saving" }
  $wb.Save(); $saved = $true; "saved"
} finally {
  if ($wb) { $wb.Close($false) }
  $xl.Quit()
  [System.Runtime.InteropServices.Marshal]::ReleaseComObject($xl) | Out-Null
  "done (saved=$saved)"
}

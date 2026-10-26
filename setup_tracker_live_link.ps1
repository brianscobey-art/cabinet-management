# One-time setup (10/26/26): turn the tracker's "Import Data" table into a
# live query on CabinetTron's phase link, so it refreshes itself instead of
# being pasted or pushed into.
#
#  - Backs the workbook up first (Backup folder, "... pre-live-link.xlsm").
#  - Builds the query table beside the old one, repoints the Command Center's
#    DATA[Last Checked] formula at it, removes the old table, moves the new
#    one into A3 and gives it the old name "ImportData" -- so every formula
#    that read ImportData keeps working.
#  - Refreshes on open and every 15 minutes while the workbook is open.
#  - Saves ONLY if DATA[Last Checked] resolves (no #REF!/#NAME?) afterwards.
#
# Uses its own hidden Excel instance; never touches a workbook already open.
param([switch]$DryRun)
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$cfg = Get-Content (Join-Path $here 'tracker_export.config.json') -Raw | ConvertFrom-Json
$url = "$($cfg.url)/api/reports/phases/live.csv?token=$($cfg.token)"
$tracker = 'C:\Users\Brian SE6\OneDrive - carterlumber.com\Carter Shared File\Trackers\3.0 Online Sales Tracker 010726.xlsm'
$backupDir = 'C:\Users\Brian SE6\OneDrive - carterlumber.com\Carter Shared File\Trackers\3.0 Online Sales Tracker 010726 Backup'
$backup = Join-Path $backupDir ("3.0 Online Sales Tracker 010726 pre-live-link {0}.xlsm" -f (Get-Date -f 'MMddyy HHmmss'))

Add-Type -Namespace W -Name K -MemberDefinition '[DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] public static extern bool CopyFileW(string a, string b, bool f);'
if (-not [W.K]::CopyFileW($tracker, $backup, $true)) { throw "backup copy failed" }
"backup: $backup ($((Get-Item $backup).Length) bytes)"

$m = @"
let
    Source = Csv.Document(Web.Contents("$url"), [Delimiter=",", Columns=5, Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    Typed = Table.TransformColumnTypes(Promoted, {{"Job Code", type text}, {"Date Checked", type date}, {"Phase", type number}, {"Date Measured", type date}, {"CONST LVL", type text}})
in
    Typed
"@

$xl = New-Object -ComObject Excel.Application
$xl.Visible = $false
$xl.DisplayAlerts = $false
$xl.AskToUpdateLinks = $false
$xl.EnableEvents = $false
$saved = $false
try {
  $wb = $xl.Workbooks.Open($tracker, 0, $false)
  if ($wb.ReadOnly) { throw "workbook opened read-only (someone has it locked) - nothing changed" }
  $ws = $wb.Worksheets.Item('Import Data')
  $old = $ws.ListObjects.Item('ImportData')
  "old table: $($old.Range.Address()) rows=$($old.ListRows.Count)"

  foreach ($q in @($wb.Queries)) { if ($q.Name -eq 'CabinetTron Phases') { $q.Delete() } }
  $null = $wb.Queries.Add('CabinetTron Phases', $m)
  $conn = 'OLEDB;Provider=Microsoft.Mashup.OleDb.1;Data Source=$Workbook$;Location="CabinetTron Phases";Extended Properties=""'
  $tmpCol = $old.Range.Columns.Count + 3
  $new = $ws.ListObjects.Add(0, $conn, $true, 1, $ws.Cells.Item($old.Range.Row, $tmpCol))
  $new.Name = 'ImportData_new'
  $qt = $new.QueryTable
  $qt.CommandType = 2
  $qt.CommandText = 'SELECT * FROM [CabinetTron Phases]'
  $qt.BackgroundQuery = $false
  $null = $qt.Refresh($false)
  "new table loaded: rows=$($new.ListRows.Count)"
  if ($new.ListRows.Count -lt 50) { throw "live link returned too few rows ($($new.ListRows.Count)) - nothing saved" }

  # Repoint the Command Center's Last Checked at the new table, then retire the old one.
  $data = $null
  foreach ($s in $wb.Worksheets) { foreach ($lo in $s.ListObjects) { if ($lo.Name -eq 'DATA') { $data = $lo } } }
  $lc = $data.ListColumns.Item('Last Checked')
  $lc.DataBodyRange.Formula2 = '=XLOOKUP([@[Job Code]],ImportData_new[Job Code],ImportData_new[Date Checked],"")'
  $old.Delete()
  $null = $new.Range.Cut($ws.Cells.Item(3, 1))
  $new = $ws.ListObjects.Item('ImportData_new')
  $new.Name = 'ImportData'
  "moved to $($new.Range.Address()); DATA[Last Checked] formula: $($lc.DataBodyRange.Cells.Item(1,1).Formula2)"

  $qt = $new.QueryTable
  $qt.RefreshOnFileOpen = $true
  $qt.RefreshPeriod = 15
  $qt.BackgroundQuery = $true
  $qt.AdjustColumnWidth = $false
  $qt.PreserveFormatting = $true
  $new.ListColumns.Item('Date Checked').DataBodyRange.NumberFormat = 'm/d/yy'
  $new.ListColumns.Item('Date Measured').DataBodyRange.NumberFormat = 'm/d/yy'
  $ws.Cells.Item(2, 1).Value2 = 'LIVE FROM CABINETTRON - refreshes on open and every 15 min (Data > Refresh All to force)'

  # Verify before saving.
  $xl.CalculateFull()
  $bad = 0; $filled = 0
  foreach ($c in $lc.DataBodyRange.Cells) {
    $t = [string]$c.Text
    if ($t -like '#*') { $bad++ } elseif ($t -ne '') { $filled++ }
  }
  "DATA[Last Checked]: $filled filled, $bad errors"
  $texts = @{}; foreach ($c in $lc.DataBodyRange.Cells) { $t=[string]$c.Text; if (-not $texts.ContainsKey($t)) { $texts[$t]=0 }; $texts[$t]++ }
  "Last Checked most common values: " + (($texts.GetEnumerator() | Sort-Object Value -Descending | Select-Object -First 6 | ForEach-Object { "'$($_.Key)' x$($_.Value)" }) -join ', ')
  $zeroish = ($texts.GetEnumerator() | Where-Object { $_.Key -match '^(0|1/0/00|1/0/1900|0-Jan-00)$' } | Measure-Object Value -Sum).Sum
  if ($zeroish -gt 0) { throw "Last Checked shows $zeroish zero-dates for houses with no phase - NOT saving" }
  if ($bad -gt 0) { throw "Last Checked shows $bad errors - NOT saving; workbook unchanged" }
  if ($DryRun) { "dry run - not saving" } else { $wb.Save(); $saved = $true; "saved" }
} finally {
  if ($wb) { $wb.Close($false) }
  $xl.Quit()
  [System.Runtime.InteropServices.Marshal]::ReleaseComObject($xl) | Out-Null
  "done (saved=$saved)"
}

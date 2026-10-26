# Update the tracker's live Import Data query (10/26/26): only the first four
# columns are typed, so column E can be renamed on CabinetTron's side
# (CONST LVL -> Full Phase) without the refresh breaking. AutoSave off first;
# saves only after a clean refresh.
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$cfg = Get-Content (Join-Path $here 'tracker_export.config.json') -Raw | ConvertFrom-Json
$url = "$($cfg.url)/api/reports/phases/live.csv?token=$($cfg.token)"
$tracker = 'C:\Users\Brian SE6\OneDrive - carterlumber.com\Carter Shared File\Trackers\3.0 Online Sales Tracker 010726.xlsm'
$m = @"
let
    Source = Csv.Document(Web.Contents("$url"), [Delimiter=",", Columns=5, Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    Typed = Table.TransformColumnTypes(Promoted, {{"Job Code", type text}, {"Date Checked", type date}, {"Phase", type number}, {"Date Measured", type date}})
in
    Typed
"@
$xl = New-Object -ComObject Excel.Application
$xl.Visible = $false; $xl.DisplayAlerts = $false; $xl.AskToUpdateLinks = $false; $xl.EnableEvents = $false
$saved = $false
try {
  $wb = $xl.Workbooks.Open($tracker, 0, $false)
  $wb.AutoSaveOn = $false
  if ($wb.ReadOnly) { throw "opened read-only - nothing changed" }
  $wb.Queries.Item('CabinetTron Phases').Formula = $m
  $imp = $wb.Worksheets.Item('Import Data').ListObjects.Item('ImportData')
  $null = $imp.QueryTable.Refresh($false)
  $hdr = ($imp.HeaderRowRange.Value2 | ForEach-Object { $_ }) -join ' | '
  "rows=$($imp.ListRows.Count) header=$hdr"
  "row: " + (($imp.ListRows.Item(400).Range.Text | ForEach-Object { $_ }) -join ' | ')
  if ($imp.ListRows.Count -lt 50) { throw "too few rows - NOT saving" }
  $imp.ListColumns.Item('Date Checked').DataBodyRange.NumberFormat = 'm/d/yy'
  $imp.ListColumns.Item('Date Measured').DataBodyRange.NumberFormat = 'm/d/yy'
  $wb.Save(); $saved = $true; "saved"
} finally {
  if ($wb) { $wb.Close($false) }
  $xl.Quit(); [System.Runtime.InteropServices.Marshal]::ReleaseComObject($xl) | Out-Null
  "done (saved=$saved)"
}

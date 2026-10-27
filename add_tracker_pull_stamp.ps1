# Import Data "Last update" stamp + hourly refresh (Brian 10/27/26).
#  - Query "CabinetTron Phases" takes the feed's 6th column, Pulled (Central
#    time, stamped by CabinetTron at each pull).
#  - A1 "Last update:", B1 "10/27/26, 4:36am" (formula -- Excel number formats
#    can't do lowercase am/pm). B1 goes red / bold white once the last pull is
#    over 24 hours old.
#  - In-Excel refresh every 60 min (was 15); banner text to match.
# Edits the copy open in Brian's Excel if there is one (never BindToMoniker),
# else a separate hidden instance. AutoSave off while editing, back on before
# the one save, and only after a clean refresh.
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$cfg = Get-Content (Join-Path $here 'tracker_export.config.json') -Raw | ConvertFrom-Json
$url = "$($cfg.url)/api/reports/phases/live.csv?token=$($cfg.token)"
$tracker = 'C:\Users\Brian SE6\OneDrive - carterlumber.com\Carter Shared File\Trackers\3.0 Online Sales Tracker 010726.xlsm'
$name = Split-Path $tracker -Leaf
$m = @"
let
    Source = Csv.Document(Web.Contents("$url"), [Delimiter=",", Columns=6, Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    Typed = Table.TransformColumnTypes(Promoted, {{"Job Code", type text}, {"Date Checked", type date}, {"Phase", type number}, {"Date Measured", type date}, {"Pulled", type datetime}})
in
    Typed
"@

$xl = $null; $ownXl = $false; $wb = $null; $saved = $false
try {
  try {
    $running = [Runtime.InteropServices.Marshal]::GetActiveObject('Excel.Application')
    foreach ($w in $running.Workbooks) { if ($w.Name -eq $name) { $wb = $w } }
  } catch {}
  if ($wb) { "editing the copy open in Excel" } else {
    $xl = New-Object -ComObject Excel.Application; $ownXl = $true
    $xl.Visible = $false; $xl.DisplayAlerts = $false; $xl.AskToUpdateLinks = $false; $xl.EnableEvents = $false
    $wb = $xl.Workbooks.Open($tracker, 0, $false)
    if ($wb.ReadOnly) { throw 'opened read-only - nothing changed' }
    "editing in a hidden Excel"
  }
  $wb.AutoSaveOn = $false

  $wb.Queries.Item('CabinetTron Phases').Formula = $m
  $ws = $wb.Worksheets.Item('Import Data')
  $imp = $ws.ListObjects.Item('ImportData')
  $null = $imp.QueryTable.Refresh($false)
  $hdr = ($imp.HeaderRowRange.Value2 | ForEach-Object { $_ }) -join ' | '
  "rows=$($imp.ListRows.Count) header=$hdr"
  if ($imp.ListRows.Count -lt 50) { throw 'too few rows - NOT saving' }
  if ($hdr -notmatch 'Pulled') { throw 'Pulled column missing - NOT saving' }
  $imp.ListColumns.Item('Pulled').DataBodyRange.NumberFormat = 'm/d/yy h:mm AM/PM'
  $imp.ListColumns.Item('Pulled').Range.HorizontalAlignment = -4108  # center
  $ws.Columns.Item('F').ColumnWidth = 16

  $conn = $imp.QueryTable.WorkbookConnection   # named "Connection1", not after the query
  $conn.OLEDBConnection.RefreshPeriod = 60; "connection '$($conn.Name)' refresh every 60 min"

  $ws.Range('A2').Value2 = 'LIVE FROM CABINETTRON - refreshes every hour (Data > Refresh All to force)'
  $a1 = $ws.Range('A1'); $a1.Value2 = 'Last update:'; $a1.HorizontalAlignment = -4152  # right
  $b1 = $ws.Range('B1')
  $b1.Formula2 = '=LET(t,MAX(ImportData[Pulled]),IF(t=0,"never",TEXT(t,"m/d/yy, h:mm")&LOWER(TEXT(t,"AM/PM"))))'
  $b1.Font.Bold = $true; $b1.HorizontalAlignment = -4108
  $b1.FormatConditions.Delete()
  $fc = $b1.FormatConditions.Add(2, [Type]::Missing,'=NOW()-MAX($F$4:$F$5000)>1')  # 2 = xlExpression
  $fc.Interior.Color = 0x2020DE   # Carter red #DE2020 (BGR)
  $fc.Font.Color = 0xFFFFFF; $fc.Font.Bold = $true
  "A1='$($a1.Text)' B1='$($b1.Text)'"

  foreach ($w in $wb.Windows) { if (-not $w.Visible) { $w.Visible = $true } }
  $wb.AutoSaveOn = $true
  $wb.Save(); $saved = $true; 'saved'
} finally {
  if ($ownXl) {
    try { if ($wb) { $wb.Close($false) } } catch {}
    try { $xl.Quit() } catch {}
    try { [Runtime.InteropServices.Marshal]::ReleaseComObject($xl) | Out-Null } catch {}
  } elseif ($wb -and -not $saved) {
    try { $wb.AutoSaveOn = $true } catch {}
  }
  "done (saved=$saved)"
}

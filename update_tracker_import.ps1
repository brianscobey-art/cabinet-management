# Pushes CabinetTron phase data into the 3.0 Online Sales Tracker's
# "Import Data" sheet (table Table21: Job Code | Date Checked | Phase |
# Date Measured | Full Phase).
#
# Uses Excel itself via COM so the .xlsm's macros, formatting, data validation
# and the calculated "Full Phase" column are all preserved (openpyxl would
# strip them). Never writes column 5 — Excel fills it from its own formula.
#
# Config lives beside this script in tracker_export.config.json:
#   { "url": "https://www.cabinettron.com", "token": "..." }

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$log  = Join-Path $env:TEMP 'carterkb_tracker_import.log'
function Log($m) { "$(Get-Date -f 'yyyy-MM-dd HH:mm:ss')  $m" | Tee-Object -FilePath $log -Append }

try {
  $cfg = Get-Content (Join-Path $here 'tracker_export.config.json') -Raw | ConvertFrom-Json
  $trackerDir = 'C:\Users\Brian SE6\OneDrive - carterlumber.com\Townsend Kitchen and Bath - Master Plans & Pricing\Trackers\3.0 Online Sales Tracker 010726 Backup'

  # 1. newest tracker workbook
  $wbFile = Get-ChildItem $trackerDir -Filter '3.0 Online Sales Tracker *.xlsm' |
            Where-Object { $_.Name -notlike '~*' } |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if (-not $wbFile) { throw "no tracker workbook found in $trackerDir" }

  # 2. pull the phase data
  $uri = "$($cfg.url)/api/reports/tracker-export/public?token=$($cfg.token)"
  $csv = (Invoke-WebRequest -Uri $uri -UseBasicParsing -TimeoutSec 120).Content
  $rows = $csv | ConvertFrom-Csv
  if (-not $rows -or $rows.Count -eq 0) { throw 'export returned no rows' }
  Log "fetched $($rows.Count) rows; target $($wbFile.Name)"

  # 3. write into Table21 with Excel
  $excel = New-Object -ComObject Excel.Application
  $excel.Visible = $false
  $excel.DisplayAlerts = $false
  $excel.AskToUpdateLinks = $false
  $wb = $excel.Workbooks.Open($wbFile.FullName, 0, $false)   # UpdateLinks=0, ReadOnly=false
  try {
    $ws = $wb.Worksheets.Item('Import Data')
    $lo = $ws.ListObjects.Item('Table21')
    $hdrRow = $lo.HeaderRowRange.Row
    $firstRow = $hdrRow + 1

    # resize the table to exactly the incoming row count (keeps the calc column)
    $lastCol = $lo.Range.Columns.Count
    $newLast = $firstRow + $rows.Count - 1
    $lo.Resize($ws.Range($ws.Cells($hdrRow, $lo.Range.Column), $ws.Cells($newLast, $lo.Range.Column + $lastCol - 1)))
    if ($lo.DataBodyRange) { $lo.DataBodyRange.Columns.Item(1).Resize($lo.DataBodyRange.Rows.Count, 4).ClearContents() }

    # bulk write columns 1-4 (never column 5 = Full Phase)
    $data = New-Object 'object[,]' $rows.Count, 4
    for ($i = 0; $i -lt $rows.Count; $i++) {
      $r = $rows[$i]
      $data[$i, 0] = $r.'Job Code'
      $data[$i, 1] = if ($r.'Date Checked')  { [datetime]$r.'Date Checked' }  else { $null }
      $data[$i, 2] = $r.'Phase'
      $data[$i, 3] = if ($r.'Date Measured') { [datetime]$r.'Date Measured' } else { $null }
    }
    $target = $ws.Range($ws.Cells($firstRow, $lo.Range.Column), $ws.Cells($newLast, $lo.Range.Column + 3))
    $target.Value2 = $data
    $ws.Columns.Item($lo.Range.Column + 1).NumberFormat = 'm/d/yy'
    $ws.Columns.Item($lo.Range.Column + 3).NumberFormat = 'm/d/yy'

    $wb.Save()
    Log "wrote $($rows.Count) rows into Table21 and saved"
  } finally {
    $wb.Close($true)
    $excel.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel) | Out-Null
  }
} catch {
  Log "ERROR: $_"
  exit 1
}

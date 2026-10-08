# Nightly snapshot of the LIVE 3.0 Online Sales Tracker.
#
# Source : Carter Shared File\Trackers\3.0 Online Sales Tracker 010726.xlsm
#          (the workbook Brian and Alex work in — Brian, 10/8/26)
# Target : Carter Shared File\Trackers\3.0 Online Sales Tracker 010726 Backup\
#          3.0 Online Sales Tracker <MMDDYY>.xlsm
#
# The MMDDYY is the morning the snapshot serves: a run after noon is labelled
# with TOMORROW's date, a run before noon with today's. That matches the old
# backup folder's convention, which everything downstream (tracker import,
# health check, LiveDesktop, Vendor Suite merge) relies on to pick "newest".
#
# Plain file copy — no Excel COM — so macros, formatting and validation ride
# along untouched, and it works while the workbook is open in Excel.
# Scheduled as "CarterKB Tracker Backup", daily 11:30 PM.
$ErrorActionPreference = 'Stop'
$log = Join-Path $env:TEMP 'carterkb_tracker_backup.log'
function Log($m) { "$(Get-Date -f 'yyyy-MM-dd HH:mm:ss')  $m" | Tee-Object -FilePath $log -Append }

$src = 'C:\Users\Brian SE6\OneDrive - carterlumber.com\Carter Shared File\Trackers\3.0 Online Sales Tracker 010726.xlsm'
$dstDir = 'C:\Users\Brian SE6\OneDrive - carterlumber.com\Carter Shared File\Trackers\3.0 Online Sales Tracker 010726 Backup'

try {
  if (-not (Test-Path $src)) { throw "live tracker not found: $src" }
  if (-not (Test-Path $dstDir)) { New-Item -ItemType Directory -Path $dstDir | Out-Null }

  $serves = Get-Date
  if ($serves.Hour -ge 12) { $serves = $serves.AddDays(1) }
  $dst = Join-Path $dstDir ("3.0 Online Sales Tracker {0}.xlsm" -f $serves.ToString('MMddyy'))

  # Make sure OneDrive has the bytes locally (Files On-Demand placeholders
  # copy as empty shells). Reading the length forces hydration.
  $srcItem = Get-Item $src
  $null = [System.IO.File]::ReadAllBytes($src).Length

  Copy-Item -LiteralPath $src -Destination $dst -Force
  $dstItem = Get-Item $dst
  if ($dstItem.Length -ne $srcItem.Length) { throw "size mismatch: src $($srcItem.Length) dst $($dstItem.Length)" }

  # A valid .xlsm is a zip: the central-directory signature must be present.
  $fs = [System.IO.File]::OpenRead($dst)
  try {
    $tail = New-Object byte[] ([Math]::Min(65557, $fs.Length))
    $fs.Seek(-$tail.Length, 'End') | Out-Null
    $fs.Read($tail, 0, $tail.Length) | Out-Null
  } finally { $fs.Close() }
  $sig = [byte[]](0x50, 0x4B, 0x05, 0x06)
  $ok = $false
  for ($i = 0; $i -le $tail.Length - 4; $i++) {
    if ($tail[$i] -eq $sig[0] -and $tail[$i+1] -eq $sig[1] -and $tail[$i+2] -eq $sig[2] -and $tail[$i+3] -eq $sig[3]) { $ok = $true; break }
  }
  if (-not $ok) { Remove-Item -LiteralPath $dst -Force; throw 'copy is not a valid workbook (no zip central directory) — removed' }

  Log ("copied {0:N0} bytes (source saved {1:M/d/yy h:mm tt}) -> {2}" -f $srcItem.Length, $srcItem.LastWriteTime, (Split-Path $dst -Leaf))
  exit 0
} catch {
  Log "ERROR: $_"
  exit 1
}

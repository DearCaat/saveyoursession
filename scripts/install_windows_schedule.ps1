param(
  [string]$TaskName = "SaveYourSession-DailySync",
  [string]$Time = "03:00",
  [string]$Python = "py",
  [string]$PluginRoot = ""
)
$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($PluginRoot)) { $PluginRoot = Split-Path -Parent $PSScriptRoot }
$runner = Join-Path $PluginRoot "scripts\run_sync.py"
if (!(Test-Path $runner)) { throw "run_sync.py not found: $runner" }
$action = "`"$Python`" `"$runner`""
schtasks.exe /Create /TN $TaskName /SC DAILY /ST $Time /TR $action /F | Out-Host
Write-Output "Installed $TaskName at $Time -> $action"

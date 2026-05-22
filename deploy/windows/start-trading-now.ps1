# Double-click or run: keeps MT5 API + forward bot + desk-api in minimized windows.
$AppDir = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
& (Join-Path $PSScriptRoot 'go-live.ps1') -AppDir $AppDir
$wd = $PSScriptRoot
@('run-mt5-api.ps1', 'run-desk-api.ps1', 'run-forward-bot.ps1', 'run-watchdog.ps1') | ForEach-Object {
  Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -WindowStyle Minimized -File `"$(Join-Path $wd $_)`" -AppDir `"$AppDir`""
}
Start-Sleep -Seconds 6
& (Join-Path $wd 'health-check.ps1')

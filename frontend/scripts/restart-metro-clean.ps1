# Kill stale Metro on 8081, clear cache, restart Expo Go dev server.
$ErrorActionPreference = 'SilentlyContinue'
$port = if ($env:METRO_PORT) { $env:METRO_PORT } else { '8081' }

Write-Host "Stopping processes on port $port..." -ForegroundColor Cyan
Get-NetTCPConnection -LocalPort $port | ForEach-Object {
  Stop-Process -Id $_.OwningProcess -Force
}

$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

if (Test-Path .\.expo) { Remove-Item -Recurse -Force .\.expo }
if (Test-Path .\node_modules\.cache) { Remove-Item -Recurse -Force .\node_modules\.cache }

Write-Host "Starting Expo with --clear (LAN)..." -ForegroundColor Green
node scripts/run-expo-go.js --clear --lan

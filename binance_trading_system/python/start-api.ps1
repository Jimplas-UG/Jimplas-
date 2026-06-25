# Start Binance Futures bridge (port 8766)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

function Import-DotEnvFile([string]$path) {
  if (-not (Test-Path $path)) { return }
  Get-Content $path | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith('#')) { return }
    $eq = $line.IndexOf('=')
    if ($eq -lt 1) { return }
    $key = $line.Substring(0, $eq).Trim()
    $val = $line.Substring($eq + 1).Trim()
    if ($key) {
      Set-Item -Path "Env:$key" -Value $val
    }
  }
}

Import-DotEnvFile (Join-Path $here '.env.local')

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
& .\.venv\Scripts\Activate.ps1
pip install -q -r requirements.txt

$env:PORT = if ($env:PORT) { $env:PORT } else { "8766" }
# 0.0.0.0 so phones on the same Wi-Fi can reach :8766 (override with HOST=127.0.0.1 if needed)
$env:HOST = if ($env:HOST) { $env:HOST } else { "0.0.0.0" }

Write-Host "Bilshenz Binance API on http://$($env:HOST):$($env:PORT)"
Write-Host "BINANCE_TESTNET=$($env:BINANCE_TESTNET) BINANCE_PAPER=$($env:BINANCE_PAPER)"

python main.py

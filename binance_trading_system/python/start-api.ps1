# Start Binance Futures bridge (port 8766)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
& .\.venv\Scripts\Activate.ps1
pip install -q -r requirements.txt

$env:PORT = if ($env:PORT) { $env:PORT } else { "8766" }
$env:HOST = if ($env:HOST) { $env:HOST } else { "127.0.0.1" }

Write-Host "Bilshenz Binance API on http://$($env:HOST):$($env:PORT)"
Write-Host "BINANCE_TESTNET=$($env:BINANCE_TESTNET) BINANCE_PAPER=$($env:BINANCE_PAPER)"

python main.py

param([string]$AppDir = 'C:\opt\bilshenz')
. (Join-Path $PSScriptRoot 'Import-TradingBotEnv.ps1')
$PyDir = Join-Path $AppDir 'mt5_trading_system\python'
$Log = Join-Path $env:TRADINGBOT_LOG_DIR 'mt5-api.log'
New-Item -ItemType Directory -Force -Path $env:TRADINGBOT_LOG_DIR | Out-Null

# Ensure MetaTrader 5 terminal is running before starting the Python bridge
$mt5Path = if ($env:MT5_TERMINAL_PATH) { $env:MT5_TERMINAL_PATH } else { 'C:\Program Files\MetaTrader 5 Exness' }
if (-not (Test-Path "$mt5Path\terminal64.exe")) { $mt5Path = 'C:\Program Files\MetaTrader 5' }
if (Test-Path "$mt5Path\terminal64.exe") {
    if (-not (Get-Process terminal64 -ErrorAction SilentlyContinue)) {
        "$(Get-Date -Format o) Starting terminal64.exe from $mt5Path (with /algotrading)" *>> $Log
        Start-Process "$mt5Path\terminal64.exe" -ArgumentList '/algotrading'
        Start-Sleep 60
    }
}
$env:MT5_TERMINAL_PATH = $mt5Path

Set-Location $PyDir
$env:PORT = '8765'
$py = Join-Path $PyDir '.venv\Scripts\python.exe'
& $py main.py *>> $Log

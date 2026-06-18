# End-to-end smoke test for Binance bridge (no secrets printed).
param(
  [string]$BaseUrl = 'http://127.0.0.1:8766',
  [string]$Symbol = 'XAUUSDT',
  [string]$BridgeToken = $env:BRIDGE_TOKEN
)
$ErrorActionPreference = 'Stop'
$base = $BaseUrl.TrimEnd('/')

function Invoke-Bridge {
  param([string]$Path, [string]$Method = 'GET')
  $headers = @{}
  if ($BridgeToken) { $headers['X-Bridge-Token'] = $BridgeToken }
  return Invoke-WebRequest -Uri "$base$Path" -Method $Method -Headers $headers -UseBasicParsing -TimeoutSec 30
}

Write-Host "=== Binance bridge smoke: $base ===" -ForegroundColor Cyan
$h = (Invoke-Bridge '/health').Content | ConvertFrom-Json
if (-not $h.ok) { throw 'health failed' }
Write-Host "health: ok mode=$($h.mode) ws=$($h.tick_stream.ws_connected)"

$t = (Invoke-Bridge "/api/tick/$Symbol").Content | ConvertFrom-Json
Write-Host "tick: bid=$($t.bid) ask=$($t.ask)"

$b = (Invoke-Bridge "/api/bars/$Symbol`?count=20").Content | ConvertFrom-Json
if (-not $b.bars -or $b.bars.Count -lt 5) { throw 'bars insufficient' }
Write-Host "bars: $($b.bars.Count) M30"

$s = (Invoke-Bridge '/api/status').Content | ConvertFrom-Json
Write-Host "status: connected=$($s.connected) mode=$($s.mode)"

Write-Host 'SMOKE_OK' -ForegroundColor Green

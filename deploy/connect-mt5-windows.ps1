# Run on your Windows PC (same machine as Exness MT5). Administrator recommended for firewall.
#Usage: .\deploy\connect-mt5-windows.ps1
$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path $PSScriptRoot -Parent
$ApiDir = Join-Path $RepoRoot 'mt5_trading_system\python'

# 1) MT5 terminal must be open and logged in
$mt5 = 'C:\Program Files\MetaTrader 5 Exness\terminal64.exe'
if (-not (Test-Path $mt5)) { $mt5 = 'C:\Program Files\MetaTrader 5\terminal64.exe' }
if (-not (Get-Process terminal64 -ErrorAction SilentlyContinue)) {
  Write-Host 'Starting MetaTrader 5...' -ForegroundColor Yellow
  Start-Process $mt5
  Write-Host 'Log in to Exness in MT5 (File -> Login), add XAUUSD to Market Watch, then run this script again.' -ForegroundColor Yellow
  exit 1
}

$env:MT5_TERMINAL_PATH = Split-Path $mt5 -Parent

# 2) Windows Firewall — allow inbound 8765 (VPS + LAN)
$ruleName = 'Bilshenz-MT5-API-8765'
$existing = Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
if (-not $existing) {
  New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 | Out-Null
  Write-Host 'Firewall rule added: TCP 8765 inbound' -ForegroundColor Green
} else {
  Write-Host 'Firewall rule already exists' -ForegroundColor DarkGray
}

# 3) Start Python MT5 API (background job)
$job = Get-Job -Name BilshenzMt5Api -ErrorAction SilentlyContinue
if ($job) { Stop-Job $job -ErrorAction SilentlyContinue; Remove-Job $job -Force -ErrorAction SilentlyContinue }
Write-Host 'Starting MT5 API on port 8765...' -ForegroundColor Green
Start-Job -Name BilshenzMt5Api -ScriptBlock {
  Set-Location $using:ApiDir
  $env:MT5_TERMINAL_PATH = $using:env:MT5_TERMINAL_PATH
  $env:PORT = '8765'
  & (Join-Path $using:ApiDir 'start-api.ps1')
} | Out-Null

Start-Sleep -Seconds 8
try {
  $status = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/status' -TimeoutSec 15
  Write-Host 'MT5 API connected:' ($status.connected) -ForegroundColor Green
  if ($status.account) {
    Write-Host "  Account: $($status.account.login)  Server: $($status.account.server)  Equity: $($status.account.equity)"
  }
} catch {
  Write-Host "API not ready yet: $_" -ForegroundColor Red
  Write-Host 'Check: MT5 logged in, Algo Trading allowed, XAUUSD in Market Watch.'
  exit 1
}

# 4) IPs for VPS config
$lan = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
  $_.IPAddress -notlike '127.*' -and $_.PrefixOrigin -ne 'WellKnown'
} | Where-Object { $_.InterfaceAlias -match 'Wi-Fi|Ethernet' } | Select-Object -First 1).IPAddress

$publicIp = try {
  (Invoke-RestMethod -Uri 'https://api.ipify.org?format=json' -TimeoutSec 8).ip
} catch { $null }

Write-Host ''
Write-Host '=== VPS configuration (/etc/tradingbot.env) ===' -ForegroundColor Cyan
if ($publicIp) {
  Write-Host "MT5_API_URL=http://${publicIp}:8765"
  Write-Host ''
  Write-Host 'Router: forward TCP port 8765 ->' $lan '(this PC)' -ForegroundColor Yellow
} else {
  Write-Host "MT5_API_URL=http://${lan}:8765   (LAN only — VPS cannot reach unless you port-forward)"
}
Write-Host 'FORWARD_DRY_RUN=1   # set 0 only after VPS health check passes'
Write-Host ''
Write-Host 'Test from VPS: curl http://<ip>:8765/api/status'
Write-Host 'Local API job: Get-Job BilshenzMt5Api | Receive-Job'

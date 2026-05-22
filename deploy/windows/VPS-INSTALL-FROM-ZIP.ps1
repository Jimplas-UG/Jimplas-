# Run ON VPS as Administrator. NO git/GitHub required.
# Put Bilshenz-VPS.zip at C:\opt\Bilshenz-VPS.zip (or Desktop) first.
Set-ExecutionPolicy Bypass -Scope Process -Force
$ErrorActionPreference = 'Stop'
$App = 'C:\opt\bilshenz'
$Log = 'C:\opt\repair-run.log'
function L($m) { "$(Get-Date -Format o) $m" | Tee-Object $Log -Append; Write-Host $m }

Start-Transcript -Path $Log -Append -Force
L '=== ZIP INSTALL (no git) ==='
New-Item -ItemType Directory -Force -Path C:\opt, C:\logs\tradingbot, 'C:\ProgramData\Bilshenz' | Out-Null

$zipCandidates = @(
  'C:\opt\Bilshenz-VPS.zip',
  'C:\Users\Administrator\Desktop\Bilshenz-VPS.zip',
  "$env:USERPROFILE\Desktop\Bilshenz-VPS.zip"
)
$ts = Get-ChildItem '\\tsclient\C\Users\*\Desktop\Bilshenz-VPS.zip' -ErrorAction SilentlyContinue | Select-Object -First 1
if ($ts) { $zipCandidates = @($ts.FullName) + $zipCandidates }
$Zip = $zipCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Zip) {
  Write-Host @'

ZIP NOT FOUND. On your PC run:
  cd c:\Users\Amoskole\bsv3\deploy\windows
  .\BUILD-VPS-ZIP.ps1

Then copy Desktop\Bilshenz-VPS.zip to VPS as C:\opt\Bilshenz-VPS.zip
  - RDP with drives enabled, or
  - Provider file upload / paste via panel

'@ -ForegroundColor Red
  Stop-Transcript; pause; exit 1
}
L "Using $Zip"

if (Test-Path $App) { Remove-Item $App -Recurse -Force }
$staging = 'C:\opt\bilshenz-src'
if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
Expand-Archive -Force $Zip $staging
if (Test-Path "$staging\deploy\windows") {
  Move-Item $staging $App -Force
} else {
  New-Item -ItemType Directory -Force -Path $App | Out-Null
  Get-ChildItem $staging | Move-Item -Destination $App -Force
}
L "deploy/windows=$(Test-Path '$App\deploy\windows')"
L "backend=$(Test-Path '$App\backend\package.json')"

foreach ($id in @('Python.Python.3.12', 'OpenJS.NodeJS.LTS')) {
  winget install --id $id -e --accept-package-agreements --accept-source-agreements 2>>$Log
}
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')

Push-Location "$App\backend"
npm install 2>>$Log
npm run strategy:freeze 2>>$Log
Pop-Location

$Py = "$App\mt5_trading_system\python"
if (-not (Test-Path "$Py\.venv")) { python -m venv "$Py\.venv" }
& "$Py\.venv\Scripts\pip.exe" install -q fastapi uvicorn MetaTrader5 pydantic requests 2>>$Log

$ef = 'C:\ProgramData\Bilshenz\tradingbot.env'
if (-not (Test-Path $ef)) {
  Copy-Item "$App\deploy\windows\tradingbot.env.example" $ef -ErrorAction SilentlyContinue
}
if (-not (Test-Path $ef)) {
  @('STRATEGY_FREEZE=1','PRODUCTION_MODE=1','MT5_API_URL=http://127.0.0.1:8765','MT5_SYMBOL=XAUUSD',
    'MT5_TERMINAL_PATH=C:\Program Files\MetaTrader 5 Exness','FORWARD_DRY_RUN=1',
    "DESK_API_KEY=$([guid]::NewGuid().ToString('N'))",'TRADINGBOT_LOG_DIR=C:\logs\tradingbot') | Set-Content $ef
} else {
  (Get-Content $ef) -replace 'change-me-long-random-secret', ([guid]::NewGuid().ToString('N')) `
    -replace 'FORWARD_DRY_RUN=.*', 'FORWARD_DRY_RUN=1' | Set-Content $ef
}

$mt5 = 'C:\Program Files\MetaTrader 5 Exness'
if (Test-Path "$mt5\terminal64.exe") {
  if (-not (Get-Process terminal64 -EA SilentlyContinue)) { Start-Process "$mt5\terminal64.exe"; Start-Sleep 20 }
} else { L 'Install Exness MT5 on VPS, login, XAUUSD' }

& "$App\deploy\windows\install-scheduled-tasks.ps1" -AppDir $App
& "$App\deploy\windows\install-log-rotation.ps1" -ErrorAction SilentlyContinue
& "$App\deploy\windows\start-bot.ps1"

Start-Sleep 10
try { Invoke-RestMethod http://127.0.0.1:8765/health -TimeoutSec 5 | Format-List } catch { L "8765: $_" }
try { Invoke-RestMethod http://127.0.0.1:8765/api/status -TimeoutSec 8 | Format-List } catch { L "status: $_" }

L 'ZIP_INSTALL_DONE'
Stop-Transcript
Write-Host 'Log: C:\opt\repair-run.log' -ForegroundColor Green
pause

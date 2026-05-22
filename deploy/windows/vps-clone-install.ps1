# VPS: clone from GitHub and install. Requires deploy/ on GitHub main (pushed).
Set-ExecutionPolicy Bypass -Scope Process -Force
$ErrorActionPreference = 'Stop'
$App = 'C:\opt\bilshenz'
$Repo = 'https://github.com/Jimplas-UG/Jimplas-.git'
$Log = 'C:\opt\vps-clone-install.log'
Start-Transcript -Path $Log -Append -Force

function Fail($m) { Write-Host $m -ForegroundColor Red; Stop-Transcript; pause; exit 1 }

Write-Host '=== GitHub clone install ===' -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path C:\opt, C:\logs\tradingbot, 'C:\ProgramData\Bilshenz' | Out-Null

# Network test
try { Invoke-WebRequest -Uri 'https://github.com' -UseBasicParsing -TimeoutSec 15 | Out-Null }
catch { Fail "VPS cannot reach github.com — use BUILD-VPS-ZIP.ps1 on PC instead. $_" }

if (-not (Get-Command git -EA SilentlyContinue)) {
  winget install Git.Git -e --accept-package-agreements --accept-source-agreements
}
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')

if (Test-Path $App) { Remove-Item $App -Recurse -Force }
git clone --depth 1 --branch main $Repo $App 2>&1 | Tee-Object $Log -Append
if ($LASTEXITCODE -ne 0) { Fail "git clone failed — see $Log" }

$checks = @(
  "$App\backend\package.json",
  "$App\mt5_trading_system\python\main.py",
  "$App\deploy\windows\production-setup.ps1"
)
foreach ($c in $checks) {
  if (-not (Test-Path $c)) { Fail "Missing after clone: $c — push deploy/ to GitHub from dev PC" }
  Write-Host "OK $c" -ForegroundColor DarkGray
}

& "$App\deploy\windows\production-setup.ps1" -AppDir $App 2>&1 | Tee-Object $Log -Append
& "$App\deploy\windows\install-mt5-terminal-task.ps1" -ErrorAction SilentlyContinue

Write-Host 'CLONE_INSTALL_DONE' -ForegroundColor Green
Write-Host "Log: $Log"
Stop-Transcript
pause

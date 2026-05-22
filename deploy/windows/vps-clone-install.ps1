# VPS: clone from GitHub and install. ASCII-only (safe for iwr download).
Set-ExecutionPolicy Bypass -Scope Process -Force
$ErrorActionPreference = 'Stop'
$App = 'C:\opt\bilshenz'
$Repo = 'https://github.com/Jimplas-UG/Jimplas-.git'
$Log = 'C:\opt\vps-clone-install.log'
Start-Transcript -Path $Log -Append -Force

function Fail([string]$m) {
  Write-Host $m -ForegroundColor Red
  Stop-Transcript
  pause
  exit 1
}

Write-Host '=== GitHub clone install ===' -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path C:\opt, C:\logs\tradingbot, 'C:\ProgramData\Bilshenz' | Out-Null

try {
  Invoke-WebRequest -Uri 'https://github.com' -UseBasicParsing -TimeoutSec 15 | Out-Null
} catch {
  Fail ('VPS cannot reach github.com - use BUILD-VPS-ZIP.ps1 on PC instead. ' + $_.Exception.Message)
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  winget install Git.Git -e --accept-package-agreements --accept-source-agreements
}
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')

if (Test-Path $App) { Remove-Item $App -Recurse -Force }
git clone --depth 1 --branch main $Repo $App 2>&1 | Tee-Object $Log -Append
if ($LASTEXITCODE -ne 0) { Fail ('git clone failed - see ' + $Log) }

$checks = @(
  (Join-Path $App 'backend\package.json'),
  (Join-Path $App 'mt5_trading_system\python\main.py'),
  (Join-Path $App 'deploy\windows\production-setup.ps1')
)
foreach ($c in $checks) {
  if (-not (Test-Path $c)) { Fail ('Missing after clone: ' + $c) }
  Write-Host ('OK ' + $c) -ForegroundColor DarkGray
}

$setup = Join-Path $App 'deploy\windows\production-setup.ps1'
& $setup -AppDir $App 2>&1 | Tee-Object $Log -Append

$mt5Task = Join-Path $App 'deploy\windows\install-mt5-terminal-task.ps1'
if (Test-Path $mt5Task) { & $mt5Task -ErrorAction SilentlyContinue }

Write-Host 'CLONE_INSTALL_DONE' -ForegroundColor Green
Write-Host ('Log: ' + $Log)
Stop-Transcript
pause

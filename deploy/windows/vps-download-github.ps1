# VPS install via GitHub ZIP (no git). Paste on VPS Administrator PowerShell.
Set-ExecutionPolicy Bypass -Scope Process -Force
$ErrorActionPreference = 'Stop'
$Log = 'C:\opt\vps-download.log'
Start-Transcript -Path $Log -Append -Force

$App = 'C:\opt\bilshenz'
$ZipUrl = 'https://github.com/Jimplas-UG/Jimplas-/archive/refs/heads/main.zip'
$ZipFile = 'C:\opt\repo-main.zip'
$Staging = 'C:\opt\repo-extract'

Write-Host 'Downloading from GitHub (zip)...' -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path C:\opt, C:\logs\tradingbot, 'C:\ProgramData\Bilshenz' | Out-Null

try {
  Invoke-WebRequest -Uri $ZipUrl -OutFile $ZipFile -UseBasicParsing -TimeoutSec 300
} catch {
  Write-Host ('DOWNLOAD FAILED: ' + $_.Exception.Message) -ForegroundColor Red
  Write-Host 'Use BUILD-VPS-ZIP.ps1 on your PC and copy Bilshenz-VPS.zip to C:\opt\' -ForegroundColor Yellow
  Stop-Transcript; pause; exit 1
}

if (Test-Path $Staging) { Remove-Item $Staging -Recurse -Force }
if (Test-Path $App) { Remove-Item $App -Recurse -Force }
Expand-Archive -Force $ZipFile $Staging

$inner = Get-ChildItem $Staging -Directory | Select-Object -First 1
if (-not $inner) { Write-Host 'ZIP EMPTY'; Stop-Transcript; pause; exit 1 }
Move-Item $inner.FullName $App -Force
Write-Host ('Extracted to ' + $App) -ForegroundColor Green

$setup = Join-Path $App 'deploy\windows\production-setup.ps1'
if (-not (Test-Path $setup)) {
  Write-Host 'CLONE_BAD - deploy\windows missing in zip'
  Get-ChildItem $App -Name | ForEach-Object { Write-Host $_ }
  Stop-Transcript; pause; exit 1
}

powershell -ExecutionPolicy Bypass -File $setup -AppDir $App
Write-Host 'ZIP_INSTALL_DONE' -ForegroundColor Green
Stop-Transcript
pause

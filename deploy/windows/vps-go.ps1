# Same as vps-clone-install.ps1 - use this URL if old file cached on VPS.
# https://raw.githubusercontent.com/Jimplas-UG/Jimplas-/main/deploy/windows/vps-go.ps1
Set-ExecutionPolicy Bypass -Scope Process -Force
$ErrorActionPreference = 'Stop'
$App = 'C:\opt\bilshenz'
$Repo = 'https://github.com/Jimplas-UG/Jimplas-.git'
$Log = 'C:\opt\vps-go.log'
Start-Transcript -Path $Log -Append -Force
function Fail([string]$m) { Write-Host $m -ForegroundColor Red; Stop-Transcript; pause; exit 1 }
New-Item -ItemType Directory -Force -Path C:\opt, C:\logs\tradingbot, 'C:\ProgramData\Bilshenz' | Out-Null
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  winget install Git.Git -e --accept-package-agreements --accept-source-agreements
}
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
if (Test-Path $App) { Remove-Item $App -Recurse -Force }
git clone --depth 1 --branch main $Repo $App 2>&1 | Tee-Object $Log -Append
if ($LASTEXITCODE -ne 0) { Fail ('git clone failed') }
$p = Join-Path $App 'deploy\windows\production-setup.ps1'
if (-not (Test-Path $p)) { Fail ('missing deploy\windows') }
& $p -AppDir $App 2>&1 | Tee-Object $Log -Append
Write-Host 'VPS_GO_DONE' -ForegroundColor Green
Write-Host ('Log: ' + $Log)
Stop-Transcript
pause

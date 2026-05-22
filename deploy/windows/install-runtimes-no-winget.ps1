# Install Python 3.12 + Node.js LTS without winget (Windows Server / minimal VPS).
#Requires -RunAsAdministrator
Set-ExecutionPolicy Bypass -Scope Process -Force
$ErrorActionPreference = 'Stop'
$Dl = 'C:\opt\installers'
New-Item -ItemType Directory -Force -Path $Dl | Out-Null

function Refresh-Path {
  $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
    [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Ensure-Python {
  Refresh-Path
  $py = Get-Command python -ErrorAction SilentlyContinue
  if ($py) { Write-Host ('Python OK: ' + $py.Source); return }
  $pyExe = Join-Path $Dl 'python-3.12.8-amd64.exe'
  if (-not (Test-Path $pyExe)) {
    Write-Host 'Downloading Python 3.12.8...' -ForegroundColor Cyan
    Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe' -OutFile $pyExe -UseBasicParsing
  }
  Write-Host 'Installing Python (silent)...' -ForegroundColor Cyan
  Start-Process -FilePath $pyExe -ArgumentList '/quiet', 'InstallAllUsers=1', 'PrependPath=1', 'Include_pip=1' -Wait
  Refresh-Path
  if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    $fallback = 'C:\Program Files\Python312\python.exe'
    if (Test-Path $fallback) {
      $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
      if ($machinePath -notlike '*Python312*') {
        [Environment]::SetEnvironmentVariable('Path', $machinePath + ';C:\Program Files\Python312;C:\Program Files\Python312\Scripts', 'Machine')
      }
      Refresh-Path
    }
  }
  if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw 'Python install failed' }
  Write-Host ('Python OK: ' + (Get-Command python).Source) -ForegroundColor Green
}

function Ensure-Node {
  Refresh-Path
  if (Get-Command npm -ErrorAction SilentlyContinue) { Write-Host ('npm OK: ' + (Get-Command npm).Source); return }
  $msi = Join-Path $Dl 'node-lts-x64.msi'
  if (-not (Test-Path $msi)) {
    Write-Host 'Downloading Node.js LTS...' -ForegroundColor Cyan
    Invoke-WebRequest -Uri 'https://nodejs.org/dist/v22.14.0/node-v22.14.0-x64.msi' -OutFile $msi -UseBasicParsing
  }
  Write-Host 'Installing Node.js (silent)...' -ForegroundColor Cyan
  Start-Process -FilePath 'msiexec.exe' -ArgumentList '/i', $msi, '/quiet', '/norestart' -Wait
  Refresh-Path
  if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw 'Node/npm install failed' }
  Write-Host ('Node OK: ' + (node --version)) -ForegroundColor Green
}

Ensure-Python
Ensure-Node
Write-Host 'RUNTIMES_OK' -ForegroundColor Green

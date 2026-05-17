# Start Bilshenz MT5 Python API (port 8765). Run on the same PC as MetaTrader 5.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function Find-Python {
  $candidates = @(
    'py -3',
    'python',
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    'C:\Program Files\Python312\python.exe'
  )
  foreach ($c in $candidates) {
    try {
      $exe = if ($c -match '\.exe$') { $c } else { $c.Split(' ')[0] }
      if ($c -match '\.exe$' -and -not (Test-Path $exe)) { continue }
      $v = & $c -c "import sys; print(sys.executable)" 2>$null
      if ($LASTEXITCODE -eq 0 -and $v -and $v -notmatch 'WindowsApps') { return $c }
    } catch { }
  }
  return $null
}

$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$pip = Join-Path $PSScriptRoot '.venv\Scripts\pip.exe'

if (-not (Test-Path $python)) {
  $py = Find-Python
  if (-not $py) {
    Write-Host ''
    Write-Host 'Python 3 is not installed (required for MT5 app connect).' -ForegroundColor Red
    Write-Host 'Install 64-bit Python: https://www.python.org/downloads/windows/' -ForegroundColor Yellow
    Write-Host 'During setup, check "Add python.exe to PATH". Then run this script again.' -ForegroundColor Yellow
    Write-Host ''
    exit 1
  }
  Write-Host 'Creating virtual environment...'
  & $py -m venv .venv
}

if (-not (Test-Path $python)) {
  Write-Host 'Failed to create .venv — install Python 3 (64-bit) and retry.' -ForegroundColor Red
  exit 1
}

& $pip install -q -r requirements.txt

$ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
  $_.IPAddress -notlike '127.*' -and $_.InterfaceAlias -match 'Wi-Fi|Ethernet'
} | Select-Object -First 1).IPAddress

Write-Host ''
Write-Host 'Starting MT5 API on http://0.0.0.0:8765' -ForegroundColor Green
if ($ip) {
  Write-Host "On your phone use: http://${ip}:8765" -ForegroundColor Cyan
}
Write-Host 'Keep this window open. Press Ctrl+C to stop.' -ForegroundColor DarkGray
Write-Host ''

$env:PORT = '8765'
& $python main.py

Set-ExecutionPolicy Bypass -Scope Process -Force
if (-not (Test-Path C:\opt)) { New-Item -ItemType Directory -Force -Path C:\opt | Out-Null }
if (-not (Test-Path C:\opt\bilshenz\.git)) {
  git clone https://github.com/Jimplas-UG/Jimplas-.git C:\opt\bilshenz
}
Set-Location C:\opt\bilshenz
git pull 2>$null
& .\deploy\windows\bootstrap-vps.ps1

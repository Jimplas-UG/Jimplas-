# Run ON VPS as Administrator (RDP or web console). Finds bundle from Desktop or tsclient.
Set-ExecutionPolicy Bypass -Scope Process -Force
$ErrorActionPreference = 'Stop'
$App = 'C:\opt\bilshenz'
$Log = 'C:\opt\vps-install.log'
function L($m) { "$(Get-Date -Format o) $m" | Tee-Object $Log -Append; Write-Host $m }

L '=== EXPERT VPS install ==='
New-Item -ItemType Directory -Force -Path C:\opt, C:\logs\tradingbot, 'C:\ProgramData\Bilshenz' | Out-Null

$zipCandidates = @(
  'C:\Users\Administrator\Desktop\Bilshenz-VPS.zip',
  "$env:USERPROFILE\Desktop\Bilshenz-VPS.zip",
  'C:\opt\Bilshenz-VPS.zip'
)
$ts = Get-ChildItem '\\tsclient\C\Users\*\Desktop\Bilshenz-VPS.zip' -ErrorAction SilentlyContinue | Select-Object -First 1
if ($ts) { $zipCandidates = @($ts.FullName) + $zipCandidates }
$Zip = $zipCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Zip) {
  throw 'Bilshenz-VPS.zip not found. On your PC run EXPERT-DEPLOY.ps1 first, then RDP with drives shared.'
}

L "Using bundle $Zip"
if (Test-Path $App) { Remove-Item $App -Recurse -Force }
Expand-Archive -Force $Zip C:\opt\bilshenz-src
if (Test-Path C:\opt\bilshenz-src\deploy) {
  Move-Item C:\opt\bilshenz-src $App -Force
} else {
  New-Item -ItemType Directory -Force -Path $App | Out-Null
  Move-Item C:\opt\bilshenz-src\* $App -Force
}

# Remote admin for future (open cloud firewall 22 + 5985 after this)
& "$App\deploy\windows\enable-remote-admin.ps1" 2>&1 | Tee-Object $Log -Append

$install = "$App\deploy\windows\vps-full-install.ps1"
if (-not (Test-Path $install)) { throw "Missing $install in bundle" }
& $install 2>&1 | Tee-Object $Log -Append

L '=== FINISHED ==='
L 'Next: install MetaTrader 5 Exness on this VPS, login demo/live, add XAUUSD'
L 'Then: set FORWARD_DRY_RUN=0 in C:\ProgramData\Bilshenz\tradingbot.env and run deploy\windows\start-bot.ps1'

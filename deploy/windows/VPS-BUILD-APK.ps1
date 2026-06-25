# Build production Android APK on the VPS (local Gradle or EAS cloud).
# Run from repo root: powershell -ExecutionPolicy Bypass -File .\deploy\windows\VPS-BUILD-APK.ps1
#Requires -RunAsAdministrator
param(
  [string]$DeskApiUrl = '',
  [string]$DeskApiKey = '',
  [string]$BinanceApiUrl = '',
  [switch]$UseEasCloud
)
Set-ExecutionPolicy Bypass -Scope Process -Force
$ErrorActionPreference = 'Stop'

$Repo = if ($PSScriptRoot -match 'deploy\\windows') {
  (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
} else {
  'C:\opt\bilshenz'
}
$Frontend = Join-Path $Repo 'frontend'
$BuildScript = Join-Path $Frontend 'scripts\build-android-release.ps1'
if (-not (Test-Path $BuildScript)) { throw "Missing $BuildScript" }

$envFile = 'C:\ProgramData\Bilshenz\tradingbot.env'
if (Test-Path $envFile) {
  & (Join-Path $PSScriptRoot 'Import-TradingBotEnv.ps1') -EnvFile $envFile
}

if (-not $DeskApiKey -and $env:DESK_API_KEY) { $DeskApiKey = $env:DESK_API_KEY }
if (-not $DeskApiUrl) {
  if ($env:EXPO_PUBLIC_DESK_API_URL) {
    $DeskApiUrl = $env:EXPO_PUBLIC_DESK_API_URL
  } elseif ($env:DESK_API_URL) {
    $DeskApiUrl = $env:DESK_API_URL
  } else {
    $port = if ($env:DESK_API_PORT) { $env:DESK_API_PORT } else { '8791' }
    try {
      $ip = (Invoke-RestMethod -Uri 'https://api.ipify.org' -TimeoutSec 10).Trim()
      if ($ip) { $DeskApiUrl = "http://${ip}:${port}" }
    } catch {
      Write-Warning 'Could not detect public IP; pass -DeskApiUrl explicitly.'
    }
  }
}

if (-not $env:ANDROID_HOME) { $env:ANDROID_HOME = 'C:\Android\android-sdk' }
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
  [Environment]::GetEnvironmentVariable('Path', 'User')

$sdkProps = Join-Path $Frontend 'android\local.properties'
if ((Test-Path $env:ANDROID_HOME) -and -not (Test-Path $sdkProps)) {
  $sdkDir = ($env:ANDROID_HOME -replace '\\', '\\')
  "sdk.dir=$sdkDir" | Set-Content -Path $sdkProps -Encoding ASCII
}

Write-Host "==> VPS APK build (frontend: $Frontend)" -ForegroundColor Cyan
if ($DeskApiUrl) { Write-Host "    Desk API: $DeskApiUrl" -ForegroundColor DarkGray }
if (-not $BinanceApiUrl -and $DeskApiUrl -and $DeskApiUrl -notmatch '127\.0\.0\.1|localhost') {
  $BinanceApiUrl = ($DeskApiUrl.TrimEnd('/') + '/v1/binance')
}
if ($BinanceApiUrl) { Write-Host "    Binance API: $BinanceApiUrl" -ForegroundColor DarkGray }
if ($UseEasCloud) { Write-Host '    Mode: EAS cloud' -ForegroundColor DarkGray }

$buildArgs = @{}
if ($DeskApiUrl) { $buildArgs.DeskApiUrl = $DeskApiUrl }
if ($DeskApiKey) { $buildArgs.DeskApiKey = $DeskApiKey }
if ($BinanceApiUrl) { $buildArgs.BinanceApiUrl = $BinanceApiUrl }
if ($UseEasCloud) { $buildArgs.UseEasCloud = $true }

& $BuildScript @buildArgs
exit $LASTEXITCODE

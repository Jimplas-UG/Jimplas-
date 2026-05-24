# Production release APK — verify, build (EAS signed or local Gradle), export artifact info.

#Requires -RunAsAdministrator

param(

  [string]$DeskApiUrl = '',

  [string]$DeskApiKey = '',

  [string]$Mt5ApiUrl = '',

  [switch]$UseEasCloud

)

$ErrorActionPreference = 'Stop'

$Root = Split-Path $PSScriptRoot -Parent

Set-Location $Root



if ($DeskApiUrl) { $env:EXPO_PUBLIC_DESK_API_URL = $DeskApiUrl }

if ($DeskApiKey) { $env:EXPO_PUBLIC_DESK_API_KEY = $DeskApiKey }

if ($Mt5ApiUrl) {
  $env:EXPO_PUBLIC_MT5_API_URL = $Mt5ApiUrl
} elseif ($DeskApiUrl -and $DeskApiUrl -notmatch '127\.0\.0\.1|localhost') {
  $env:EXPO_PUBLIC_MT5_API_URL = ($DeskApiUrl -replace ':8791/?$', ':8765')
}



Write-Host '==> Assets' -ForegroundColor Cyan

node scripts/generate-assets.js



Write-Host '==> Dependencies' -ForegroundColor Cyan

npm install --include=dev



$env:BABEL_ENV = 'production'

$env:EAS_BUILD = 'true'

$env:EXPO_PUBLIC_DESK_LOCAL = '0'

$env:EXPO_PUBLIC_DESK_REMOTE = '1'



Write-Host '==> Production stability checks' -ForegroundColor Cyan

node scripts/verify-release-build.js

if ($LASTEXITCODE -ne 0) { throw 'verify-release-build failed' }



if ($UseEasCloud) {

  Write-Host '==> EAS cloud build (signed APK)' -ForegroundColor Cyan

  $prevEap = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  $easLog = @(npx eas-cli build --platform android --profile production --non-interactive 2>&1)
  $easExit = $LASTEXITCODE
  $ErrorActionPreference = $prevEap
  $easText = $easLog -join "`n"
  $easLog | Out-Host

  if ($easExit -ne 0 -and $easText -notmatch 'builds/[a-f0-9-]{36}') {
    throw 'EAS build failed'
  }

  $buildId = [regex]::Match(($easLog -join "`n"), 'builds/([a-f0-9-]{36})').Groups[1].Value

  if ($buildId) {

    $json = npx eas-cli build:view $buildId --json 2>&1 | Out-String

    $apkUrl = [regex]::Match($json, '"applicationArchiveUrl":\s*"([^"]+)"').Groups[1].Value

    $dist = Join-Path $Root 'dist'

    New-Item -ItemType Directory -Force -Path $dist | Out-Null

    if ($apkUrl) {

      Set-Content -Path (Join-Path $dist 'bilshenz-release-url.txt') -Value $apkUrl -Encoding ASCII

      Write-Host "APK_URL $apkUrl" -ForegroundColor Green

      try {

        Invoke-WebRequest -Uri $apkUrl -OutFile (Join-Path $dist 'bilshenz-release-signed.apk') -UseBasicParsing

        Write-Host "APK_OK $(Join-Path $dist 'bilshenz-release-signed.apk')" -ForegroundColor Green

      } catch {

        Write-Warning "Download from URL manually: $apkUrl"

      }

    }

    Write-Host "BUILD_PAGE https://expo.dev/accounts/jimplas/projects/bilshenz-desk/builds/$buildId" -ForegroundColor Cyan

  }

  exit 0

}



Write-Host '==> Install JDK + Android SDK (if missing)' -ForegroundColor Cyan

if (-not (Get-Command java -ErrorAction SilentlyContinue)) {

  choco install microsoft-openjdk17 -y --no-progress

}

if (-not $env:ANDROID_HOME) {

  choco install android-sdk -y --no-progress 2>$null

  $env:ANDROID_HOME = 'C:\Android\android-sdk'

  $env:Path += ";$env:ANDROID_HOME\platform-tools;$env:ANDROID_HOME\cmdline-tools\latest\bin"

}



Write-Host '==> Prebuild + Gradle release' -ForegroundColor Cyan

$env:NODE_ENV = 'production'

npx expo prebuild --platform android --clean

$sdkHome = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { 'C:\Android\android-sdk' }

if (Test-Path $sdkHome) {

  $sdkDir = ($sdkHome -replace '\\', '\\')

  "sdk.dir=$sdkDir" | Set-Content -Path (Join-Path $Root 'android\local.properties') -Encoding ASCII

}

Push-Location android

.\gradlew.bat assembleRelease

Pop-Location



$apk = Get-ChildItem -Path (Join-Path $Root 'android\app\build\outputs\apk\release') -Filter *.apk -Recurse |

  Sort-Object LastWriteTime -Descending |

  Select-Object -First 1

if ($apk) {

  $dest = Join-Path $Root 'dist\bilshenz-release.apk'

  New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null

  Copy-Item $apk.FullName $dest -Force

  $hash = (Get-FileHash $dest -Algorithm SHA256).Hash

  @(

    "path=$dest",

    "sha256=$hash",

    "signed=debug-or-local-keystore (use -UseEasCloud for Play-ready signing)",

    "builtAt=$(Get-Date -Format o)"

  ) | Set-Content (Join-Path $Root 'dist\bilshenz-release-manifest.txt') -Encoding ASCII

  Write-Host "APK_OK $dest" -ForegroundColor Green

  Write-Host "SHA256 $hash" -ForegroundColor DarkGray

} else {

  throw 'APK not found after gradle build'

}



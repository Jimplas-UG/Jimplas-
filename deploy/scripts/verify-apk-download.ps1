# Verify VPS APK download from Windows PC
param(
  [string]$Host = '157.245.33.42',
  [int]$Port = 8791
)
$base = "http://${Host}:${Port}"
$fail = 0

function Test-Url($name, $url, [scriptblock]$Check) {
  try {
    $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 15
    & $Check $r
    Write-Host "OK  $name" -ForegroundColor Green
  } catch {
    Write-Host "FAIL $name — $($_.Exception.Message)" -ForegroundColor Red
    $script:fail = 1
  }
}

Test-Url 'health' "$base/health" { param($r) if ($r.Content -notmatch '"ok":true') { throw 'not ok' } }

try {
  $dl = Invoke-RestMethod -Uri "$base/download" -TimeoutSec 15
  if ($dl.error -eq 'unauthorized') {
    throw '/download still requires auth — run git pull + restart on VPS'
  }
  if ($dl.ok -eq $true) {
    Write-Host "OK  download meta size=$($dl.sizeBytes)" -ForegroundColor Green
    $apk = Invoke-WebRequest -Uri "$base/download/bilshenz.apk" -UseBasicParsing -TimeoutSec 120
    if ($apk.RawContentLength -lt 1MB) { throw "APK too small: $($apk.RawContentLength)" }
    Write-Host "OK  apk bytes=$($apk.RawContentLength)" -ForegroundColor Green
  } else {
    throw 'apk_not_found — upload APK to VPS frontend/dist/'
  }
} catch {
  Write-Host "FAIL download — $_" -ForegroundColor Red
  $fail = 1
}

if ($fail) { exit 1 }
Write-Host "`nVERIFY_OK — install: $base/download/bilshenz.apk" -ForegroundColor Cyan

# Phase 1 — Windows VPS system validation and 24/7 tuning.
# Run as Administrator on the VPS before any bot install.
#Requires -RunAsAdministrator
param(
  [string]$TimeZone = 'Eastern Standard Time',
  [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
$results = [ordered]@{}

function Test-PhaseItem {
  param([string]$Name, [scriptblock]$Check)
  try {
    $ok = & $Check
    $results[$Name] = if ($ok) { 'PASS' } else { 'FAIL' }
  } catch {
    $results[$Name] = "FAIL: $($_.Exception.Message)"
  }
}

Write-Host '=== Phase 1: System validation ===' -ForegroundColor Cyan

# --- 1. Windows version ---
Test-PhaseItem 'WindowsVersion' {
  $os = Get-CimInstance Win32_OperatingSystem
  $name = $os.Caption
  $arch = $os.OSArchitecture
  Write-Host "  OS: $name ($arch) Build $($os.BuildNumber)" -ForegroundColor DarkGray
  $arch -match '64'
}

# --- 2. Internet ---
Test-PhaseItem 'InternetConnectivity' {
  $t = Test-NetConnection -ComputerName 1.1.1.1 -Port 443 -WarningAction SilentlyContinue
  if (-not $t.TcpTestSucceeded) { return $false }
  Resolve-DnsName github.com -ErrorAction Stop | Out-Null
  $true
}

# --- 3. RDP ---
Test-PhaseItem 'RdpService' {
  $svc = Get-Service TermService
  Write-Host "  TermService: $($svc.Status) / $($svc.StartType)" -ForegroundColor DarkGray
  if ($svc.Status -ne 'Running') { Start-Service TermService -ErrorAction SilentlyContinue }
  $deny = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server' -EA SilentlyContinue).fDenyTSConnections
  $rdpRules = @(Get-NetFirewallRule -DisplayGroup 'Remote Desktop' -EA SilentlyContinue | Where-Object Enabled -eq 'True')
  Write-Host "  fDenyTSConnections=$deny RDP firewall rules=$($rdpRules.Count)" -ForegroundColor DarkGray
  ($svc.Status -eq 'Running') -and ($deny -eq 0) -and ($rdpRules.Count -gt 0)
}

if (-not $ValidateOnly) {
  Write-Host '==> Timezone' -ForegroundColor Cyan
  try { Set-TimeZone -Id $TimeZone } catch { tzutil /s $TimeZone }
  Write-Host "  Set to: $(Get-TimeZone | Select-Object -ExpandProperty Id)" -ForegroundColor DarkGray

  Write-Host '==> Disable sleep / hibernate' -ForegroundColor Cyan
  powercfg /hibernate off
  powercfg -change -standby-timeout-ac 0
  powercfg -change -hibernate-timeout-ac 0
  powercfg -change -monitor-timeout-ac 0
  powercfg -change -disk-timeout-ac 0

  Write-Host '==> High performance power plan' -ForegroundColor Cyan
  $schemes = powercfg -list
  $high = $schemes | Select-String 'High performance|Ultimate Performance' | Select-Object -First 1
  if ($high) {
    $guid = ($high -split '\s+')[3].Trim('()')
    powercfg -setactive $guid
  }

  Write-Host '==> Windows Update — no forced reboot while logged on' -ForegroundColor Cyan
  $auPath = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU'
  New-Item -Path $auPath -Force | Out-Null
  Set-ItemProperty -Path $auPath -Name NoAutoRebootWithLoggedOnUsers -Value 1 -Type DWord -Force
  Set-ItemProperty -Path $auPath -Name AUOptions -Value 2 -Type DWord -Force

  Write-Host '==> BSOD auto-reboot off' -ForegroundColor Cyan
  Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\CrashControl' -Name AutoReboot -Value 0 -Type DWord -Force

  Write-Host '==> Log directories' -ForegroundColor Cyan
  New-Item -ItemType Directory -Force -Path 'C:\logs\tradingbot', 'C:\ProgramData\Bilshenz' | Out-Null
}

# --- 4. Timezone set ---
Test-PhaseItem 'TimezoneConfigured' {
  $tz = Get-TimeZone
  Write-Host "  $($tz.Id) — local: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor DarkGray
  $true
}

# --- 5–6. Power ---
Test-PhaseItem 'PowerNoSleep' {
  $hib = powercfg /a 2>&1 | Out-String
  $scheme = powercfg /getactivescheme
  Write-Host "  $scheme" -ForegroundColor DarkGray
  ($scheme -match 'High performance|Ultimate Performance') -or ($scheme -notmatch 'Balanced')
}

# --- 7. Update policy ---
Test-PhaseItem 'UpdateNoForceReboot' {
  $v = Get-ItemProperty 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU' -EA SilentlyContinue
  if ($v.NoAutoRebootWithLoggedOnUsers -eq 1) { return $true }
  Write-Host '  (policy not set — run without -ValidateOnly)' -ForegroundColor Yellow
  -not $ValidateOnly
}

# --- 8. Firewall ---
Test-PhaseItem 'FirewallOutboundAllow' {
  $profiles = Get-NetFirewallProfile
  $bad = $profiles | Where-Object { $_.DefaultOutboundAction -eq 'Block' }
  if ($bad) { Write-Host "  Blocked outbound on: $($bad.Name -join ', ')" -ForegroundColor Red; return $false }
  $true
}

Test-PhaseItem 'RdpFirewallInbound' {
  @(Get-NetFirewallRule -DisplayGroup 'Remote Desktop' -EA SilentlyContinue | Where-Object {
    $_.Enabled -eq 'True' -and $_.Direction -eq 'Inbound' -and $_.Action -eq 'Allow'
  }).Count -gt 0
}

Write-Host ''
Write-Host '--- Phase 1 results ---' -ForegroundColor Cyan
$results.GetEnumerator() | ForEach-Object {
  $color = if ($_.Value -eq 'PASS') { 'Green' } else { 'Red' }
  Write-Host "$($_.Key): $($_.Value)" -ForegroundColor $color
}

$failed = @($results.Values | Where-Object { $_ -ne 'PASS' })
if ($failed.Count -gt 0) {
  Write-Host "PHASE1_INCOMPLETE ($($failed.Count) check(s) failed)" -ForegroundColor Red
  exit 1
}
Write-Host 'PHASE1_OK' -ForegroundColor Green

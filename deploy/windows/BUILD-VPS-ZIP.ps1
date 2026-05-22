# Run on YOUR PC (not VPS). Creates zip - no GitHub needed on VPS.
$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Desktop = [Environment]::GetFolderPath('Desktop')
$Zip = Join-Path $Desktop 'Bilshenz-VPS.zip'

Write-Host 'Building bundle...' -ForegroundColor Cyan
if (Test-Path $Zip) { Remove-Item $Zip -Force }
Compress-Archive -Path @(
  (Join-Path $RepoRoot 'deploy\windows'),
  (Join-Path $RepoRoot 'backend'),
  (Join-Path $RepoRoot 'mt5_trading_system\python')
) -DestinationPath $Zip -CompressionLevel Fastest -Force

$mb = [math]::Round((Get-Item $Zip).Length / 1MB, 2)
Copy-Item (Join-Path $PSScriptRoot 'VPS-INSTALL-FROM-ZIP.ps1') (Join-Path $Desktop 'VPS-INSTALL-FROM-ZIP.ps1') -Force

Write-Host ''
Write-Host 'CREATED:' -ForegroundColor Green
Write-Host "  $Zip  ($mb MB)"
Write-Host "  $(Join-Path $Desktop 'VPS-INSTALL-FROM-ZIP.ps1')"
Write-Host ''
Write-Host 'NEXT - pick ONE way to get zip onto VPS:' -ForegroundColor Yellow
Write-Host '  A) RDP: enable drive sharing, connect, copy zip to C:\opt\Bilshenz-VPS.zip'
Write-Host '  B) Provider panel: upload zip to VPS, move to C:\opt\Bilshenz-VPS.zip'
Write-Host '  C) On VPS run VPS-INSTALL-FROM-ZIP.ps1 (from Desktop or C:\opt\)'

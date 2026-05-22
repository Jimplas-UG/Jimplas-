$LogDir = 'C:\logs\tradingbot'
$Archive = Join-Path $LogDir 'archive'
New-Item -ItemType Directory -Force -Path $Archive | Out-Null
$stamp = Get-Date -Format 'yyyy-MM-dd'
Get-ChildItem $LogDir -File | Where-Object { $_.Extension -match '\.(log|jsonl)$' } | ForEach-Object {
  $dest = Join-Path $Archive ($_.BaseName + '_' + $stamp + $_.Extension)
  if (-not (Test-Path $dest)) { Copy-Item $_.FullName $dest }
  Clear-Content $_.FullName -ErrorAction SilentlyContinue
}
Get-ChildItem $Archive -File | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-14) } | Remove-Item -Force

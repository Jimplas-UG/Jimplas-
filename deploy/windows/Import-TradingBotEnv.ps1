# Loads C:\ProgramData\Bilshenz\tradingbot.env into process env (no secret output).
param(
  [string]$EnvFile = 'C:\ProgramData\Bilshenz\tradingbot.env'
)
if (-not (Test-Path $EnvFile)) {
  throw "Missing env file: $EnvFile - copy tradingbot.env.example first."
}
Get-Content $EnvFile | ForEach-Object {
  $line = $_.Trim()
  if (-not $line -or $line.StartsWith('#')) { return }
  $i = $line.IndexOf('=')
  if ($i -lt 1) { return }
  $key = $line.Substring(0, $i).Trim()
  $val = $line.Substring($i + 1).Trim()
  [Environment]::SetEnvironmentVariable($key, $val, 'Process')
}

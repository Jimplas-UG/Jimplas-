param(
    [string]$ConfigPath = 'C:\ProgramData\Bilshenz\telegram.env'
)

if (-not (Test-Path $ConfigPath)) {
    Write-Output "Telegram not configured. Create $ConfigPath with TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"
    exit 0
}
Get-Content $ConfigPath | ForEach-Object {
    if ($_ -match '^([^#=]+)=(.+)$') {
        [System.Environment]::SetEnvironmentVariable($Matches[1].Trim(), $Matches[2].Trim(), 'Process')
    }
}

$token = $env:TELEGRAM_BOT_TOKEN
$chatId = $env:TELEGRAM_CHAT_ID
if (-not $token -or -not $chatId) {
    Write-Output "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID"
    exit 1
}

$stateFile = 'C:\logs\tradingbot\telegram-alert-state.json'

function Send-Telegram($text) {
    try {
        $body = @{ chat_id = $chatId; text = $text; parse_mode = 'HTML' } | ConvertTo-Json -Compress
        $resp = Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/sendMessage" `
            -Method Post -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 15
        return $resp.ok
    } catch {
        Write-Output "Telegram send failed: $($_.Exception.Message)"
        return $false
    }
}

function Get-AlertState {
    if (Test-Path $stateFile) {
        try { return Get-Content $stateFile -Raw | ConvertFrom-Json } catch {}
    }
    return [PSCustomObject]@{ lastDealTime = 0; lastFailsafe = $false; lastConnected = $true; lastDeskOk = $true; lastDailyReport = '' }
}

function Save-AlertState($state) {
    $state | ConvertTo-Json | Set-Content $stateFile -Encoding utf8
}

$state = Get-AlertState
$wc = New-Object System.Net.WebClient
$now = Get-Date

# --- CHECK 1: MT5 Connection ---
$mt5Ok = $false
$balance = 0; $equity = 0
try {
    $mt5 = $wc.DownloadString('http://127.0.0.1:8765/api/status') | ConvertFrom-Json
    $mt5Ok = [bool]$mt5.connected
    $balance = $mt5.account.balance
    $equity = $mt5.account.equity
} catch { $mt5Ok = $false }

if (-not $mt5Ok -and $state.lastConnected) {
    $msg = [char]0x1F534 + ' MT5 DISCONNECTED' + "`nThe MT5 API is not responding.`nTime: $($now.ToString('HH:mm:ss'))"
    Send-Telegram $msg | Out-Null
} elseif ($mt5Ok -and -not $state.lastConnected) {
    $msg = [char]0x2705 + " MT5 RECONNECTED`nBalance: `$$balance | Equity: `$$equity`nTime: $($now.ToString('HH:mm:ss'))"
    Send-Telegram $msg | Out-Null
}
$state | Add-Member -NotePropertyName lastConnected -NotePropertyValue $mt5Ok -Force

# --- CHECK 2: Desk API Health ---
$deskOk = $false
try {
    $desk = Invoke-RestMethod http://127.0.0.1:8791/health -TimeoutSec 10
    $deskOk = [bool]$desk.ok
} catch { $deskOk = $false }

if (-not $deskOk -and $state.lastDeskOk) {
    $msg = [char]0x1F534 + " DESK API DOWN`nThe strategy API is not responding.`nTime: $($now.ToString('HH:mm:ss'))"
    Send-Telegram $msg | Out-Null
} elseif ($deskOk -and -not $state.lastDeskOk) {
    $msg = [char]0x2705 + " DESK API RECOVERED`nTime: $($now.ToString('HH:mm:ss'))"
    Send-Telegram $msg | Out-Null
}
$state | Add-Member -NotePropertyName lastDeskOk -NotePropertyValue $deskOk -Force

# --- CHECK 3: Bot Failsafe ---
$failsafe = $false
$failReason = ''
try {
    $safety = Get-Content 'C:\logs\tradingbot\safety-state.json' -Raw | ConvertFrom-Json
    $failsafe = [bool]$safety.failsafe
    $failReason = $safety.failsafeReason
} catch {}

if ($failsafe -and -not $state.lastFailsafe) {
    $msg = [char]0x1F6A8 + " BOT FAILSAFE ACTIVATED`nReason: $failReason`nTrading stopped. Review needed.`nTime: $($now.ToString('HH:mm:ss'))"
    Send-Telegram $msg | Out-Null
} elseif (-not $failsafe -and $state.lastFailsafe) {
    $msg = [char]0x2705 + " BOT FAILSAFE CLEARED`nTrading resumed.`nTime: $($now.ToString('HH:mm:ss'))"
    Send-Telegram $msg | Out-Null
}
$state | Add-Member -NotePropertyName lastFailsafe -NotePropertyValue $failsafe -Force

# --- CHECK 4: New Trades ---
try {
    $dealsJson = $wc.DownloadString('http://127.0.0.1:8765/api/logs?limit=20') | ConvertFrom-Json
    $lastTime = [int64]$state.lastDealTime
    foreach ($deal in $dealsJson.deals) {
        if ($deal.type -le 1 -and $deal.symbol -and [int64]$deal.time -gt $lastTime) {
            $side = if ($deal.type -eq 0) { [char]0x1F7E2 + ' BUY' } else { [char]0x1F534 + ' SELL' }
            $dt = [DateTimeOffset]::FromUnixTimeSeconds($deal.time).DateTime.ToString('yyyy-MM-dd HH:mm')
            $profitVal = [double]$deal.profit
            $profitStr = if ($profitVal -ge 0) { "+`$$profitVal" } else { "-`$$([Math]::Abs($profitVal))" }
            $msg = "$side $($deal.symbol)`nVol: $($deal.volume) @ $($deal.price)`nProfit: $profitStr`nTime: $dt"
            Send-Telegram $msg | Out-Null
            if ([int64]$deal.time -gt [int64]$state.lastDealTime) {
                $state | Add-Member -NotePropertyName lastDealTime -NotePropertyValue ([int64]$deal.time) -Force
            }
        }
    }
} catch {}

# --- CHECK 5: Daily P&L Report (once per day after 8 PM) ---
$todayKey = $now.ToString('yyyy-MM-dd')
if ($state.lastDailyReport -ne $todayKey -and $now.Hour -ge 20 -and $mt5Ok) {
    try {
        $allDeals = ($wc.DownloadString('http://127.0.0.1:8765/api/logs?limit=200') | ConvertFrom-Json).deals
        $todayDeals = $allDeals | Where-Object {
            $_.type -le 1 -and $_.symbol -and
            ([DateTimeOffset]::FromUnixTimeSeconds($_.time).DateTime.ToString('yyyy-MM-dd') -eq $todayKey)
        }
        $todayPnl = ($todayDeals | Measure-Object -Property profit -Sum).Sum
        if (-not $todayPnl) { $todayPnl = 0 }
        $tradeCount = ($todayDeals | Measure-Object).Count
        $wins = ($todayDeals | Where-Object { [double]$_.profit -gt 0 } | Measure-Object).Count
        $pnlStr = if ($todayPnl -ge 0) { "+`$$([math]::Round($todayPnl,2))" } else { "-`$$([math]::Round([Math]::Abs($todayPnl),2))" }
        $emoji = if ($todayPnl -ge 0) { [char]0x1F4C8 } else { [char]0x1F4C9 }
        $botStatus = if ($failsafe) { 'FAILSAFE' } else { 'Active' }

        $msg = "$emoji DAILY REPORT $todayKey`n`nTrades: $tradeCount (Wins: $wins)`nPnL: $pnlStr`nBalance: `$$balance`nEquity: `$$equity`n`nBot: $botStatus | MT5: $(if ($mt5Ok) {'Connected'} else {'Down'})"
        Send-Telegram $msg | Out-Null
        $state | Add-Member -NotePropertyName lastDailyReport -NotePropertyValue $todayKey -Force
    } catch {}
}

# --- CHECK 6: MT5 Terminal process ---
$mt5Proc = Get-Process terminal64 -ErrorAction SilentlyContinue
if (-not $mt5Proc) {
    $msg = [char]0x1F534 + " MT5 TERMINAL PROCESS DEAD`nterminal64.exe not running.`nWatchdog should restart it.`nTime: $($now.ToString('HH:mm:ss'))"
    Send-Telegram $msg | Out-Null
}

Save-AlertState $state
Write-Output "$($now.ToString('HH:mm:ss')) Alert check: mt5=$mt5Ok desk=$deskOk failsafe=$failsafe"

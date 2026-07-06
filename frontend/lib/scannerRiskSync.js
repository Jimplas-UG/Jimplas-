/**
 * Keep Python tick scanner aligned with Risk desk — partition sizing + exec gates.
 */
import { postScannerExecEnable, postScannerRiskConfig } from '../broker/binanceScannerApi';

/**
 * Scanner auto-exec when Binance API is linked.
 * ON by default on connect so qualified signals are not missed.
 * Only hard safety stops block (emergency, pause, loss/drawdown limits).
 */
export function scannerExecAllowed(config, metrics, _positions, connected) {
  if (!connected) return false;
  if (config.emergencyStop) return false;
  if (config.pauseNewTrades) return false;
  if (config.autoStopApiErrors && config.apiErrorStreak >= 3) return false;
  if (config.autoStopDailyLoss && metrics.dailyLossPct >= config.maxDailyLossPct) return false;
  if (config.autoStopDrawdown && metrics.drawdownPct >= config.maxDrawdownPct) return false;
  if (metrics.weeklyLossPct >= config.maxWeeklyLossPct) return false;
  return true;
}

/** Immediate exec ON after login — backend already enables on /api/login; one fire-and-forget confirm. */
export async function enableScannerAutoExecOnConnect(baseUrl, { retries = 1, delayMs = 150 } = {}) {
  const b = String(baseUrl || '').replace(/\/$/, '');
  if (!b) return { ok: false, error: 'no_base_url' };
  let last = { ok: false, error: 'no_attempt' };
  for (let i = 0; i <= retries; i += 1) {
    last = await postScannerExecEnable(b, true);
    if (last.ok && last.exec_enabled !== false) return last;
    if (i < retries) await new Promise((r) => setTimeout(r, delayMs * (i + 1)));
  }
  return last;
}

/**
 * Push partition legs + exec on/off to the bridge (retries for reconnect / restart).
 */
export async function syncScannerBridgeState(
  baseUrl,
  { config, metrics, positions, connected },
  { retries = 3, delayMs = 800 } = {},
) {
  const b = String(baseUrl || '').replace(/\/$/, '');
  if (!b) return { ok: false, error: 'no_base_url', execOn: false };

  const execOn = scannerExecAllowed(config, metrics, positions, connected);
  const riskPayload = {
    partitionUsd: config.partitionUsd,
    shortPartitionPct: config.shortPartitionPct,
    long1PartitionPct: config.long1PartitionPct,
    long2PartitionPct: config.long2PartitionPct,
  };

  let lastRisk = { ok: false, error: 'no_attempt' };
  let lastExec = { ok: true, skipped: true };

  for (let i = 0; i <= retries; i += 1) {
    lastRisk = await postScannerRiskConfig(b, riskPayload);
    // Only push exec on/off while Binance is linked — never disable on app boot before connect.
    if (connected) {
      lastExec = await postScannerExecEnable(b, execOn);
    }
    const execOk = !connected || lastExec.ok;
    if (lastRisk.ok && execOk) {
      return { ok: true, execOn: connected ? execOn : null, risk: lastRisk, exec: lastExec };
    }
    if (i < retries) {
      await new Promise((r) => setTimeout(r, delayMs * (i + 1)));
    }
  }

  return { ok: false, execOn: connected ? execOn : null, risk: lastRisk, exec: lastExec };
}

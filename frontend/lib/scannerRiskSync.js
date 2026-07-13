/**
 * Keep Python tick scanner aligned with Risk desk — partition sizing + emergency halt.
 */
import { postScannerExecControl, postScannerRiskConfig } from '../broker/binanceScannerApi';

/**
 * Push partition legs and execution halt state to the bridge (retries for reconnect / restart).
 */
export async function syncScannerBridgeState(
  baseUrl,
  { config },
  { retries = 3, delayMs = 800 } = {},
) {
  const b = String(baseUrl || '').replace(/\/$/, '');
  if (!b) return { ok: false, error: 'no_base_url' };

  const riskPayload = {
    partitionUsd: config.partitionUsd,
    shortPartitionPct: config.shortPartitionPct,
    long1PartitionPct: config.long1PartitionPct,
    long2PartitionPct: config.long2PartitionPct,
  };
  const execEnabled = !config.emergencyStop;

  let lastRisk = { ok: false, error: 'no_attempt' };
  let lastExec = { ok: false, error: 'no_attempt' };

  for (let i = 0; i <= retries; i += 1) {
    [lastRisk, lastExec] = await Promise.all([
      postScannerRiskConfig(b, riskPayload),
      postScannerExecControl(b, execEnabled),
    ]);
    if (lastRisk.ok && lastExec.ok) {
      return { ok: true, risk: lastRisk, exec: lastExec };
    }
    if (i < retries) {
      await new Promise((r) => setTimeout(r, delayMs * (i + 1)));
    }
  }

  return { ok: false, risk: lastRisk, exec: lastExec };
}

/**
 * Halt or resume scanner entries immediately (emergency stop button).
 */
export async function syncScannerExecHalt(baseUrl, enabled, { retries = 2, delayMs = 500 } = {}) {
  const b = String(baseUrl || '').replace(/\/$/, '');
  if (!b) return { ok: false, error: 'no_base_url' };

  let last = { ok: false, error: 'no_attempt' };
  for (let i = 0; i <= retries; i += 1) {
    last = await postScannerExecControl(b, enabled);
    if (last.ok) return last;
    if (i < retries) {
      await new Promise((r) => setTimeout(r, delayMs * (i + 1)));
    }
  }
  return last;
}

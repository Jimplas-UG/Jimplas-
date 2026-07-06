/**
 * Keep Python tick scanner aligned with Risk desk — partition sizing only.
 * Execution is always armed when Binance is linked (server-side); halt via SCANNER_EXEC / FORWARD_DRY_RUN env.
 */
import { postScannerRiskConfig } from '../broker/binanceScannerApi';

/**
 * Push partition legs to the bridge (retries for reconnect / restart).
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

  let lastRisk = { ok: false, error: 'no_attempt' };

  for (let i = 0; i <= retries; i += 1) {
    lastRisk = await postScannerRiskConfig(b, riskPayload);
    if (lastRisk.ok) {
      return { ok: true, risk: lastRisk };
    }
    if (i < retries) {
      await new Promise((r) => setTimeout(r, delayMs * (i + 1)));
    }
  }

  return { ok: false, risk: lastRisk };
}

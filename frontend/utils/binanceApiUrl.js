import { getBinanceApiUrl, getDeskApiUrl } from '../lib/envConfig';
import { getMetroLanHost, isLocalhostApiUrl } from './bridgeLanUrl';

/** Best Binance bridge URL for this device (LAN :8766, desk proxy, or env). */
export function getDefaultBinanceBridgeUrl(port = 8766) {
  const baked = getBinanceApiUrl();
  if (baked && !isLocalhostApiUrl(baked)) return baked.replace(/\/$/, '');

  const env = process.env.EXPO_PUBLIC_BINANCE_API_URL?.trim();
  if (env) return env.replace(/\/$/, '');

  const lan = getMetroLanHost();
  if (lan) return `http://${lan}:${port}`;

  return `http://127.0.0.1:${port}`;
}

/** Candidate URLs to try when connecting (direct bridge, then desk proxy). */
export function binanceBridgeUrlCandidates(preferred = '') {
  const out = [];
  const push = (u) => {
    const v = String(u || '').trim().replace(/\/$/, '');
    if (v && !out.includes(v)) out.push(v);
  };

  push(preferred);

  const lan = getMetroLanHost();
  if (lan) {
    push(`http://${lan}:8766`);
    push(`http://${lan}:8791/v1/binance`);
  }

  const desk = getDeskApiUrl();
  if (desk && !isLocalhostApiUrl(desk)) {
    push(`${desk.replace(/\/$/, '')}/v1/binance`);
  }

  push(getDefaultBinanceBridgeUrl());
  push('http://127.0.0.1:8766');

  return out;
}

export function formatBinanceNetworkError(message, baseUrl) {
  const msg = message ? String(message) : 'Network request failed';
  const lan = getMetroLanHost();
  const suggest = lan ? `http://${lan}:8766` : 'http://YOUR_PC_IP:8766';
  const hint =
    `On your PC run:\n` +
    `  cd binance_trading_system\\python\n` +
    `  $env:BINANCE_PAPER="0"\n` +
    `  .\\start-api.ps1\n\n` +
    `Phone URL (same Wi‑Fi): ${suggest}\n` +
    `Not 127.0.0.1 — that points to the phone itself.`;

  if (/fetch|network|failed|ECONNREFUSED|abort|timed out/i.test(msg)) {
    return `${msg}\n\n${hint}`;
  }
  if (isLocalhostApiUrl(baseUrl)) {
    return `${msg}\n\n${hint}`;
  }
  return msg;
}

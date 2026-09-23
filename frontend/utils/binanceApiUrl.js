import { getBinanceApiUrl, getDeskApiUrl, isVpsDeployed } from '../lib/envConfig';
import { getMetroLanHost, isLocalhostApiUrl, rewriteLocalhostBridgeUrl } from './bridgeLanUrl';

/** Known-dead / placeholder hosts that must never stick in AsyncStorage. */
const OBSOLETE_HOST_RE =
  /(127\.0\.0\.1|localhost|YOUR-RAILWAY|railway\.app|157\.245\.33\.42|161\.35\.112\.53)/i;

export function isObsoleteBridgeUrl(url) {
  const u = String(url || '').trim();
  if (!u) return true;
  if (isLocalhostApiUrl(u)) return true;
  return OBSOLETE_HOST_RE.test(u);
}

/** Best Binance bridge URL for this device (baked VPS → desk proxy → LAN). */
export function getDefaultBinanceBridgeUrl(port = 8766) {
  const env = process.env.EXPO_PUBLIC_BINANCE_API_URL?.trim();
  if (env && !isObsoleteBridgeUrl(env)) return env.replace(/\/$/, '');

  const baked = getBinanceApiUrl();
  if (baked && !isObsoleteBridgeUrl(baked)) return baked.replace(/\/$/, '');

  const desk = getDeskApiUrl();
  if (desk && !isObsoleteBridgeUrl(desk)) {
    return `${desk.replace(/\/$/, '')}/v1/binance`;
  }

  const lan = getMetroLanHost();
  if (lan) return `http://${lan}:${port}`;

  return `http://127.0.0.1:${port}`;
}

/** Best URL for this device — never use loopback on Expo Go when LAN host is known. */
export function resolveBridgeUrlForDevice(preferred = '') {
  const raw = String(preferred || '').trim();
  if (raw && !isObsoleteBridgeUrl(raw)) {
    return rewriteLocalhostBridgeUrl(raw);
  }
  return rewriteLocalhostBridgeUrl(getDefaultBinanceBridgeUrl());
}

/** Candidate URLs to try when connecting — baked VPS first; localhost last (dev only). */
export function binanceBridgeUrlCandidates(preferred = '') {
  const out = [];
  const push = (u) => {
    const v = String(u || '').trim().replace(/\/$/, '');
    if (v && !out.includes(v) && !isObsoleteBridgeUrl(v)) out.push(v);
  };

  push(preferred);
  push(getDefaultBinanceBridgeUrl());

  const desk = getDeskApiUrl();
  if (desk && !isObsoleteBridgeUrl(desk)) {
    push(`${desk.replace(/\/$/, '')}/v1/binance`);
    // Direct bridge sibling of desk host
    try {
      const host = desk.replace(/^https?:\/\//i, '').split('/')[0].split(':')[0];
      if (host) push(`http://${host}:8766`);
    } catch {
      /* ignore */
    }
  }

  if (!isVpsDeployed()) {
    const lan = getMetroLanHost();
    if (lan) {
      push(`http://${lan}:8766`);
      push(`http://${lan}:8791/v1/binance`);
    }
  }

  return out;
}

export function formatBinanceNetworkError(message, baseUrl) {
  const msg = message ? String(message) : 'Network request failed';
  const vps = getDefaultBinanceBridgeUrl();
  const remote = vps && !isObsoleteBridgeUrl(vps);
  const hint = remote
    ? `Server bridge:\n  ${vps}\n\n` +
      `1) Settings → Advanced → set Bridge URL to that address\n` +
      `2) Switch to MAINNET (not Testnet)\n` +
      `3) Paste live Futures API key + secret → Connect\n` +
      `Or install the latest APK from the desk /download link.`
    : (() => {
        const lan = getMetroLanHost();
        const suggest = lan ? `http://${lan}:8766` : 'http://YOUR_PC_IP:8766';
        return (
          `On your PC run:\n` +
          `  cd binance_trading_system\\python\n` +
          `  $env:BINANCE_PAPER="0"\n` +
          `  .\\start-api.ps1\n\n` +
          `Phone URL (same Wi‑Fi): ${suggest}\n` +
          `Not 127.0.0.1 — that points to the phone itself.`
        );
      })();

  if (/fetch|network|failed|ECONNREFUSED|abort|timed out/i.test(msg)) {
    return `${msg}\n\n${hint}`;
  }
  if (isLocalhostApiUrl(baseUrl) || isObsoleteBridgeUrl(baseUrl)) {
    return `${msg}\n\n${hint}`;
  }
  return msg;
}

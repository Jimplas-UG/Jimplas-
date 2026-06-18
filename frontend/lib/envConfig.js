/**
 * Production env — process.env (EAS) + app.config extra (runtime fallback).
 */
import Constants from 'expo-constants';

function extra(key) {
  const c = Constants.expoConfig?.extra ?? Constants.manifest2?.extra ?? Constants.manifest?.extra;
  return c?.[key];
}

function stripTrailingSlash(url) {
  return String(url || '').replace(/\/$/, '');
}

function isLocalhostUrl(url) {
  return /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?(\/|$)/i.test(String(url || '').trim());
}

export function getDeskApiUrl() {
  const fromEnv = process.env.EXPO_PUBLIC_DESK_API_URL?.trim();
  if (fromEnv) return stripTrailingSlash(fromEnv);
  const fromExtra = extra('deskApiUrl');
  if (fromExtra) return stripTrailingSlash(fromExtra);
  return 'http://127.0.0.1:8791';
}

/**
 * Binance Futures bridge URL — production uses desk-api proxy on :8791/v1/binance
 */
export function getBinanceApiUrl() {
  const fromEnv = process.env.EXPO_PUBLIC_BINANCE_API_URL?.trim();
  if (fromEnv) return stripTrailingSlash(fromEnv);

  const fromExtra = extra('binanceApiUrl');
  if (fromExtra) return stripTrailingSlash(fromExtra);

  const desk = getDeskApiUrl();
  if (desk && !isLocalhostUrl(desk)) {
    return `${stripTrailingSlash(desk)}/v1/binance`;
  }

  return 'http://127.0.0.1:8766';
}

export function getDeskApiKey() {
  return process.env.EXPO_PUBLIC_DESK_API_KEY?.trim() || extra('deskApiKey') || '';
}

/** Optional direct-bridge token when BRIDGE_TOKEN is set on Python API (LAN dev). */
export function getBridgeToken() {
  return process.env.EXPO_PUBLIC_BRIDGE_TOKEN?.trim() || extra('bridgeToken') || '';
}

export function isDeskRemote() {
  if (process.env.EXPO_PUBLIC_DESK_LOCAL === '1') return false;
  if (process.env.EXPO_PUBLIC_DESK_REMOTE === '1') return true;
  return extra('deskRemote') !== '0';
}

export function isVpsDeployed() {
  const binance = getBinanceApiUrl();
  const desk = getDeskApiUrl();
  return !isLocalhostUrl(binance) || !isLocalhostUrl(desk);
}

export function envDiagnostics() {
  return {
    deskApiUrl: getDeskApiUrl(),
    binanceApiUrl: getBinanceApiUrl(),
    hasDeskKey: !!getDeskApiKey(),
    deskRemote: isDeskRemote(),
    vpsDeployed: isVpsDeployed(),
    dev: typeof __DEV__ !== 'undefined' ? __DEV__ : false,
  };
}

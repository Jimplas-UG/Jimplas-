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
 * MT5 bridge URL — production uses desk-api proxy on :8791/v1/mt5
 * (avoids carrier blocks on direct :8765).
 */
export function getMt5ApiUrl() {
  const fromEnv = process.env.EXPO_PUBLIC_MT5_API_URL?.trim();
  if (fromEnv) return stripTrailingSlash(fromEnv);

  const fromExtra = extra('mt5ApiUrl');
  if (fromExtra) return stripTrailingSlash(fromExtra);

  const desk = getDeskApiUrl();
  if (desk && !isLocalhostUrl(desk)) {
    return `${stripTrailingSlash(desk)}/v1/mt5`;
  }

  return 'http://127.0.0.1:8765';
}

export function getDeskApiKey() {
  return process.env.EXPO_PUBLIC_DESK_API_KEY?.trim() || extra('deskApiKey') || '';
}

export function isDeskRemote() {
  if (process.env.EXPO_PUBLIC_DESK_LOCAL === '1') return false;
  if (process.env.EXPO_PUBLIC_DESK_REMOTE === '1') return true;
  return extra('deskRemote') !== '0';
}

export function isVpsDeployed() {
  const mt5 = getMt5ApiUrl();
  const desk = getDeskApiUrl();
  return !isLocalhostUrl(mt5) || !isLocalhostUrl(desk);
}

export function envDiagnostics() {
  return {
    deskApiUrl: getDeskApiUrl(),
    mt5ApiUrl: getMt5ApiUrl(),
    hasDeskKey: !!getDeskApiKey(),
    deskRemote: isDeskRemote(),
    vpsDeployed: isVpsDeployed(),
    dev: typeof __DEV__ !== 'undefined' ? __DEV__ : false,
  };
}

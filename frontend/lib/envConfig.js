/**
 * Production env — process.env (EAS) + app.config extra (runtime fallback).
 */
import Constants from 'expo-constants';

function extra(key) {
  const c = Constants.expoConfig?.extra ?? Constants.manifest2?.extra ?? Constants.manifest?.extra;
  return c?.[key];
}

export function getDeskApiUrl() {
  const fromEnv = process.env.EXPO_PUBLIC_DESK_API_URL?.trim();
  if (fromEnv) return fromEnv.replace(/\/$/, '');
  const fromExtra = extra('deskApiUrl');
  if (fromExtra) return String(fromExtra).replace(/\/$/, '');
  return 'http://127.0.0.1:8791';
}

export function getDeskApiKey() {
  return process.env.EXPO_PUBLIC_DESK_API_KEY?.trim() || extra('deskApiKey') || '';
}

export function isDeskRemote() {
  if (process.env.EXPO_PUBLIC_DESK_LOCAL === '1') return false;
  if (process.env.EXPO_PUBLIC_DESK_REMOTE === '1') return true;
  return extra('deskRemote') !== '0';
}

export function envDiagnostics() {
  return {
    deskApiUrl: getDeskApiUrl(),
    hasDeskKey: !!getDeskApiKey(),
    deskRemote: isDeskRemote(),
    dev: typeof __DEV__ !== 'undefined' ? __DEV__ : false,
  };
}

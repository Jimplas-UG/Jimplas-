/**
 * Secure Binance credential storage — expo-secure-store with AsyncStorage migration.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';
import {
  binanceFetch,
  fetchBinanceSession,
  pickReachableBinanceBridgeUrl,
  postBinanceAttach,
  postBinanceLogin,
  rememberBridgeUrl,
  probeBridgeHealth,
} from '../broker/binanceFuturesApi';
import { getBrokerMode } from './brokerMode';

export const STORAGE_BINANCE_KEY = '@bilshenz_v1/binanceApiKey';
export const STORAGE_BINANCE_SECRET = '@bilshenz_v1/binanceApiSecret';
export const STORAGE_BINANCE_TESTNET = '@bilshenz_v1/binanceTestnet';
const MIGRATION_FLAG = '@bilshenz_v1/binanceSecureMigrated';

const CONNECT_TIMEOUT_MS = 45000;
const FAST_LOGIN_TIMEOUT_MS = 35000;

const SECURE_KEYS = {
  apiKey: 'bilshenz.binance.apiKey',
  apiSecret: 'bilshenz.binance.apiSecret',
};

function canUseSecureStore() {
  return Platform.OS !== 'web';
}

async function secureGet(key) {
  if (!canUseSecureStore()) return null;
  try {
    return await SecureStore.getItemAsync(key);
  } catch {
    return null;
  }
}

async function secureSet(key, value) {
  if (!canUseSecureStore()) return false;
  try {
    if (value) await SecureStore.setItemAsync(key, value);
    else await SecureStore.deleteItemAsync(key);
    return true;
  } catch {
    return false;
  }
}

async function migrateLegacyCredentials() {
  const done = await AsyncStorage.getItem(MIGRATION_FLAG);
  if (done === '1') return;
  const pairs = await AsyncStorage.multiGet([STORAGE_BINANCE_KEY, STORAGE_BINANCE_SECRET]);
  const m = Object.fromEntries(pairs);
  const key = m[STORAGE_BINANCE_KEY] || '';
  const secret = m[STORAGE_BINANCE_SECRET] || '';
  if (key || secret) {
    await secureSet(SECURE_KEYS.apiKey, key);
    await secureSet(SECURE_KEYS.apiSecret, secret);
  }
  await AsyncStorage.setItem(MIGRATION_FLAG, '1');
}

export async function loadStoredBinanceCredentials() {
  await migrateLegacyCredentials();
  const pairs = await AsyncStorage.multiGet([
    STORAGE_BINANCE_KEY,
    STORAGE_BINANCE_SECRET,
    STORAGE_BINANCE_TESTNET,
  ]);
  const m = Object.fromEntries(pairs);
  const secureKey = (await secureGet(SECURE_KEYS.apiKey)) || '';
  const secureSecret = (await secureGet(SECURE_KEYS.apiSecret)) || '';
  return {
    apiKey: secureKey || m[STORAGE_BINANCE_KEY] || '',
    apiSecret: secureSecret || m[STORAGE_BINANCE_SECRET] || '',
    testnet: m[STORAGE_BINANCE_TESTNET] !== '0',
  };
}

export async function saveStoredBinanceCredentials(apiKey, apiSecret, testnet) {
  await AsyncStorage.setItem(STORAGE_BINANCE_TESTNET, testnet ? '1' : '0');
  if (canUseSecureStore()) {
    await AsyncStorage.multiRemove([STORAGE_BINANCE_KEY, STORAGE_BINANCE_SECRET]);
    await secureSet(SECURE_KEYS.apiKey, apiKey);
    await secureSet(SECURE_KEYS.apiSecret, apiSecret);
  } else {
    await AsyncStorage.multiSet([
      [STORAGE_BINANCE_KEY, apiKey],
      [STORAGE_BINANCE_SECRET, apiSecret],
    ]);
  }
  await AsyncStorage.setItem(MIGRATION_FLAG, '1');
}

export async function saveStoredBinanceTestnetPref(testnet) {
  await AsyncStorage.setItem(STORAGE_BINANCE_TESTNET, testnet ? '1' : '0');
}

export async function clearStoredBinanceCredentials() {
  await secureSet(SECURE_KEYS.apiKey, '');
  await secureSet(SECURE_KEYS.apiSecret, '');
  await AsyncStorage.multiRemove([STORAGE_BINANCE_KEY, STORAGE_BINANCE_SECRET, STORAGE_BINANCE_TESTNET]);
}

export function hasBinanceCredentials(creds) {
  return !!(String(creds?.apiKey || '').trim() && String(creds?.apiSecret || '').trim());
}


export function isTransientBridgeError(error) {
  const msg = String(error || '');
  return /network|fetch|timeout|timed out|ECONNREFUSED|abort|failed to connect|bridge offline|503|502|504/i.test(msg);
}

export function isHardBinanceAuthFailure(error) {
  const msg = String(error || '');
  if (isTransientBridgeError(msg)) return false;
  return /invalid api-key|api-key format|signature|permission denied|ip.*restrict/i.test(msg);
}

/** Resolve bridge URL — on fast connect, use configured URL immediately (login proves reachability). */
async function resolveBridgeUrl(baseUrl, { fast = true } = {}) {
  const pref = String(baseUrl || '').trim().replace(/\/$/, '');
  if (fast && pref) {
    rememberBridgeUrl(pref);
    return pref;
  }
  const url = await pickReachableBinanceBridgeUrl(pref);
  if (url) rememberBridgeUrl(url);
  return url;
}

/** Login — backend auto-detects testnet/mainnet mismatch in a single request. */
async function loginOnce(url, apiKey, apiSecret, testnet, timeoutMs, autoDetectEnv) {
  return postBinanceLogin(
    url,
    { api_key: apiKey, api_secret: apiSecret, testnet, auto_detect_env: autoDetectEnv },
    timeoutMs,
  );
}

/**
 * Full connect flow — optimized for quant speed on credential re-entry.
 */
export async function connectBinanceBridge({
  baseUrl = '',
  apiKey = '',
  apiSecret = '',
  testnet = true,
  mode = getBrokerMode(),
  timeoutMs = CONNECT_TIMEOUT_MS,
  autoDetectEnv = true,
  clearSession = false,
  fast = true,
} = {}) {
  const url = await resolveBridgeUrl(baseUrl, { fast });
  if (!url) {
    return { ok: false, url: baseUrl, error: 'Cannot reach Binance bridge' };
  }

  // Login does time sync + account verify (+ optional env auto-detect). Never use sub‑10s.
  const loginTimeout = Math.max(timeoutMs || CONNECT_TIMEOUT_MS, FAST_LOGIN_TIMEOUT_MS);

  if (clearSession) {
    void binanceFetch(url, '/api/logout', { method: 'POST' }, 2000).catch(() => {});
  }

  let resolvedTestnet = testnet;
  let login;
  let autoDetected = false;

  if (mode === 'paper') {
    login = await postBinanceAttach(url, loginTimeout);
    if (!login.ok) {
      return { ok: false, url, error: login.detail || 'Paper attach failed' };
    }
  } else {
    const key = apiKey.trim();
    const secret = apiSecret.trim();
    if (!key || !secret) {
      return { ok: false, url, error: 'Enter API key and secret' };
    }

    let attempt = autoDetectEnv
      ? await loginOnce(url, key, secret, testnet, loginTimeout, true)
      : await loginOnce(url, key, secret, testnet, loginTimeout, false);

    // One retry on transient abort/timeout (common on mobile networks).
    if (!attempt.ok && isTransientBridgeError(attempt.detail)) {
      await new Promise((r) => setTimeout(r, 800));
      attempt = await loginOnce(url, key, secret, testnet, loginTimeout, autoDetectEnv);
    }

    login = attempt;
    resolvedTestnet = attempt.testnet ?? testnet;
    autoDetected = !!attempt.auto_detected;

    if (!login.ok) {
      const raw = login.detail || 'Login failed';
      const friendly = /abort/i.test(raw)
        ? 'Connection timed out reaching Binance via VPS — tap Retry. Check Testnet vs Mainnet matches your key.'
        : raw;
      return { ok: false, url, error: friendly, testnet: resolvedTestnet };
    }

    void saveStoredBinanceCredentials(key, secret, resolvedTestnet);
  }

  const account = login.account;
  const modeLabel = login.mode ?? (resolvedTestnet ? 'testnet' : 'live');

  if (!account) {
    const verified = await fetchBinanceSession(url, 2500, 0);
    if (!verified.account) {
      return {
        ok: false,
        url,
        error: verified.error || 'Could not verify account after login',
        testnet: resolvedTestnet,
      };
    }
    rememberBridgeUrl(url);
    return {
      ok: true,
      url,
      session: {
        ok: true,
        account: verified.account,
        mode: verified.mode ?? modeLabel,
        testnet: verified.testnet ?? resolvedTestnet,
        can_execute: verified.can_execute,
        exec_block: verified.exec_block ?? null,
      },
      testnet: verified.testnet ?? resolvedTestnet,
      autoDetected,
    };
  }

  rememberBridgeUrl(url);

  return {
    ok: true,
    url,
    session: {
      ok: true,
      account,
      mode: modeLabel,
      testnet: resolvedTestnet,
      can_execute: login.can_execute !== false,
      exec_enabled: login.exec_enabled !== false,
      exec_block: login.exec_block ?? null,
    },
    testnet: resolvedTestnet,
    autoDetected,
  };
}

export async function tryBinanceSessionConnect(baseUrl, timeoutMs = 10000) {
  const mode = getBrokerMode();
  const pref = String(baseUrl || '').trim().replace(/\/$/, '');
  // Prefer the bound URL immediately — do not wait on health before status.
  let url = pref;
  let session = pref ? await fetchBinanceSession(pref, Math.min(2000, timeoutMs), 0) : { ok: false };
  if (!session.ok) {
    const hit = pref ? await probeBridgeHealth(pref, 400) : null;
    url = hit || (await pickReachableBinanceBridgeUrl(pref));
    if (!url) {
      return { ok: false, url: baseUrl, error: 'Cannot reach Binance bridge' };
    }
    session = await fetchBinanceSession(url, 4000, 0);
  }

  if (session.ok) {
    rememberBridgeUrl(url);
    return { ok: true, url, session };
  }

  const creds = await loadStoredBinanceCredentials();
  if (mode !== 'paper' && (!creds.apiKey.trim() || !creds.apiSecret.trim())) {
    return { ok: false, url, error: 'No stored API credentials' };
  }

  return connectBinanceBridge({
    baseUrl: url,
    apiKey: creds.apiKey,
    apiSecret: creds.apiSecret,
    testnet: creds.testnet,
    mode,
    timeoutMs,
    autoDetectEnv: false,
    clearSession: false,
    fast: true,
  });
}

export async function restoreBinanceBridgeSession(baseUrl, timeoutMs = 10000) {
  const pref = String(baseUrl || '').trim().replace(/\/$/, '');
  // Status first on preferred URL — skip health gate when the session is already live.
  let url = pref;
  let session = pref ? await fetchBinanceSession(pref, 2000, 0) : { ok: false };
  if (!session.ok) {
    const hit = pref ? await probeBridgeHealth(pref, 400) : null;
    url = hit || (await pickReachableBinanceBridgeUrl(pref)) || pref;
    session = await fetchBinanceSession(url, 4000, 0);
  }
  if (session.ok) {
    rememberBridgeUrl(url);
    return { ok: true, url, session, hardFail: false };
  }
  if (isHardBinanceAuthFailure(session.error)) {
    return { ok: false, url, error: session.error, hardFail: true };
  }

  const mode = getBrokerMode();
  const creds = await loadStoredBinanceCredentials();
  if (mode !== 'paper' && !hasBinanceCredentials(creds)) {
    return { ok: false, url, error: 'No stored API credentials', hardFail: false };
  }

  const restored = await tryBinanceSessionConnect(url, timeoutMs);
  return {
    ...restored,
    hardFail: isHardBinanceAuthFailure(restored.error),
  };
}

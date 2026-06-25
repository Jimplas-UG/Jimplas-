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
} from '../broker/binanceFuturesApi';
import { getBrokerMode } from './brokerMode';
import { binanceBridgeUrlCandidates } from '../utils/binanceApiUrl';

export const STORAGE_BINANCE_KEY = '@bilshenz_v1/binanceApiKey';
export const STORAGE_BINANCE_SECRET = '@bilshenz_v1/binanceApiSecret';
export const STORAGE_BINANCE_TESTNET = '@bilshenz_v1/binanceTestnet';
const MIGRATION_FLAG = '@bilshenz_v1/binanceSecureMigrated';

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

/** Persist testnet/mainnet preference before connect (keeps auto-restore in sync with UI toggle). */
export async function saveStoredBinanceTestnetPref(testnet) {
  await AsyncStorage.setItem(STORAGE_BINANCE_TESTNET, testnet ? '1' : '0');
}

export async function clearStoredBinanceCredentials() {
  await secureSet(SECURE_KEYS.apiKey, '');
  await secureSet(SECURE_KEYS.apiSecret, '');
  await AsyncStorage.multiRemove([STORAGE_BINANCE_KEY, STORAGE_BINANCE_SECRET, STORAGE_BINANCE_TESTNET]);
}

function isKeyEnvMismatch(detail) {
  return /invalid api-key|api-key format|signature|permissions|unauthorized/i.test(String(detail || ''));
}

/**
 * Login with optional auto-detect: if keys fail on selected env, try the other (testnet ↔ mainnet).
 */
async function loginWithEnvFallback(url, apiKey, apiSecret, testnet, timeoutMs) {
  let login = await postBinanceLogin(
    url,
    { api_key: apiKey, api_secret: apiSecret, testnet },
    timeoutMs,
  );
  if (login.ok) return { login, testnet, autoDetected: false };

  if (isKeyEnvMismatch(login.detail)) {
    const alt = !testnet;
    const altLogin = await postBinanceLogin(
      url,
      { api_key: apiKey, api_secret: apiSecret, testnet: alt },
      timeoutMs,
    );
    if (altLogin.ok) {
      return { login: altLogin, testnet: alt, autoDetected: true };
    }
  }

  return { login, testnet, autoDetected: false };
}

/**
 * Full connect flow: reach bridge → clear stale session → login/attach → verify account.
 */
export async function connectBinanceBridge({
  baseUrl = '',
  apiKey = '',
  apiSecret = '',
  testnet = true,
  mode = getBrokerMode(),
  timeoutMs = 22000,
  autoDetectEnv = true,
} = {}) {
  const url = await pickReachableBinanceBridgeUrl(baseUrl);
  if (!url) {
    return { ok: false, url: baseUrl, error: 'Cannot reach Binance bridge' };
  }

  try {
    await binanceFetch(url, '/api/logout', { method: 'POST' }, 8000);
  } catch {
    /* clear stale session */
  }

  let resolvedTestnet = testnet;
  let login;
  let autoDetected = false;

  if (mode === 'paper') {
    login = await postBinanceAttach(url, timeoutMs);
    if (!login.ok) {
      return { ok: false, url, error: login.detail || 'Paper attach failed' };
    }
  } else {
    const key = apiKey.trim();
    const secret = apiSecret.trim();
    if (!key || !secret) {
      return { ok: false, url, error: 'Enter API key and secret' };
    }

    const attempt = autoDetectEnv
      ? await loginWithEnvFallback(url, key, secret, testnet, timeoutMs)
      : {
          login: await postBinanceLogin(url, { api_key: key, api_secret: secret, testnet }, timeoutMs),
          testnet,
          autoDetected: false,
        };
    login = attempt.login;
    resolvedTestnet = attempt.testnet;
    autoDetected = attempt.autoDetected;

    if (!login.ok) {
      return { ok: false, url, error: login.detail || 'Login failed', testnet: resolvedTestnet };
    }

    await saveStoredBinanceCredentials(key, secret, resolvedTestnet);
  }

  let account = login.account;
  let modeLabel = login.mode ?? (resolvedTestnet ? 'testnet' : 'live');

  const verified = await fetchBinanceSession(url, timeoutMs, 3);
  if (verified.account) {
    account = verified.account;
    modeLabel = verified.mode ?? modeLabel;
    resolvedTestnet = verified.testnet ?? resolvedTestnet;
  } else if (!account) {
    return {
      ok: false,
      url,
      error: verified.error || 'Could not verify account after login',
      testnet: resolvedTestnet,
    };
  }

  return {
    ok: true,
    url,
    session: { ok: true, account, mode: modeLabel, testnet: resolvedTestnet },
    testnet: resolvedTestnet,
    autoDetected,
  };
}

/**
 * Restore bridge session — uses stored keys for binance mode, attach for paper.
 */
export async function tryBinanceSessionConnect(baseUrl, timeoutMs = 18000) {
  const mode = getBrokerMode();

  const session = await fetchBinanceSession(baseUrl, timeoutMs, 1);
  if (session.ok) {
    const url = await pickReachableBinanceBridgeUrl(baseUrl);
    return { ok: true, url: url || baseUrl, session };
  }

  const creds = await loadStoredBinanceCredentials();
  if (mode !== 'paper' && (!creds.apiKey.trim() || !creds.apiSecret.trim())) {
    const url = await pickReachableBinanceBridgeUrl(baseUrl);
    return { ok: false, url: url || baseUrl, error: 'No stored API credentials' };
  }

  return connectBinanceBridge({
    baseUrl,
    apiKey: creds.apiKey,
    apiSecret: creds.apiSecret,
    testnet: creds.testnet,
    mode,
    timeoutMs,
    autoDetectEnv: true,
  });
}

/**
 * Secure Binance credential storage — expo-secure-store with AsyncStorage migration.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';
import {
  binanceFetch,
  fetchBinanceSession,
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
  await AsyncStorage.multiSet([
    [STORAGE_BINANCE_TESTNET, testnet ? '1' : '0'],
    [STORAGE_BINANCE_KEY, apiKey],
    [STORAGE_BINANCE_SECRET, apiSecret],
  ]);
  const ok = (await secureSet(SECURE_KEYS.apiKey, apiKey)) && (await secureSet(SECURE_KEYS.apiSecret, apiSecret));
  if (ok) {
    await AsyncStorage.setItem(MIGRATION_FLAG, '1');
  }
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

async function pickReachableBridgeUrl(candidates) {
  for (const url of candidates) {
    try {
      const res = await binanceFetch(url, '/health', {}, 6000);
      if (res.ok) return url;
    } catch {
      /* try next */
    }
  }
  return null;
}

/**
 * Restore bridge session — uses stored keys for binance mode, attach for paper.
 */
export async function tryBinanceSessionConnect(baseUrl, timeoutMs = 15000) {
  const mode = getBrokerMode();
  const candidates = binanceBridgeUrlCandidates(baseUrl);
  const url = await pickReachableBridgeUrl(candidates);
  if (!url) {
    return { ok: false, url: baseUrl, error: 'Cannot reach Binance bridge' };
  }

  let session = await fetchBinanceSession(url, timeoutMs);
  if (session.ok) return { ok: true, url, session };

  if (mode === 'paper') {
    const login = await postBinanceAttach(url, timeoutMs);
    if (!login.ok) return { ok: false, url, error: login.detail || 'Paper attach failed' };
    session = await fetchBinanceSession(url, timeoutMs);
    return { ok: session.ok, url, session, error: session.error };
  }

  const creds = await loadStoredBinanceCredentials();
  if (!creds.apiKey.trim() || !creds.apiSecret.trim()) {
    return { ok: false, url, error: 'No stored API credentials' };
  }

  const login = await postBinanceLogin(
    url,
    {
      api_key: creds.apiKey.trim(),
      api_secret: creds.apiSecret.trim(),
      testnet: creds.testnet,
    },
    timeoutMs,
  );
  if (!login.ok) return { ok: false, url, error: login.detail || 'Login failed' };

  session = await fetchBinanceSession(url, timeoutMs);
  return { ok: session.ok, url, session, error: session.error };
}

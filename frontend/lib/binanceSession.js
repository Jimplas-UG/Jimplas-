import AsyncStorage from '@react-native-async-storage/async-storage';
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

export async function loadStoredBinanceCredentials() {
  const pairs = await AsyncStorage.multiGet([
    STORAGE_BINANCE_KEY,
    STORAGE_BINANCE_SECRET,
    STORAGE_BINANCE_TESTNET,
  ]);
  const m = Object.fromEntries(pairs);
  return {
    apiKey: m[STORAGE_BINANCE_KEY] || '',
    apiSecret: m[STORAGE_BINANCE_SECRET] || '',
    testnet: m[STORAGE_BINANCE_TESTNET] !== '0',
  };
}

export async function saveStoredBinanceCredentials(apiKey, apiSecret, testnet) {
  await AsyncStorage.multiSet([
    [STORAGE_BINANCE_KEY, apiKey],
    [STORAGE_BINANCE_SECRET, apiSecret],
    [STORAGE_BINANCE_TESTNET, testnet ? '1' : '0'],
  ]);
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

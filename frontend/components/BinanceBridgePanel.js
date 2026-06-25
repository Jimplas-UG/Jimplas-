import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { useBinanceBridge } from '../contexts/BinanceBridgeContext';
import { useBilshenzTheme } from '../contexts/ThemeContext';
import StaticHexLogo from './logo/StaticHexLogo';
import ErrorState from './ui/ErrorState';
import { TRADING_SYMBOL } from '../lib/tradingSymbol';
import {
  binanceFetch,
  fetchBinancePositions,
  fetchBinanceSession,
} from '../broker/binanceFuturesApi';
import { getBrokerMode } from '../lib/brokerMode';
import {
  connectBinanceBridge,
  loadStoredBinanceCredentials,
  saveStoredBinanceTestnetPref,
  tryBinanceSessionConnect,
} from '../lib/binanceSession';
import {
  formatBinanceNetworkError,
  getDefaultBinanceBridgeUrl,
} from '../utils/binanceApiUrl';
import { getMetroLanHost, isLocalhostApiUrl } from '../utils/bridgeLanUrl';

function sessionLabel(account, mode) {
  if (!account) return 'Not connected';
  const srv = account.server ?? mode ?? 'binance';
  const bal = account.balance != null ? `$${Math.round(account.balance).toLocaleString()}` : '—';
  return `${srv} · ${bal} ${account.currency ?? 'USDT'}`;
}

function accountIsTestnet(account) {
  const srv = String(account?.server ?? '').toLowerCase();
  return srv.includes('testnet') || srv.includes('test');
}

function formatLoginEnvError(detail, testnet) {
  const msg = String(detail || 'Login failed');
  if (/invalid api-key|api-key format|signature|permissions/i.test(msg)) {
    return testnet
      ? `${msg}\n\nUse separate Futures keys from testnet.binancefuture.com — mainnet keys only work on Mainnet.`
      : `${msg}\n\nUse mainnet Futures keys from binance.com — testnet keys only work on Testnet.`;
  }
  return msg;
}

export default function BinanceBridgePanel() {
  const { colors: C } = useBilshenzTheme();
  const mode = getBrokerMode();
  const metroLan = getMetroLanHost();
  const { baseUrl, setBaseUrl, connected, setConnected, hydrated } = useBinanceBridge();

  const [apiKey, setApiKey] = useState('');
  const [apiSecret, setApiSecret] = useState('');
  const [showSecret, setShowSecret] = useState(false);
  const [testnet, setTestnet] = useState(true);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [account, setAccount] = useState(null);
  const [bridgeMode, setBridgeMode] = useState(null);
  const [tick, setTick] = useState(null);
  const [positions, setPositions] = useState([]);
  const [feedLive, setFeedLive] = useState(false);
  const graceUntilRef = useRef(0);
  const pollRef = useRef(null);

  const sessionLive = connected && !!account;
  const sessionTestnet = account ? accountIsTestnet(account) : null;
  const envMismatch = sessionLive && sessionTestnet != null && sessionTestnet !== testnet;

  const clearBridgeSession = useCallback(async () => {
    try {
      if (baseUrl) await binanceFetch(baseUrl, '/api/logout', { method: 'POST' }, 8000);
    } catch {
      /* ignore */
    }
    graceUntilRef.current = 0;
    setConnected(false);
    setAccount(null);
    setBridgeMode(null);
    setPositions([]);
  }, [baseUrl, setConnected]);

  const stopPoll = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const applySession = useCallback(
    (session, url) => {
      if (url) setBaseUrl(url);
      const acct = session?.account;
      if (acct && typeof acct === 'object') {
        graceUntilRef.current = Date.now() + 45000;
        setConnected(true);
        setAccount(acct);
        setBridgeMode(session.mode ?? null);
        setErr('');
        return true;
      }
      return false;
    },
    [setBaseUrl, setConnected],
  );

  const refresh = useCallback(async () => {
    const b = baseUrl?.trim();
    if (!b) return;
    try {
      const session = await fetchBinanceSession(b, 15000);
      if (session.ok) {
        applySession(session, b);
      } else if (Date.now() > graceUntilRef.current) {
        setConnected(false);
        setAccount(null);
        setBridgeMode(null);
        if (session.error) setErr(session.error);
      }
      if (!session.ok) return;

      const tkRes = await binanceFetch(b, `/api/tick/${TRADING_SYMBOL}`, {}, 10000);
      if (tkRes.ok) setTick(await tkRes.json());

      const pos = await fetchBinancePositions(b, TRADING_SYMBOL);
      setPositions(pos);
    } catch (e) {
      if (Date.now() > graceUntilRef.current) {
        setErr(formatBinanceNetworkError(e instanceof Error ? e.message : String(e), b));
      }
    }
  }, [applySession, baseUrl, setConnected]);

  const onTestnetChange = useCallback(
    async (next) => {
      setTestnet(next);
      await saveStoredBinanceTestnetPref(next);
      if (sessionLive && sessionTestnet != null && sessionTestnet !== next) {
        await clearBridgeSession();
        const creds = await loadStoredBinanceCredentials();
        if (creds.apiKey.trim() && creds.apiSecret.trim() && mode !== 'paper') {
          setBusy(true);
          setErr(next ? 'Switching to Testnet…' : 'Switching to Mainnet…');
          try {
            const result = await connectBinanceBridge({
              baseUrl,
              apiKey: creds.apiKey,
              apiSecret: creds.apiSecret,
              testnet: next,
              mode,
              autoDetectEnv: false,
            });
            if (result.ok && result.session) {
              if (result.autoDetected) setTestnet(result.testnet);
              applySession(result.session, result.url);
              void refresh();
              return;
            }
            setErr(
              formatLoginEnvError(
                result.error,
                next,
              ) || (next ? 'Testnet login failed — use testnet.binancefuture.com keys' : 'Mainnet login failed — use binance.com keys'),
            );
          } catch (e) {
            setErr(formatBinanceNetworkError(e instanceof Error ? e.message : String(e), baseUrl));
          } finally {
            setBusy(false);
          }
          return;
        }
        setErr(
          next
            ? 'Switched to Testnet — paste testnet.binancefuture.com keys and tap Connect.'
            : 'Switched to Mainnet — paste binance.com Futures keys and tap Connect.',
        );
      }
    },
    [applySession, baseUrl, clearBridgeSession, mode, refresh, sessionLive, sessionTestnet],
  );

  useEffect(() => {
    let cancelled = false;
    loadStoredBinanceCredentials().then((creds) => {
      if (cancelled) return;
      if (creds.apiKey) setApiKey(creds.apiKey);
      if (creds.apiSecret) setApiSecret(creds.apiSecret);
      setTestnet(creds.testnet);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!hydrated || sessionLive || busy || mode === 'paper' || connected) return;
    let cancelled = false;
    (async () => {
      const creds = await loadStoredBinanceCredentials();
      if (!creds.apiKey.trim() || !creds.apiSecret.trim()) return;
      setBusy(true);
      try {
        const restored = await tryBinanceSessionConnect(baseUrl, 20000);
        if (cancelled) return;
        if (restored.ok && restored.session) {
          if (restored.testnet != null) setTestnet(restored.testnet);
          if (restored.autoDetected) {
            setErr(
              restored.testnet
                ? 'Connected to Testnet (auto-detected from your API keys).'
                : 'Connected to Mainnet (auto-detected from your API keys).',
            );
          }
          applySession(restored.session, restored.url);
        }
      } finally {
        if (!cancelled) setBusy(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [hydrated, sessionLive, busy, mode, baseUrl, connected, applySession]);

  useEffect(() => {
    if (isLocalhostApiUrl(baseUrl) && metroLan) {
      setBaseUrl(getDefaultBinanceBridgeUrl());
    }
  }, [baseUrl, metroLan, setBaseUrl]);

  useEffect(() => {
    if (connected && baseUrl && !account) {
      void refresh();
    }
  }, [connected, baseUrl, account, refresh]);

  useEffect(() => {
    if (sessionLive && baseUrl) {
      void refresh();
      stopPoll();
      pollRef.current = setInterval(() => refresh(), 8000);
      return stopPoll;
    }
    stopPoll();
    return undefined;
  }, [sessionLive, baseUrl, refresh]);

  useEffect(() => {
    const b = baseUrl?.trim();
    if (!b || sessionLive) {
      setFeedLive(false);
      return undefined;
    }
    let cancelled = false;
    const probe = async () => {
      try {
        const health = await binanceFetch(b, '/health', {}, 6000);
        if (!health.ok) {
          if (!cancelled) setFeedLive(false);
          return;
        }
        const tkRes = await binanceFetch(b, `/api/tick/${TRADING_SYMBOL}`, {}, 8000);
        if (!cancelled) {
          setFeedLive(tkRes.ok);
          if (tkRes.ok) setTick(await tkRes.json());
        }
      } catch {
        if (!cancelled) setFeedLive(false);
      }
    };
    void probe();
    const id = setInterval(probe, 12000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [baseUrl, sessionLive]);

  const onConnect = useCallback(async () => {
    setBusy(true);
    setErr('');
    try {
      const key = apiKey.trim();
      const secret = apiSecret.trim();

      if (mode !== 'paper' && (!key || !secret)) {
        setErr(
          testnet
            ? 'Enter both API key and secret from testnet.binancefuture.com'
            : 'Enter both API key and secret from binance.com (Futures API)',
        );
        return;
      }

      const result = await connectBinanceBridge({
        baseUrl,
        apiKey: key,
        apiSecret: secret,
        testnet,
        mode,
        autoDetectEnv: true,
      });

      if (!result.ok) {
        setConnected(false);
        setAccount(null);
        const msg = formatLoginEnvError(result.error, result.testnet ?? testnet);
        const netMsg = /bridge|network|fetch|ECONNREFUSED/i.test(msg)
          ? formatBinanceNetworkError(msg, baseUrl)
          : msg;
        setErr(netMsg);
        if (/bridge|network|fetch|ECONNREFUSED/i.test(msg)) {
          Alert.alert('Bridge offline', netMsg);
        } else {
          Alert.alert('Binance login failed', netMsg);
        }
        return;
      }

      if (result.testnet != null && result.testnet !== testnet) {
        setTestnet(result.testnet);
      }
      if (result.autoDetected) {
        setErr(
          result.testnet
            ? 'Connected to Testnet — keys matched testnet.binancefuture.com.'
            : 'Connected to Mainnet — keys matched binance.com.',
        );
      }

      applySession(result.session, result.url);
      setConnected(true);
      void refresh();
    } catch (e) {
      const msg = formatBinanceNetworkError(e instanceof Error ? e.message : String(e), baseUrl);
      setErr(msg);
      setConnected(false);
      setAccount(null);
    } finally {
      setBusy(false);
    }
  }, [apiKey, apiSecret, applySession, baseUrl, mode, refresh, setConnected, testnet]);

  const onDisconnect = useCallback(async () => {
    setBusy(true);
    try {
      if (baseUrl) await binanceFetch(baseUrl, '/api/logout', { method: 'POST' }, 8000);
    } catch {
      /* ignore */
    }
    stopPoll();
    graceUntilRef.current = 0;
    setConnected(false);
    setAccount(null);
    setBridgeMode(null);
    setTick(null);
    setPositions([]);
    setErr('');
    setBusy(false);
  }, [baseUrl, setConnected]);

  const onAutoUrl = () => {
    const url = getDefaultBinanceBridgeUrl();
    setBaseUrl(url);
    setErr('');
  };

  const statusColor = sessionLive ? C.green : feedLive ? C.amber : err ? C.red : C.dim;
  const statusText = sessionLive
    ? `Connected · ${sessionLabel(account, bridgeMode)}`
    : feedLive
      ? `Market data live · paste secret & tap Connect`
      : busy
        ? 'Connecting…'
        : err
          ? 'Connection failed'
          : 'Start bridge on your PC (port 8766)';

  const spreadPips =
    tick?.bid != null && tick?.ask != null ? ((tick.ask - tick.bid) / 0.1).toFixed(1) : null;

  const envLabel = sessionLive
    ? sessionTestnet
      ? 'TESTNET'
      : 'MAINNET'
    : bridgeMode === 'paper'
      ? 'PAPER'
      : testnet
        ? 'TESTNET'
        : 'MAINNET';

  return (
    <View style={st.root}>
      <View style={[st.banner, { borderColor: sessionLive ? 'rgba(0,230,118,0.4)' : 'rgba(255,61,87,0.35)' }]}>
        <StaticHexLogo size={44} variant="icon" />
        <View style={{ flex: 1, marginLeft: 12 }}>
          <Text style={[st.bannerTitle, { color: C.goldL }]}>Binance Futures · {envLabel}</Text>
          <Text style={[st.bannerStatus, { color: statusColor }]}>{statusText}</Text>
          {(sessionLive || feedLive) && tick ? (
            <Text style={[st.bannerSub, { color: C.dim }]}>
              {TRADING_SYMBOL} {(tick.bid + tick.ask) / 2} · spread {spreadPips}p
            </Text>
          ) : null}
        </View>
      </View>

      <View style={[st.checklist, { borderColor: C.border }]}>
        {[
          { ok: feedLive || sessionLive, label: 'Bridge & XAUUSDT quotes' },
          { ok: sessionLive, label: 'Futures API logged in' },
          { ok: sessionLive, label: 'Ready to send orders' },
        ].map((step) => (
          <View key={step.label} style={st.checkRow}>
            <Text style={{ color: step.ok ? C.green : C.dim, fontSize: 12, width: 18 }}>
              {step.ok ? '✓' : '○'}
            </Text>
            <Text style={{ color: step.ok ? C.text : C.dim2, fontSize: 11, fontWeight: '600' }}>{step.label}</Text>
          </View>
        ))}
      </View>

      <View style={[st.card, { borderColor: C.border }]}>
        {mode !== 'paper' ? (
          <>
            <Text style={[st.hint, { color: C.dim, marginTop: 0 }]}>
              Enable Futures + Read on your API key. Keys are not shared between Testnet and Mainnet.
            </Text>

            {envMismatch ? (
              <Text style={[st.hint, { color: C.amber, fontWeight: '700' }]}>
                Active session is {sessionTestnet ? 'Testnet' : 'Mainnet'} but you selected{' '}
                {testnet ? 'Testnet' : 'Mainnet'}. Disconnect or switch environment to match.
              </Text>
            ) : null}

            <Text style={[st.label, { color: C.dim }]}>Environment</Text>
            <View style={st.row}>
              {[
                { id: true, label: 'Testnet' },
                { id: false, label: 'Mainnet' },
              ].map((opt) => (
                <Pressable
                  key={String(opt.id)}
                  onPress={() => void onTestnetChange(opt.id)}
                  style={[st.chip, testnet === opt.id && { borderColor: C.gold, backgroundColor: 'rgba(212,180,90,0.15)' }]}>
                  <Text style={{ color: testnet === opt.id ? C.goldL : C.dim, fontSize: 11, fontWeight: '700' }}>
                    {opt.label}
                  </Text>
                </Pressable>
              ))}
            </View>

            <Text style={[st.label, { color: C.dim }]}>API Key</Text>
            <TextInput
              style={[st.input, { borderColor: C.border, color: C.text, backgroundColor: C.inputBg }]}
              value={apiKey}
              onChangeText={setApiKey}
              autoCapitalize="none"
              autoCorrect={false}
                placeholder={testnet ? 'Futures API key (testnet.binancefuture.com)' : 'Futures API key (binance.com)'}
              placeholderTextColor={C.dim2}
            />

            <Text style={[st.label, { color: C.dim }]}>API Secret</Text>
            <View style={st.secretRow}>
              <TextInput
                style={[st.input, st.secretInput, { borderColor: C.border, color: C.text, backgroundColor: C.inputBg }]}
                value={apiSecret}
                onChangeText={setApiSecret}
                secureTextEntry={!showSecret}
                autoCapitalize="none"
                autoCorrect={false}
                placeholder={testnet ? 'Secret from testnet.binancefuture.com' : 'Secret from binance.com Futures API'}
                placeholderTextColor={C.dim2}
                returnKeyType="done"
                onSubmitEditing={() => void onConnect()}
              />
              <Pressable onPress={() => setShowSecret((v) => !v)} style={[st.eye, { borderColor: C.border }]}>
                <Text>{showSecret ? '🙈' : '👁'}</Text>
              </Pressable>
            </View>

            {!sessionLive && apiKey.trim() && !apiSecret.trim() ? (
              <Text style={[st.hint, { color: C.amber, fontWeight: '700' }]}>
                Paste your API secret above, then tap Connect.
              </Text>
            ) : null}

            {err ? (
              <ErrorState title="Connection failed" message={err} compact onRetry={onConnect} retryLabel="Retry connect" />
            ) : null}

            {sessionLive ? (
              <Pressable onPress={onDisconnect} disabled={busy} style={[st.btn, st.btnOff]}>
                <Text style={st.btnOffTxt}>Disconnect</Text>
              </Pressable>
            ) : (
              <Pressable
                onPress={onConnect}
                disabled={busy || (mode !== 'paper' && (!apiKey.trim() || !apiSecret.trim()))}
                style={[
                  st.btn,
                  st.btnOn,
                  mode !== 'paper' && (!apiKey.trim() || !apiSecret.trim()) ? { opacity: 0.45 } : null,
                ]}>
                {busy ? <ActivityIndicator color="#F2E6C5" /> : (
                  <Text style={st.btnOnTxt}>
                    {mode === 'paper' ? 'Connect Paper' : 'Connect Binance'}
                  </Text>
                )}
              </Pressable>
            )}
          </>
        ) : (
          <Text style={[st.hint, { color: C.dim }]}>
            Paper mode — no keys needed. Start bridge with BINANCE_PAPER=1.
          </Text>
        )}

        {Platform.OS !== 'web' && isLocalhostApiUrl(baseUrl) ? (
          <Text style={[st.hint, { color: C.amber }]}>
            127.0.0.1 won&apos;t work on a phone. Tap &quot;Use PC on Wi‑Fi&quot; below.
          </Text>
        ) : null}

        {err && mode === 'paper' ? (
          <ErrorState title="Connection failed" message={err} compact onRetry={onConnect} retryLabel="Retry connect" />
        ) : null}

        {mode === 'paper' ? (
          sessionLive ? (
            <Pressable onPress={onDisconnect} disabled={busy} style={[st.btn, st.btnOff]}>
              <Text style={st.btnOffTxt}>Disconnect</Text>
            </Pressable>
          ) : (
            <Pressable onPress={onConnect} disabled={busy} style={[st.btn, st.btnOn]}>
              {busy ? <ActivityIndicator color="#F2E6C5" /> : <Text style={st.btnOnTxt}>Connect Paper</Text>}
            </Pressable>
          )
        ) : null}

        <Pressable onPress={onAutoUrl} style={[st.secondaryBtn, { borderColor: C.border }]}>
          <Text style={{ color: C.goldL, fontWeight: '700', fontSize: 11 }}>
            {metroLan ? `USE PC ON WI‑FI (${metroLan}:8766)` : 'USE DEFAULT BRIDGE URL'}
          </Text>
        </Pressable>

        <Pressable onPress={() => setShowAdvanced((v) => !v)} style={{ marginTop: 10 }}>
          <Text style={{ color: C.dim, fontSize: 10, fontWeight: '700' }}>
            {showAdvanced ? '▾ Hide advanced' : '▸ Advanced (manual URL)'}
          </Text>
        </Pressable>
        {showAdvanced ? (
          <>
            <Text style={[st.label, { color: C.dim }]}>Bridge URL</Text>
            <TextInput
              style={[st.input, { borderColor: C.border, color: C.text, backgroundColor: C.inputBg }]}
              value={baseUrl}
              onChangeText={setBaseUrl}
              autoCapitalize="none"
              autoCorrect={false}
              placeholder={getDefaultBinanceBridgeUrl()}
              placeholderTextColor={C.dim2}
            />
          </>
        ) : null}

        {sessionLive && account ? (
          <View style={st.metrics}>
            <View style={[st.metric, { borderColor: C.border }]}>
              <Text style={[st.metricLab, { color: C.dim }]}>Balance</Text>
              <Text style={[st.metricVal, { color: C.goldL }]}>
                ${Math.round(account.balance ?? 0).toLocaleString()}
              </Text>
            </View>
            <View style={[st.metric, { borderColor: C.border }]}>
              <Text style={[st.metricLab, { color: C.dim }]}>Equity</Text>
              <Text style={[st.metricVal, { color: C.green }]}>
                ${Math.round(account.equity ?? account.balance ?? 0).toLocaleString()}
              </Text>
            </View>
            <View style={[st.metric, { borderColor: C.border }]}>
              <Text style={[st.metricLab, { color: C.dim }]}>Floating</Text>
              <Text style={[st.metricVal, { color: (account.profit ?? 0) >= 0 ? C.green : C.red }]}>
                ${Math.round(account.profit ?? 0).toLocaleString()}
              </Text>
            </View>
          </View>
        ) : null}

        {sessionLive && positions.length ? (
          <View style={[st.posBox, { borderColor: C.border }]}>
            <Text style={[st.metricLab, { color: C.goldL, marginBottom: 8 }]}>OPEN POSITIONS</Text>
            {positions.map((p, i) => (
              <View key={`${p.symbol}-${p.type}-${i}`} style={st.posRow}>
                <Text style={{ color: C.text, fontSize: 11, fontWeight: '700' }}>
                  {p.type} · {p.volume} {p.symbol}
                </Text>
                <Text style={{ color: (p.profit ?? 0) >= 0 ? C.green : C.red, fontSize: 11, fontWeight: '700' }}>
                  ${Number(p.profit ?? 0).toFixed(2)}
                </Text>
              </View>
            ))}
          </View>
        ) : null}
      </View>
    </View>
  );
}

const st = StyleSheet.create({
  root: { marginTop: 4 },
  banner: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 14,
    borderRadius: 12,
    borderWidth: 1,
    backgroundColor: 'rgba(10,8,6,0.55)',
  },
  bannerTitle: { fontSize: 13, fontWeight: '800', letterSpacing: 0.6 },
  bannerStatus: { fontSize: 11, fontWeight: '700', marginTop: 4 },
  bannerSub: { fontSize: 10, marginTop: 4 },
  card: {
    marginTop: 12,
    padding: 14,
    borderRadius: 12,
    borderWidth: 1,
    backgroundColor: 'rgba(0,0,0,0.28)',
  },
  label: { fontSize: 10, fontWeight: '700', marginTop: 12, marginBottom: 6, letterSpacing: 0.4 },
  input: {
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 10,
    paddingHorizontal: 12,
    fontSize: 12,
  },
  secretRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  secretInput: { flex: 1 },
  eye: {
    width: 44,
    height: 44,
    borderRadius: 10,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  row: { flexDirection: 'row', gap: 8 },
  chip: {
    flex: 1,
    paddingVertical: 10,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.12)',
    alignItems: 'center',
  },
  secondaryBtn: {
    marginTop: 12,
    paddingVertical: 11,
    borderRadius: 10,
    borderWidth: 1,
    alignItems: 'center',
  },
  hint: { marginTop: 10, fontSize: 10, lineHeight: 15 },
  btn: {
    marginTop: 14,
    paddingVertical: 14,
    borderRadius: 12,
    alignItems: 'center',
    borderWidth: 1,
  },
  btnOn: { backgroundColor: 'rgba(212,180,90,0.38)', borderColor: 'rgba(242,226,176,0.35)' },
  btnOnTxt: { color: '#F2E6C5', fontWeight: '800', fontSize: 12, letterSpacing: 0.5 },
  btnOff: { backgroundColor: 'rgba(255,61,87,0.18)', borderColor: 'rgba(255,61,87,0.4)' },
  btnOffTxt: { color: '#ffc8d0', fontWeight: '800', fontSize: 12 },
  metrics: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 14 },
  metric: { flex: 1, minWidth: '30%', borderWidth: 1, borderRadius: 10, padding: 10 },
  metricLab: { fontSize: 9, fontWeight: '700' },
  metricVal: { fontSize: 15, fontWeight: '800', marginTop: 4 },
  posBox: { marginTop: 12, borderWidth: 1, borderRadius: 10, padding: 10 },
  posRow: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 6 },
  checklist: {
    marginTop: 10,
    padding: 12,
    borderRadius: 10,
    borderWidth: 1,
    backgroundColor: 'rgba(0,0,0,0.2)',
  },
  checkRow: { flexDirection: 'row', alignItems: 'center', marginTop: 4 },
});

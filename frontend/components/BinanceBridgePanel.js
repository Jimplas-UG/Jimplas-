import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { BlurView } from 'expo-blur';
import AsyncStorage from '@react-native-async-storage/async-storage';
import Svg, { Circle, Defs, LinearGradient, Path, Stop } from 'react-native-svg';
import { useBinanceBridge } from '../contexts/BinanceBridgeContext';
import { useBilshenzTheme } from '../contexts/ThemeContext';
import StaticHexLogo from './logo/StaticHexLogo';
import {
  binanceFetch,
  getDefaultBinanceApiUrl,
  postBinanceAttach,
  postBinanceLogin,
} from '../broker/binanceFuturesApi';
import { getBrokerMode } from '../lib/brokerMode';
import { isVpsDeployed, getDeskApiUrl } from '../lib/envConfig';
import { getMetroLanHost, isLocalhostApiUrl } from '../utils/mt5ApiUrl';

const STORAGE_BINANCE_KEY = '@bilshenz_v1/binanceApiKey';
const STORAGE_BINANCE_SECRET = '@bilshenz_v1/binanceApiSecret';
const STORAGE_BINANCE_TESTNET = '@bilshenz_v1/binanceTestnet';
const STORAGE_BINANCE_REMEMBER = '@bilshenz_v1/binanceRememberCreds';

const BNB_ACCENT = '#F0B90B';

function BinanceDiamondMark({ size = 22 }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24">
      <Defs>
        <LinearGradient id="bzGrad" x1="0%" y1="0%" x2="100%" y2="100%">
          <Stop offset="0%" stopColor="#FFF4C2" />
          <Stop offset="50%" stopColor={BNB_ACCENT} />
          <Stop offset="100%" stopColor="#C98A2E" />
        </LinearGradient>
      </Defs>
      <Path
        d="M12 2L4 8v8l8 6 8-6V8L12 2z"
        fill="none"
        stroke="url(#bzGrad)"
        strokeWidth={1.4}
        strokeLinejoin="round"
      />
      <Path d="M12 6l5 3.5v5L12 18l-5-3.5v-5L12 6z" fill="url(#bzGrad)" fillOpacity={0.35} />
    </Svg>
  );
}

function StatusDot({ on, color }) {
  return (
    <View style={[st.dotWrap, on && { shadowColor: color, shadowOpacity: 0.85, shadowRadius: 6 }]}>
      <View style={[st.dot, { backgroundColor: on ? color : 'rgba(255,255,255,0.2)' }]} />
    </View>
  );
}

function Segmented({ value, onChange, options, C }) {
  return (
    <View style={[st.segmented, { borderColor: C.border }]}>
      {options.map((opt) => {
        const active = value === opt.id;
        return (
          <Pressable
            key={opt.id}
            onPress={() => onChange(opt.id)}
            style={[
              st.segment,
              active && { backgroundColor: 'rgba(212,180,90,0.22)', borderColor: C.gold },
            ]}>
            <Text style={[st.segmentTxt, { color: active ? C.goldL : C.dim }]}>{opt.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

function MetricTile({ label, value, sub, accent, C }) {
  return (
    <View style={[st.metricTile, { borderColor: C.border, backgroundColor: 'rgba(0,0,0,0.32)' }]}>
      <Text style={[st.metricLab, { color: C.dim }]}>{label}</Text>
      <Text style={[st.metricVal, { color: accent ?? C.goldL }]}>{value}</Text>
      {sub ? <Text style={[st.metricSub, { color: C.dim2 }]}>{sub}</Text> : null}
    </View>
  );
}

const st = StyleSheet.create({
  root: { marginTop: 6 },
  hero: {
    alignItems: 'center',
    paddingVertical: 16,
    paddingHorizontal: 12,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: 'rgba(212,180,90,0.28)',
    backgroundColor: 'rgba(10,8,6,0.55)',
    overflow: 'hidden',
  },
  heroGlow: {
    position: 'absolute',
    top: -40,
    right: -30,
    width: 120,
    height: 120,
    borderRadius: 60,
    backgroundColor: 'rgba(240,185,11,0.08)',
  },
  logoRow: { flexDirection: 'row', alignItems: 'center', gap: 14 },
  brandTitle: { fontSize: 13, fontWeight: '800', letterSpacing: 1.4, color: '#F2E2B0' },
  brandSub: { fontSize: 10, fontWeight: '600', letterSpacing: 0.6, color: 'rgba(122,108,69,0.95)', marginTop: 3 },
  statusPill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginTop: 14,
    paddingVertical: 7,
    paddingHorizontal: 14,
    borderRadius: 20,
    borderWidth: 1,
  },
  statusTxt: { fontSize: 11, fontWeight: '800', letterSpacing: 0.8 },
  modeBadge: {
    marginTop: 10,
    paddingVertical: 4,
    paddingHorizontal: 10,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: 'rgba(240,185,11,0.35)',
    backgroundColor: 'rgba(240,185,11,0.1)',
  },
  modeBadgeTxt: { fontSize: 9, fontWeight: '800', color: BNB_ACCENT, letterSpacing: 1.1 },
  cardOuter: { marginTop: 14, borderRadius: 14, overflow: 'hidden', borderWidth: 1 },
  cardInner: { padding: 14 },
  sectionTitle: { fontSize: 10, fontWeight: '800', letterSpacing: 1.3, marginBottom: 8 },
  rowLab: { fontSize: 10, fontWeight: '700', marginTop: 10, letterSpacing: 0.4 },
  inp: {
    marginTop: 6,
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 11,
    paddingHorizontal: 12,
    fontSize: 12,
  },
  pwRow: { flexDirection: 'row', alignItems: 'center', marginTop: 6, gap: 8 },
  pwInp: { flex: 1, marginTop: 0 },
  eyeBtn: {
    width: 44,
    height: 44,
    borderRadius: 10,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  eyeTxt: { fontSize: 18 },
  lanBtn: {
    marginTop: 8,
    paddingVertical: 10,
    borderRadius: 10,
    borderWidth: 1,
    alignItems: 'center',
  },
  lanBtnTxt: { fontSize: 10, fontWeight: '800', letterSpacing: 0.7 },
  testBtn: {
    marginTop: 12,
    paddingVertical: 10,
    borderRadius: 10,
    borderWidth: 1,
    alignItems: 'center',
  },
  testBtnTxt: { fontSize: 10, fontWeight: '800', letterSpacing: 0.6 },
  primaryBtn: {
    marginTop: 14,
    paddingVertical: 14,
    borderRadius: 12,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: 'rgba(242,226,176,0.35)',
    backgroundColor: 'rgba(212,180,90,0.38)',
  },
  primaryBtnTxt: { fontSize: 12, fontWeight: '800', color: '#F2E6C5', letterSpacing: 0.9 },
  disconnectBtn: { backgroundColor: 'rgba(255,61,87,0.22)', borderColor: 'rgba(255,61,87,0.4)' },
  hint: { marginTop: 8, fontSize: 10, lineHeight: 15 },
  metricsRow: { flexDirection: 'row', gap: 8, marginTop: 12 },
  metricTile: { flex: 1, borderRadius: 10, borderWidth: 1, padding: 10 },
  metricLab: { fontSize: 9, fontWeight: '700', letterSpacing: 0.5 },
  metricVal: { fontSize: 14, fontWeight: '800', marginTop: 4 },
  metricSub: { fontSize: 9, marginTop: 2 },
  tickBar: {
    marginTop: 10,
    padding: 10,
    borderRadius: 10,
    borderWidth: 1,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  tickPrice: { fontSize: 16, fontWeight: '800' },
  tickSpread: { fontSize: 10, fontWeight: '600' },
  posRow: {
    marginTop: 6,
    paddingVertical: 8,
    paddingHorizontal: 10,
    borderRadius: 8,
    borderBottomWidth: 1,
  },
  posTxt: { fontSize: 11, fontWeight: '600' },
  row: { flexDirection: 'row', gap: 8, marginTop: 10 },
  miniBtn: { flex: 1, paddingVertical: 11, borderRadius: 10, alignItems: 'center' },
  miniTxt: { fontWeight: '800', fontSize: 11, letterSpacing: 0.5 },
  segmented: {
    flexDirection: 'row',
    marginTop: 8,
    borderRadius: 10,
    borderWidth: 1,
    overflow: 'hidden',
    padding: 3,
    gap: 4,
  },
  segment: {
    flex: 1,
    paddingVertical: 9,
    borderRadius: 8,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: 'transparent',
  },
  segmentTxt: { fontSize: 10, fontWeight: '800', letterSpacing: 0.5 },
  dotWrap: { width: 10, height: 10, alignItems: 'center', justifyContent: 'center' },
  dot: { width: 7, height: 7, borderRadius: 4 },
  rememberRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 10 },
  rememberLbl: { fontSize: 10, flex: 1, paddingRight: 8 },
  stepsRow: { flexDirection: 'row', gap: 6, marginTop: 12, flexWrap: 'wrap' },
  stepChip: {
    paddingVertical: 5,
    paddingHorizontal: 8,
    borderRadius: 6,
    borderWidth: 1,
  },
  stepTxt: { fontSize: 9, fontWeight: '700', letterSpacing: 0.4 },
});

export default function BinanceBridgePanel() {
  const { colors: C } = useBilshenzTheme();
  const mode = getBrokerMode();
  const metroLan = getMetroLanHost();
  const vpsUrl = getDefaultBinanceApiUrl();
  const showVps = isVpsDeployed() || !isLocalhostApiUrl(vpsUrl);
  const { baseUrl, setBaseUrl, connected, setConnected } = useBinanceBridge();

  const [apiKey, setApiKey] = useState('');
  const [apiSecret, setApiSecret] = useState('');
  const [showSecret, setShowSecret] = useState(false);
  const [testnet, setTestnet] = useState(true);
  const [rememberCreds, setRememberCreds] = useState(true);
  const [busy, setBusy] = useState(false);
  const [busyHint, setBusyHint] = useState('');
  const [err, setErr] = useState('');
  const [statusLine, setStatusLine] = useState('');
  const [account, setAccount] = useState(null);
  const [positions, setPositions] = useState([]);
  const [tick, setTick] = useState(null);
  const pollRef = useRef(null);

  const skin = useMemo(
    () => ({
      hero: { borderColor: 'rgba(212,180,90,0.28)' },
      card: { borderColor: C.border },
      inp: { borderColor: C.border, color: C.text, backgroundColor: C.inputBg },
      hint: { color: C.dim },
      rowLab: { color: C.dim },
      lanBtn: { borderColor: 'rgba(212,180,90,0.45)', backgroundColor: 'rgba(212,180,90,0.1)' },
      lanBtnTxt: { color: C.goldL },
      eyeBtn: { borderColor: C.border, backgroundColor: C.inputBg },
      statusPillOn: { borderColor: 'rgba(0,230,118,0.45)', backgroundColor: C.greenD },
      statusPillOff: { borderColor: 'rgba(255,61,87,0.35)', backgroundColor: C.redD },
    }),
    [C],
  );

  const modeLabel =
    mode === 'paper' ? 'PAPER SIM' : testnet ? 'TESTNET' : 'MAINNET LIVE';

  const stopPoll = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const refresh = useCallback(async () => {
    const b = baseUrl?.trim();
    if (!b) return;
    try {
      const stRes = await binanceFetch(b, '/api/status', {}, 15000);
      const st = await stRes.json();
      setConnected(!!st.connected);
      setAccount(st.account || null);
      setErr('');
      if (!st.connected) {
        setPositions([]);
        setTick(null);
        return;
      }
      const [posRes, tkRes] = await Promise.all([
        binanceFetch(b, '/api/positions', {}, 12000),
        binanceFetch(b, '/api/tick/XAUUSDT', {}, 10000),
      ]);
      const pos = await posRes.json().catch(() => ({}));
      const tk = tkRes.ok ? await tkRes.json() : null;
      setPositions(Array.isArray(pos.positions) ? pos.positions : []);
      setTick(tk);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [baseUrl, setConnected]);

  useEffect(() => {
    AsyncStorage.multiGet([
      STORAGE_BINANCE_KEY,
      STORAGE_BINANCE_SECRET,
      STORAGE_BINANCE_TESTNET,
      STORAGE_BINANCE_REMEMBER,
    ]).then((pairs) => {
      const m = Object.fromEntries(pairs);
      if (m[STORAGE_BINANCE_KEY]) setApiKey(m[STORAGE_BINANCE_KEY]);
      if (m[STORAGE_BINANCE_SECRET]) setApiSecret(m[STORAGE_BINANCE_SECRET]);
      if (m[STORAGE_BINANCE_TESTNET] === '0') setTestnet(false);
      if (m[STORAGE_BINANCE_REMEMBER] === '0') setRememberCreds(false);
    });
  }, []);

  useEffect(() => {
    if (showVps && isLocalhostApiUrl(baseUrl)) setBaseUrl(vpsUrl);
  }, [showVps, baseUrl, setBaseUrl, vpsUrl]);

  useEffect(() => {
    if (connected && baseUrl) {
      void refresh();
      stopPoll();
      pollRef.current = setInterval(() => refresh(), 5000);
      return stopPoll;
    }
    stopPoll();
    return undefined;
  }, [connected, baseUrl, refresh]);

  const finishConnected = useCallback(
    (acct, line) => {
      setConnected(true);
      setAccount(acct || null);
      setStatusLine(line || '');
      setErr('');
      void refresh();
    },
    [refresh, setConnected],
  );

  const onConnect = useCallback(async () => {
    setBusy(true);
    setBusyHint('Signing in to Binance Futures…');
    setErr('');
    try {
      const url = baseUrl || getDefaultBinanceApiUrl();
      setBaseUrl(url);
      let r;
      if (mode === 'paper') {
        r = await postBinanceAttach(url);
      } else if (apiKey.trim() && apiSecret.trim()) {
        r = await postBinanceLogin(url, {
          api_key: apiKey.trim(),
          api_secret: apiSecret.trim(),
          testnet,
        });
        if (rememberCreds) {
          await AsyncStorage.multiSet([
            [STORAGE_BINANCE_KEY, apiKey.trim()],
            [STORAGE_BINANCE_SECRET, apiSecret.trim()],
            [STORAGE_BINANCE_TESTNET, testnet ? '1' : '0'],
            [STORAGE_BINANCE_REMEMBER, '1'],
          ]);
        }
      } else {
        r = await postBinanceAttach(url);
      }
      if (r.ok) {
        finishConnected(
          r.account,
          `${modeLabel} · ${r.account?.server ?? 'binance'} · XAUUSDT`,
        );
      } else {
        setConnected(false);
        const msg = r.detail || 'Connect failed';
        setErr(msg);
        Alert.alert('Binance', msg);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setErr(msg);
    } finally {
      setBusy(false);
      setBusyHint('');
    }
  }, [
    apiKey,
    apiSecret,
    baseUrl,
    finishConnected,
    mode,
    modeLabel,
    rememberCreds,
    setBaseUrl,
    setConnected,
    testnet,
  ]);

  const onDisconnect = useCallback(async () => {
    setBusy(true);
    try {
      await binanceFetch(baseUrl, '/api/logout', { method: 'POST' }, 10000);
    } catch {
      /* ignore */
    }
    stopPoll();
    setConnected(false);
    setAccount(null);
    setPositions([]);
    setTick(null);
    setStatusLine('');
    setBusy(false);
  }, [baseUrl, setConnected]);

  const onTestApi = useCallback(async () => {
    setBusy(true);
    setErr('');
    const b = baseUrl.trim();
    try {
      const res = await binanceFetch(b, '/health', {}, 12000);
      const j = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(JSON.stringify(j));
      Alert.alert('Bridge online', `Service: ${j.service}\nMode: ${j.mode}\n\nTap CONNECT when ready.`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [baseUrl]);

  const onTestOrder = useCallback(async () => {
    if (!connected) return;
    setBusy(true);
    try {
      const res = await binanceFetch(
        baseUrl,
        '/api/order',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ symbol: 'XAUUSDT', side: 'BUY', volume: 0.001, sl: null, tp: null }),
        },
        20000,
      );
      const j = await res.json().catch(() => ({}));
      Alert.alert('Test order', res.ok ? 'Market order accepted' : String(j.detail ?? JSON.stringify(j)));
      await refresh();
    } catch (e) {
      Alert.alert('Test order', e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [baseUrl, connected, refresh]);

  const applyVpsUrl = () => setBaseUrl(getDefaultBinanceApiUrl());
  const applyLanUrl = () => {
    if (!metroLan) return;
    const desk = getDeskApiUrl();
    if (isLocalhostApiUrl(desk)) {
      setBaseUrl(`http://${metroLan}:8791/v1/binance`);
    } else {
      setBaseUrl(`${desk.replace(/\/$/, '')}/v1/binance`);
    }
  };

  const spreadPips =
    tick?.bid != null && tick?.ask != null ? ((tick.ask - tick.bid) / 0.1).toFixed(1) : null;

  return (
    <View style={st.root}>
      {/* Hero */}
      <View style={[st.hero, skin.hero]}>
        <View style={st.heroGlow} />
        <View style={st.logoRow}>
          <StaticHexLogo size={56} variant="icon" />
          <View>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
              <Text style={st.brandTitle}>BILSHENZ</Text>
              <BinanceDiamondMark size={18} />
            </View>
            <Text style={st.brandSub}>Binance USD-M Futures · BSV3.2</Text>
          </View>
        </View>

        <View
          style={[
            st.statusPill,
            connected ? skin.statusPillOn : skin.statusPillOff,
          ]}>
          <StatusDot on={connected} color={connected ? C.green : C.red} />
          <Text style={[st.statusTxt, { color: connected ? C.green : C.red }]}>
            {connected ? 'BRIDGE CONNECTED' : 'AWAITING CONNECTION'}
          </Text>
        </View>

        <View style={st.modeBadge}>
          <Text style={st.modeBadgeTxt}>{modeLabel} · {mode.toUpperCase()}</Text>
        </View>
      </View>

      {/* Form card */}
      <View style={[st.cardOuter, skin.card]}>
        <BlurView intensity={28} tint="dark" style={StyleSheet.absoluteFill} />
        <View style={st.cardInner}>
          <Text style={[st.sectionTitle, { color: C.gold }]}>EXECUTION BRIDGE</Text>

          <View style={st.stepsRow}>
            {['API URL', 'KEYS', 'CONNECT'].map((s, i) => (
              <View
                key={s}
                style={[
                  st.stepChip,
                  {
                    borderColor: connected || (i === 0 && baseUrl) ? 'rgba(212,180,90,0.4)' : C.border,
                    backgroundColor: 'rgba(0,0,0,0.25)',
                  },
                ]}>
                <Text style={[st.stepTxt, { color: C.dim }]}>{i + 1}. {s}</Text>
              </View>
            ))}
          </View>

          <Text style={[st.rowLab, skin.rowLab]}>API BASE URL</Text>
          <TextInput
            style={[st.inp, skin.inp]}
            value={baseUrl}
            onChangeText={setBaseUrl}
            autoCapitalize="none"
            autoCorrect={false}
            placeholder={vpsUrl}
            placeholderTextColor={C.dim2}
          />
          {Platform.OS !== 'web' && isLocalhostApiUrl(baseUrl) ? (
            <Text style={[st.hint, { color: C.amber }]}>
              {showVps
                ? '127.0.0.1 is this device — use VPS proxy below.'
                : 'Use your PC LAN IP or desk-api proxy (same Wi‑Fi as Expo).'}
            </Text>
          ) : null}
          {showVps ? (
            <Pressable style={[st.lanBtn, skin.lanBtn]} onPress={applyVpsUrl}>
              <Text style={[st.lanBtnTxt, skin.lanBtnTxt]}>USE VPS PROXY (/v1/binance)</Text>
            </Pressable>
          ) : null}
          {metroLan && !showVps ? (
            <Pressable style={[st.lanBtn, skin.lanBtn]} onPress={applyLanUrl}>
              <Text style={[st.lanBtnTxt, skin.lanBtnTxt]}>USE LAN DESK PROXY ({metroLan})</Text>
            </Pressable>
          ) : null}

          {mode !== 'paper' ? (
            <>
              <Text style={[st.rowLab, skin.rowLab]}>ENVIRONMENT</Text>
              <Segmented
                value={testnet ? 'testnet' : 'mainnet'}
                onChange={(v) => setTestnet(v === 'testnet')}
                options={[
                  { id: 'testnet', label: 'TESTNET' },
                  { id: 'mainnet', label: 'MAINNET' },
                ]}
                C={C}
              />

              <Text style={[st.rowLab, skin.rowLab]}>API KEY</Text>
              <TextInput
                style={[st.inp, skin.inp]}
                value={apiKey}
                onChangeText={setApiKey}
                autoCapitalize="none"
                autoCorrect={false}
                placeholder="Binance Futures API key"
                placeholderTextColor={C.dim2}
              />

              <Text style={[st.rowLab, skin.rowLab]}>API SECRET</Text>
              <View style={st.pwRow}>
                <TextInput
                  style={[st.inp, st.pwInp, skin.inp]}
                  value={apiSecret}
                  onChangeText={setApiSecret}
                  secureTextEntry={!showSecret}
                  autoCapitalize="none"
                  autoCorrect={false}
                  placeholder="••••••••••••"
                  placeholderTextColor={C.dim2}
                />
                <Pressable
                  style={[st.eyeBtn, skin.eyeBtn]}
                  onPress={() => setShowSecret((v) => !v)}
                  accessibilityLabel={showSecret ? 'Hide secret' : 'Show secret'}>
                  <Text style={st.eyeTxt}>{showSecret ? '🙈' : '👁'}</Text>
                </Pressable>
              </View>

              <View style={st.rememberRow}>
                <Text style={[st.rememberLbl, { color: C.dim }]}>Remember keys on this device</Text>
                <Pressable onPress={() => setRememberCreds((v) => !v)} hitSlop={8}>
                  <Text style={{ fontSize: 10, fontWeight: '800', color: rememberCreds ? C.green : C.dim2 }}>
                    {rememberCreds ? 'ON' : 'OFF'}
                  </Text>
                </Pressable>
              </View>
            </>
          ) : (
            <Text style={[st.hint, skin.hint, { marginTop: 12 }]}>
              Paper mode — simulated fills. Set BINANCE_PAPER=1 on the Python bridge. No API keys required.
            </Text>
          )}

          <Pressable style={[st.testBtn, { borderColor: 'rgba(64,196,255,0.35)', backgroundColor: 'rgba(64,196,255,0.08)' }]} onPress={onTestApi} disabled={busy}>
            <Text style={[st.testBtnTxt, { color: C.blue }]}>PING BRIDGE HEALTH</Text>
          </Pressable>

          {!connected ? (
            <Pressable style={st.primaryBtn} onPress={onConnect} disabled={busy}>
              {busy ? (
                <ActivityIndicator color="#F2E6C5" />
              ) : (
                <Text style={st.primaryBtnTxt}>
                  {mode === 'paper' ? 'CONNECT PAPER ENGINE' : 'CONNECT BINANCE FUTURES'}
                </Text>
              )}
            </Pressable>
          ) : (
            <Pressable style={[st.primaryBtn, st.disconnectBtn]} onPress={onDisconnect} disabled={busy}>
              <Text style={[st.primaryBtnTxt, { color: '#ffc8d0' }]}>DISCONNECT</Text>
            </Pressable>
          )}

          {busy && busyHint ? <Text style={[st.hint, { color: C.goldL }]}>{busyHint}</Text> : null}
          {statusLine && connected ? <Text style={[st.hint, { color: C.text }]}>{statusLine}</Text> : null}
          {err ? <Text style={[st.hint, { color: C.red }]}>{err}</Text> : null}

          {connected && account ? (
            <>
              <View style={st.metricsRow}>
                <MetricTile
                  label="BALANCE"
                  value={`$${Math.round(account.balance ?? 0).toLocaleString()}`}
                  sub={account.currency ?? 'USDT'}
                  C={C}
                />
                <MetricTile
                  label="EQUITY"
                  value={`$${Math.round(account.equity ?? account.balance ?? 0).toLocaleString()}`}
                  sub="Live"
                  accent={C.green}
                  C={C}
                />
              </View>

              {tick ? (
                <View style={[st.tickBar, { borderColor: C.border, backgroundColor: 'rgba(240,185,11,0.06)' }]}>
                  <View>
                    <Text style={[st.rowLab, { marginTop: 0, color: C.dim }]}>XAUUSDT</Text>
                    <Text style={[st.tickPrice, { color: C.goldL }]}>
                      {((tick.bid + tick.ask) / 2).toFixed(2)}
                    </Text>
                  </View>
                  <View style={{ alignItems: 'flex-end' }}>
                    <Text style={[st.tickSpread, { color: C.dim }]}>
                      {tick.bid?.toFixed?.(2)} / {tick.ask?.toFixed?.(2)}
                    </Text>
                    {spreadPips ? (
                      <Text style={[st.tickSpread, { color: C.teal, marginTop: 2 }]}>{spreadPips}p spread</Text>
                    ) : null}
                  </View>
                </View>
              ) : null}

              <Text style={[st.rowLab, skin.rowLab, { marginTop: 14 }]}>OPEN POSITIONS</Text>
              <ScrollView style={{ maxHeight: 120 }} nestedScrollEnabled>
                {positions.length === 0 ? (
                  <Text style={[st.hint, skin.hint]}>No open XAUUSDT position</Text>
                ) : (
                  positions.map((p, i) => (
                    <View key={String(p.ticket ?? i)} style={[st.posRow, { borderBottomColor: C.border }]}>
                      <Text style={[st.posTxt, { color: C.text }]}>
                        {p.type} {p.volume} · entry {p.price_open?.toFixed?.(2) ?? '—'} · P/L{' '}
                        <Text style={{ color: (p.profit ?? 0) >= 0 ? C.green : C.red }}>
                          {p.profit?.toFixed?.(2) ?? p.profit}
                        </Text>
                      </Text>
                    </View>
                  ))
                )}
              </ScrollView>

              {mode !== 'paper' ? (
                <Pressable
                  style={[st.testBtn, { borderColor: 'rgba(0,230,118,0.35)', backgroundColor: C.greenD, marginTop: 12 }]}
                  onPress={onTestOrder}
                  disabled={busy}>
                  <Text style={[st.testBtnTxt, { color: C.green }]}>TEST MIN QTY ORDER</Text>
                </Pressable>
              ) : null}
            </>
          ) : null}

          <Text style={[st.hint, skin.hint, { marginTop: 12 }]}>
            Start bridge: cd binance_trading_system\python → .\start-api.ps1 · Set EXPO_PUBLIC_BROKER_MODE=binance
          </Text>
        </View>
      </View>
    </View>
  );
}

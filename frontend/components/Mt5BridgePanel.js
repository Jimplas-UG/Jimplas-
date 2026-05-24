import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, Alert, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useMt5Bridge } from '../contexts/Mt5BridgeContext';
import { useBilshenzTheme } from '../contexts/ThemeContext';
import {
  postMt5Attach,
  postMt5Login,
  tryExistingMt5Session,
} from '../broker/mt5PythonApi';
import {
  formatMt5NetworkError,
  getDefaultMt5ApiUrl,
  getMetroLanHost,
  isLocalhostApiUrl,
} from '../utils/mt5ApiUrl';
import { isVpsDeployed, getDeskApiKey } from '../lib/envConfig';
import { parseApiErrorBody } from '../broker/mt5PythonApi';

const STORAGE_MT5_SERVER = '@bilshenz_v1/mt5Server';
const STORAGE_MT5_LOGIN = '@bilshenz_v1/mt5Login';
const STORAGE_MT5_PASSWORD = '@bilshenz_v1/mt5Password';
const STORAGE_MT5_REMEMBER = '@bilshenz_v1/mt5RememberCreds';

const styles = StyleSheet.create({
  title: { fontSize: 11, fontWeight: '800', color: '#c9b87c', letterSpacing: 1.2, marginTop: 14 },
  card: {
    marginTop: 8,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.12)',
    padding: 12,
    backgroundColor: 'rgba(0,0,0,0.28)',
  },
  rowLab: { fontSize: 10, fontWeight: '700', color: 'rgba(255,255,255,0.55)', marginTop: 8 },
  inp: {
    marginTop: 6,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.14)',
    borderRadius: 8,
    paddingVertical: 10,
    paddingHorizontal: 12,
    color: '#eaeaea',
    fontSize: 12,
    backgroundColor: 'rgba(0,0,0,0.22)',
  },
  btn: {
    marginTop: 12,
    paddingVertical: 12,
    borderRadius: 8,
    backgroundColor: 'rgba(212,180,90,0.35)',
    alignItems: 'center',
  },
  btnTxt: { fontSize: 12, fontWeight: '800', color: '#f2e6c5' },
  status: { marginTop: 10, fontSize: 11, fontWeight: '700' },
  hint: { marginTop: 6, fontSize: 10, color: 'rgba(255,255,255,0.45)', lineHeight: 14 },
  posRow: { marginTop: 6, paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: 'rgba(255,255,255,0.08)' },
  posTxt: { fontSize: 11, color: '#ddd' },
  row: { flexDirection: 'row', gap: 8, marginTop: 8 },
  miniBtn: { flex: 1, paddingVertical: 10, borderRadius: 8, alignItems: 'center', backgroundColor: 'rgba(60,120,200,0.35)' },
  miniBtnR: { backgroundColor: 'rgba(200,60,60,0.35)' },
  miniTxt: { fontWeight: '800', fontSize: 11, color: '#eee' },
  lanBtn: {
    marginTop: 8,
    paddingVertical: 9,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: 'rgba(212,180,90,0.45)',
    alignItems: 'center',
    backgroundColor: 'rgba(212,180,90,0.12)',
  },
  lanBtnTxt: { fontSize: 10, fontWeight: '800', color: '#e8d4a0', letterSpacing: 0.8 },
  testBtn: {
    marginTop: 8,
    paddingVertical: 9,
    borderRadius: 8,
    alignItems: 'center',
    backgroundColor: 'rgba(80,120,80,0.25)',
    borderWidth: 1,
    borderColor: 'rgba(120,200,120,0.35)',
  },
  testBtnTxt: { fontSize: 10, fontWeight: '800', color: '#b8e8b8', letterSpacing: 0.6 },
  pwRow: { flexDirection: 'row', alignItems: 'center', marginTop: 6, gap: 8 },
  pwInp: { flex: 1, marginTop: 0, paddingRight: 8 },
  eyeBtn: {
    width: 44,
    height: 44,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.14)',
    backgroundColor: 'rgba(0,0,0,0.22)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  eyeTxt: { fontSize: 18, color: 'rgba(242,226,197,0.85)' },
  rememberRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 8 },
  rememberLbl: { fontSize: 10, color: 'rgba(255,255,255,0.55)', flex: 1, paddingRight: 8 },
  forgetBtn: { marginTop: 4, alignSelf: 'flex-start' },
  forgetTxt: { fontSize: 10, color: 'rgba(212,180,90,0.75)', textDecorationLine: 'underline' },
});

function Mt5BridgePanel() {
  const { colors: C } = useBilshenzTheme();
  const metroLan = getMetroLanHost();
  const { baseUrl, setBaseUrl, connected, setConnected } = useMt5Bridge();
  const vpsUrl = getDefaultMt5ApiUrl();
  const showVps = isVpsDeployed() || !isLocalhostApiUrl(vpsUrl);

  const skin = useMemo(
    () => ({
      title: { color: C.gold },
      card: { borderColor: C.border, backgroundColor: 'rgba(0,0,0,0.28)' },
      rowLab: { color: C.dim },
      inp: { borderColor: C.border, color: C.text, backgroundColor: 'rgba(0,0,0,0.22)' },
      hint: { color: C.dim },
      posTxt: { color: C.text },
      btnTxt: { color: '#f2e6c5' },
    }),
    [C]
  );

  useEffect(() => {
    if (!showVps) return;
    const canonical = getDefaultMt5ApiUrl();
    if (canonical && mustForceVpsUrl(baseUrl, canonical)) {
      setBaseUrl(canonical);
    }
  }, [showVps, baseUrl, setBaseUrl]);

  function mustForceVpsUrl(current, canonical) {
    if (!canonical) return false;
    if (isLocalhostApiUrl(current)) return true;
    if (/:8765(\/|$)/.test(current)) return true;
    if (canonical.includes('/v1/mt5') && !current.includes('/v1/mt5')) return true;
    return false;
  }

  useEffect(() => {
    if (metroLan && isLocalhostApiUrl(baseUrl)) setBaseUrl(`http://${metroLan}:8765`);
  }, [metroLan, baseUrl, setBaseUrl]);
  const [server, setServer] = useState('');
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [rememberCreds, setRememberCreds] = useState(true);
  const [credsHydrated, setCredsHydrated] = useState(false);
  const [busy, setBusy] = useState(false);
  const [busyHint, setBusyHint] = useState('');
  const [err, setErr] = useState('');
  const [account, setAccount] = useState(null);
  const [positions, setPositions] = useState([]);
  const [tick, setTick] = useState(null);
  const pollRef = useRef(null);
  const autoConnectTried = useRef(false);

  const stopPoll = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const refresh = useCallback(async (opts = {}) => {
    const b = baseUrl.trim();
    if (!b) return;
    const light = !!opts.light;
    try {
      const st = await fetch(`${b}/api/status`).then((r) => r.json());
      setConnected(!!st.connected);
      setAccount(st.account || null);
      setErr('');
      if (!st.connected) {
        setPositions([]);
        setTick(null);
        return;
      }
      if (light) return;
      const [pos, tk] = await Promise.all([
        fetch(`${b}/api/positions`).then((r) => r.json()),
        fetch(`${b}/api/tick/XAUUSD`).then((r) => (r.ok ? r.json() : null)),
      ]);
      setPositions(Array.isArray(pos.positions) ? pos.positions : []);
      setTick(tk);
    } catch (e) {
      const raw = e instanceof Error ? e.message : String(e);
      setErr(formatMt5NetworkError(raw, b));
    }
  }, [baseUrl]);

  const finishConnected = useCallback(
    async (account) => {
      setConnected(true);
      setAccount(account || null);
      stopPoll();
      pollRef.current = setInterval(() => refresh({ light: false }), 5000);
      await refresh({ light: true });
      void refresh({ light: false });
    },
    [refresh],
  );

  useEffect(() => () => stopPoll(), []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [[, srv], [, log], [, pwd], [, rem]] = await AsyncStorage.multiGet([
          STORAGE_MT5_SERVER,
          STORAGE_MT5_LOGIN,
          STORAGE_MT5_PASSWORD,
          STORAGE_MT5_REMEMBER,
        ]);
        if (cancelled) return;
        const remember = rem !== '0';
        setRememberCreds(remember);
        if (remember) {
          if (srv) setServer(srv);
          if (log) setLogin(log);
          if (pwd) setPassword(pwd);
        }
      } catch {
        /* ignore */
      } finally {
        if (!cancelled) setCredsHydrated(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const persistCredentials = useCallback(async (srv, log, pwd, remember) => {
    try {
      if (!remember) {
        await AsyncStorage.multiRemove([STORAGE_MT5_SERVER, STORAGE_MT5_LOGIN, STORAGE_MT5_PASSWORD]);
        await AsyncStorage.setItem(STORAGE_MT5_REMEMBER, '0');
        return;
      }
      await AsyncStorage.multiSet([
        [STORAGE_MT5_SERVER, srv],
        [STORAGE_MT5_LOGIN, log],
        [STORAGE_MT5_PASSWORD, pwd],
        [STORAGE_MT5_REMEMBER, '1'],
      ]);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    if (!credsHydrated || !rememberCreds) return;
    const t = setTimeout(() => {
      void persistCredentials(server.trim(), login.trim(), password, true);
    }, 600);
    return () => clearTimeout(t);
  }, [server, login, password, rememberCreds, credsHydrated, persistCredentials]);

  const onForgetCredentials = () => {
    setServer('');
    setLogin('');
    setPassword('');
    setRememberCreds(false);
    void persistCredentials('', '', '', false);
  };

  const ensureApiReachable = async (b) => {
    const hdrs = b.includes('/v1/mt5') ? { Authorization: `Bearer ${getDeskApiKey()}` } : {};
    const health = await fetch(`${b}/health`, { method: 'GET', headers: hdrs });
    if (!health.ok) {
      const txt = await health.text().catch(() => '');
      throw new Error(parseApiErrorBody(txt, health.status));
    }
  };

  const onConnect = async () => {
    setBusy(true);
    setBusyHint('');
    setErr('');
    const b = baseUrl.trim();
    const serverTrim = server.trim();
    const loginTrim = login.trim();
    const loginNum = parseInt(loginTrim, 10);
    if (!b) {
      setErr('Set API BASE URL first (e.g. http://127.0.0.1:8765 on this PC, or http://PC_IP:8765 from phone).');
      setBusy(false);
      return;
    }
    if (!serverTrim) {
      setErr('Enter your broker server name exactly as shown in MT5 (any broker).');
      setBusy(false);
      return;
    }
    if (!Number.isFinite(loginNum) || loginNum <= 0) {
      setErr('Enter a valid numeric login (account number).');
      setBusy(false);
      return;
    }
    if (!password) {
      setErr('Enter your MT5 trading password.');
      setBusy(false);
      return;
    }
    try {
      await ensureApiReachable(b);
      setBusyHint('Checking existing MT5 session…');
      const existing = await tryExistingMt5Session(b, loginNum, serverTrim);
      if (existing.ok) {
        await persistCredentials(serverTrim, loginTrim, password, rememberCreds);
        await finishConnected(existing.account);
        return;
      }
      setBusyHint('Logging in to broker (may take up to 45s)…');
      const result = await postMt5Login(b, {
        login: loginNum,
        password,
        server: serverTrim,
      });
      if (!result.ok) throw new Error(result.detail || 'Login failed');
      await persistCredentials(serverTrim, loginTrim, password, rememberCreds);
      await finishConnected(result.account);
    } catch (e) {
      const raw = e instanceof Error ? e.message : String(e);
      setErr(formatMt5NetworkError(raw, b));
      setConnected(false);
    } finally {
      setBusy(false);
      setBusyHint('');
    }
  };

  const onAttachTerminal = async () => {
    setBusy(true);
    setBusyHint('');
    setErr('');
    const b = baseUrl.trim();
    if (!b) {
      setErr('Set API BASE URL first.');
      setBusy(false);
      return;
    }
    try {
      await ensureApiReachable(b);
      setBusyHint('Using MT5 terminal session…');
      const result = await postMt5Attach(b);
      if (!result.ok) throw new Error(result.detail || 'No MT5 session');
      const acc = result.account;
      if (acc?.server) setServer(String(acc.server));
      if (acc?.login) setLogin(String(acc.login));
      await finishConnected(acc);
    } catch (e) {
      const raw = e instanceof Error ? e.message : String(e);
      setErr(formatMt5NetworkError(raw, b));
      setConnected(false);
    } finally {
      setBusy(false);
      setBusyHint('');
    }
  };

  useEffect(() => {
    if (!credsHydrated || connected || busy || autoConnectTried.current) return;
    if (!server.trim() || !login.trim() || !password) return;
    autoConnectTried.current = true;
    const t = setTimeout(() => void onConnect(), 400);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- one-shot auto login on launch
  }, [credsHydrated, connected, busy, server, login, password]);

  const onDisconnect = async () => {
    setBusy(true);
    try {
      const b = baseUrl.trim();
      await fetch(`${b}/api/logout`, { method: 'POST' });
    } catch {
      /* ignore */
    }
    stopPoll();
    setConnected(false);
    setAccount(null);
    setPositions([]);
    setTick(null);
    setBusy(false);
  };

  const sendManual = async (side) => {
    const b = baseUrl.trim();
    setErr('');
    try {
      const res = await fetch(`${b}/api/order`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: 'XAUUSD', side, volume: 0.01 }),
      });
      const j = await res.json();
      if (!res.ok) throw new Error(typeof j.detail === 'string' ? j.detail : JSON.stringify(j));
      await refresh();
    } catch (e) {
      const raw = e instanceof Error ? e.message : String(e);
      setErr(formatMt5NetworkError(raw, b));
    }
  };

  const applyLanUrl = () => {
    if (metroLan) setBaseUrl(`http://${metroLan}:8765`);
  };

  const applyVpsUrl = () => {
    setBaseUrl(getDefaultMt5ApiUrl());
  };

  const onTestApi = async () => {
    setBusy(true);
    setErr('');
    const b = baseUrl.trim();
    try {
      const hdrs = b.includes('/v1/mt5') ? { Authorization: `Bearer ${getDeskApiKey()}` } : {};
      const res = await fetch(`${b}/health`, { method: 'GET', headers: hdrs });
      const txt = await res.text();
      if (!res.ok) throw new Error(parseApiErrorBody(txt, res.status));
      setErr('');
      setConnected(false);
      Alert.alert('API reachable', `${txt}\n\nNow tap CONNECT MT5.`);
    } catch (e) {
      const raw = e instanceof Error ? e.message : String(e);
      setErr(formatMt5NetworkError(raw, b));
    } finally {
      setBusy(false);
    }
  };

  return (
    <View>
      <Text style={[styles.title, skin.title]}>MT5 PYTHON API</Text>
      <View style={[styles.card, skin.card]}>
        <Text style={[styles.rowLab, skin.rowLab]}>API BASE URL</Text>
        <TextInput
          style={[styles.inp, skin.inp]}
          value={baseUrl}
          onChangeText={(t) => setBaseUrl(t)}
          autoCapitalize="none"
          autoCorrect={false}
          placeholder={showVps ? vpsUrl : metroLan ? `http://${metroLan}:8765` : 'http://192.168.x.x:8765'}
          placeholderTextColor="#666"
        />
        {Platform.OS !== 'web' && isLocalhostApiUrl(baseUrl) ? (
          <Text style={[styles.hint, { color: '#ffb86c', marginTop: 6 }]}>
            {showVps
              ? '127.0.0.1 is the phone itself — tap USE VPS SERVER below (no PC window needed).'
              : '127.0.0.1 will not reach your PC from a phone. Use your Windows LAN IP (same Wi‑Fi as Expo).'}
          </Text>
        ) : null}
        {showVps ? (
          <Pressable style={styles.lanBtn} onPress={applyVpsUrl}>
            <Text style={styles.lanBtnTxt}>USE VPS SERVER (port 8791 — no PC needed)</Text>
          </Pressable>
        ) : null}
        {metroLan && !showVps ? (
          <Pressable style={styles.lanBtn} onPress={applyLanUrl}>
            <Text style={styles.lanBtnTxt}>USE PC IP FROM EXPO ({metroLan})</Text>
          </Pressable>
        ) : null}
        <Text style={styles.rowLab}>SERVER</Text>
        <TextInput
          style={styles.inp}
          value={server}
          onChangeText={setServer}
          autoCapitalize="none"
          placeholder="Broker server from MT5 (any broker)"
          placeholderTextColor="#666"
        />
        <Text style={styles.rowLab}>LOGIN</Text>
        <TextInput style={styles.inp} value={login} onChangeText={setLogin} keyboardType="numeric" placeholder="12345678" placeholderTextColor="#666" />
        <Text style={styles.rowLab}>PASSWORD</Text>
        <View style={styles.pwRow}>
          <TextInput
            style={[styles.inp, styles.pwInp]}
            value={password}
            onChangeText={setPassword}
            secureTextEntry={!showPassword}
            autoCapitalize="none"
            autoCorrect={false}
            placeholder="••••••••"
            placeholderTextColor="#666"
          />
          <Pressable
            style={styles.eyeBtn}
            onPress={() => setShowPassword((v) => !v)}
            accessibilityRole="button"
            accessibilityLabel={showPassword ? 'Hide password' : 'Show password'}>
            <Text style={styles.eyeTxt}>{showPassword ? '🙈' : '👁'}</Text>
          </Pressable>
        </View>

        <View style={styles.rememberRow}>
          <Text style={styles.rememberLbl}>Remember login on this device</Text>
          <Pressable
            onPress={() => {
              const next = !rememberCreds;
              setRememberCreds(next);
              if (!next) void persistCredentials('', '', '', false);
            }}
            hitSlop={8}>
            <Text style={[styles.status, { color: rememberCreds ? '#6dffb0' : '#888', marginTop: 0 }]}>
              {rememberCreds ? 'ON' : 'OFF'}
            </Text>
          </Pressable>
        </View>
        {rememberCreds && (server || login) ? (
          <Pressable style={styles.forgetBtn} onPress={onForgetCredentials}>
            <Text style={styles.forgetTxt}>Clear saved credentials</Text>
          </Pressable>
        ) : null}

        <Pressable style={styles.testBtn} onPress={onTestApi} disabled={busy}>
          <Text style={styles.testBtnTxt}>TEST API (must pass before CONNECT)</Text>
        </Pressable>

        <Pressable style={[styles.lanBtn, { marginTop: 10 }]} onPress={onAttachTerminal} disabled={busy}>
          <Text style={styles.lanBtnTxt}>USE MT5 TERMINAL SESSION (fastest)</Text>
        </Pressable>
        <Text style={[styles.hint, { marginTop: 4 }]}>
          Log in inside MT5 first (Exness, IC, FXCM, etc.), then tap above — no slow IPC login.
        </Text>

        {!connected ? (
          <Pressable style={styles.btn} onPress={onConnect} disabled={busy}>
            {busy ? <ActivityIndicator color="#f2e6c5" /> : <Text style={styles.btnTxt}>CONNECT MT5 (login + password)</Text>}
          </Pressable>
        ) : (
          <Pressable style={[styles.btn, { backgroundColor: 'rgba(180,60,60,0.4)' }]} onPress={onDisconnect} disabled={busy}>
            <Text style={styles.btnTxt}>DISCONNECT</Text>
          </Pressable>
        )}

        {busy && busyHint ? <Text style={[styles.hint, { color: '#e8d4a0', marginTop: 8 }]}>{busyHint}</Text> : null}

        <Text style={[styles.status, { color: connected ? '#6dffb0' : '#ff8b7a' }]}>
          {connected ? '● CONNECTED' : '○ DISCONNECTED'}
        </Text>

        {account ? (
          <Text style={[styles.hint, { color: '#cfcfcf' }]}>
            Bal {account.balance?.toFixed?.(2) ?? '—'} · Eq {account.equity?.toFixed?.(2) ?? '—'} · {account.currency ?? ''}
          </Text>
        ) : null}
        {tick ? (
          <Text style={[styles.hint, { color: '#a8d4ff' }]}>
            XAUUSD bid {tick.bid} ask {tick.ask}
          </Text>
        ) : connected ? (
          <Text style={styles.hint}>No tick yet (check symbol name on broker).</Text>
        ) : null}

        {connected ? (
          <>
            <Text style={[styles.rowLab, { marginTop: 12 }]}>OPEN POSITIONS</Text>
            <ScrollView style={{ maxHeight: 140 }} nestedScrollEnabled>
              {positions.length === 0 ? <Text style={styles.hint}>None</Text> : null}
              {positions.map((p) => (
                <View key={String(p.ticket)} style={styles.posRow}>
                  <Text style={styles.posTxt}>
                    #{p.ticket} {p.type} {p.volume} {p.symbol} P/L {p.profit?.toFixed?.(2) ?? p.profit}
                  </Text>
                </View>
              ))}
            </ScrollView>
            <Text style={[styles.rowLab, { marginTop: 8 }]}>MANUAL (0.01 lot demo)</Text>
            <View style={styles.row}>
              <Pressable style={styles.miniBtn} onPress={() => sendManual('BUY')}>
                <Text style={styles.miniTxt}>BUY</Text>
              </Pressable>
              <Pressable style={[styles.miniBtn, styles.miniBtnR]} onPress={() => sendManual('SELL')}>
                <Text style={styles.miniTxt}>SELL</Text>
              </Pressable>
            </View>
          </>
        ) : null}

        {err ? <Text style={[styles.hint, { color: '#ff7a8a', marginTop: 8 }]}>{err}</Text> : null}
        <Text style={[styles.hint, { marginTop: 10 }]}>
          On PC: cd mt5_trading_system\python → .\start-api.ps1 (MT5 open + logged in). Phone URL =
          http://PC_LAN_IP:8765 — tap USE PC IP FROM EXPO. Not 127.0.0.1. Demo first for AUTO-EXECUTE.
        </Text>
      </View>
    </View>
  );
}

export default Mt5BridgePanel;

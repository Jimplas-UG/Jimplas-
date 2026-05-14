import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';

const DEFAULT_API =
  (typeof process !== 'undefined' && process.env?.EXPO_PUBLIC_MT5_API_URL) || 'http://127.0.0.1:8765';

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
});

export function Mt5BridgePanel() {
  const [baseUrl, setBaseUrl] = useState(DEFAULT_API.replace(/\/$/, ''));
  const [server, setServer] = useState('');
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [connected, setConnected] = useState(false);
  const [account, setAccount] = useState(null);
  const [positions, setPositions] = useState([]);
  const [tick, setTick] = useState(null);
  const pollRef = useRef(null);

  const stopPoll = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const refresh = useCallback(async () => {
    const b = baseUrl.trim();
    if (!b) return;
    try {
      const [st, pos, tk] = await Promise.all([
        fetch(`${b}/api/status`).then((r) => r.json()),
        fetch(`${b}/api/positions`).then((r) => r.json()),
        fetch(`${b}/api/tick/XAUUSD`).then((r) => (r.ok ? r.json() : null)),
      ]);
      setConnected(!!st.connected);
      setAccount(st.account || null);
      setPositions(Array.isArray(pos.positions) ? pos.positions : []);
      setTick(tk);
      setErr('');
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }, [baseUrl]);

  useEffect(() => () => stopPoll(), []);

  const onConnect = async () => {
    setBusy(true);
    setErr('');
    try {
      const b = baseUrl.trim();
      const res = await fetch(`${b}/api/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          login: parseInt(login, 10),
          password,
          server: server.trim(),
        }),
      });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(j.detail || JSON.stringify(j));
      setConnected(true);
      setAccount(j.account || null);
      stopPoll();
      pollRef.current = setInterval(refresh, 3000);
      await refresh();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setConnected(false);
    } finally {
      setBusy(false);
    }
  };

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
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <View>
      <Text style={styles.title}>MT5 PYTHON API</Text>
      <View style={styles.card}>
        <Text style={styles.rowLab}>API BASE URL</Text>
        <TextInput
          style={styles.inp}
          value={baseUrl}
          onChangeText={setBaseUrl}
          autoCapitalize="none"
          autoCorrect={false}
          placeholder="http://PC-IP:8765"
          placeholderTextColor="#666"
        />
        <Text style={styles.rowLab}>SERVER</Text>
        <TextInput
          style={styles.inp}
          value={server}
          onChangeText={setServer}
          autoCapitalize="none"
          placeholder="Exness-MT5Trial"
          placeholderTextColor="#666"
        />
        <Text style={styles.rowLab}>LOGIN</Text>
        <TextInput style={styles.inp} value={login} onChangeText={setLogin} keyboardType="numeric" placeholder="12345678" placeholderTextColor="#666" />
        <Text style={styles.rowLab}>PASSWORD</Text>
        <TextInput
          style={styles.inp}
          value={password}
          onChangeText={setPassword}
          secureTextEntry
          placeholder="••••••••"
          placeholderTextColor="#666"
        />

        {!connected ? (
          <Pressable style={styles.btn} onPress={onConnect} disabled={busy}>
            {busy ? <ActivityIndicator color="#f2e6c5" /> : <Text style={styles.btnTxt}>CONNECT MT5</Text>}
          </Pressable>
        ) : (
          <Pressable style={[styles.btn, { backgroundColor: 'rgba(180,60,60,0.4)' }]} onPress={onDisconnect} disabled={busy}>
            <Text style={styles.btnTxt}>DISCONNECT</Text>
          </Pressable>
        )}

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
          Run Python API on the same Windows PC as MT5 (see mt5_trading_system/install.md). Set EXPO_PUBLIC_MT5_API_URL when building Expo.
        </Text>
      </View>
    </View>
  );
}

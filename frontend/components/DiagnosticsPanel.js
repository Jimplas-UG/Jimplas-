import React, { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { useBilshenzTheme } from '../contexts/ThemeContext';

function Row({ label, value, color }) {
  const { colors: C } = useBilshenzTheme();
  return (
    <View style={st.row}>
      <Text style={[st.label, { color: C.dim }]}>{label}</Text>
      <Text style={[st.value, { color: color || C.text }]} numberOfLines={1}>
        {value ?? '—'}
      </Text>
    </View>
  );
}

/**
 * Live VPS / Binance diagnostics — no UI redesign, compact panel.
 */
export default function DiagnosticsPanel({ diagnostics, loading, onRefresh, style }) {
  const { colors: C } = useBilshenzTheme();
  const d = diagnostics || {};
  const wsOk = d.user_data_stream?.ws_connected || d.scanner_stream?.ws_connected;
  const execMs = d.execution?.last_latency_ms ?? d.scanner?.last_exec_latency_ms;

  return (
    <View style={[st.wrap, { backgroundColor: C.panel, borderColor: C.border }, style]}>
      <View style={st.head}>
        <Text style={[st.title, { color: C.text }]}>Live diagnostics</Text>
        {onRefresh ? (
          <Pressable onPress={onRefresh} hitSlop={8}>
            <Text style={{ color: C.accentLight, fontSize: 12, fontWeight: '700' }}>Refresh</Text>
          </Pressable>
        ) : null}
      </View>
      {loading && !d.ok ? (
        <ActivityIndicator color={C.goldL} style={{ marginVertical: 8 }} />
      ) : null}
      <Row label="Binance API" value={d.binance_latency_ms != null ? `${d.binance_latency_ms} ms` : '—'} />
      <Row label="CPU" value={d.cpu_pct != null ? `${d.cpu_pct}%` : '—'} />
      <Row
        label="RAM"
        value={
          d.memory?.ram_used_mb != null
            ? `${d.memory.ram_used_mb}/${d.memory.ram_total_mb} MB`
            : '—'
        }
      />
      <Row label="WebSocket" value={wsOk ? 'Connected' : 'Reconnecting…'} color={wsOk ? C.green : C.amber} />
      <Row label="Active pair" value={d.pair_isolation?.active_symbol || 'None'} />
      <Row label="Last exec" value={execMs != null ? `${execMs} ms` : '—'} />
      <Row
        label="Last sync"
        value={
          d.user_data_stream?.last_sync_ms
            ? new Date(d.user_data_stream.last_sync_ms).toLocaleTimeString()
            : '—'
        }
      />
    </View>
  );
}

const st = StyleSheet.create({
  wrap: { borderWidth: 1, borderRadius: 14, padding: 12, marginTop: 10 },
  head: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 },
  title: { fontSize: 12, fontWeight: '700' },
  row: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 3, gap: 8 },
  label: { fontSize: 11, flex: 1 },
  value: { fontSize: 11, fontWeight: '600', flex: 1, textAlign: 'right' },
});

import React from 'react';
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useBilshenzTheme } from '../../contexts/ThemeContext';
import { useDevPreview } from '../../contexts/DevPreviewContext';

const st = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.85)' },
  card: {
    flex: 1,
    marginTop: 48,
    marginHorizontal: 8,
    marginBottom: 8,
    borderRadius: 14,
    borderWidth: 1,
    padding: 12,
  },
  title: { fontSize: 12, fontWeight: '800', letterSpacing: 1.2, marginBottom: 8 },
  section: { fontSize: 10, fontWeight: '800', letterSpacing: 0.8, marginTop: 12, marginBottom: 6 },
  row: { fontSize: 10, lineHeight: 16, fontFamily: 'monospace' },
  logRow: {
    paddingVertical: 6,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255,255,255,0.06)',
  },
  btn: { marginTop: 12, paddingVertical: 10, borderRadius: 8, alignItems: 'center', borderWidth: 1 },
  btnTxt: { fontSize: 10, fontWeight: '800' },
});

export default function DevDebugPanel({ visible, onClose, currentTab, engineState, snapshot }) {
  const { colors: C } = useBilshenzTheme();
  const { apiLog, clearLog, refreshLog, mockApi } = useDevPreview();

  const trade = snapshot?.trade;
  const sig = snapshot?.signals;

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <View style={[st.backdrop, { backgroundColor: C.black }]}>
        <View style={[st.card, { borderColor: C.border, backgroundColor: C.panel }]}>
          <Text style={[st.title, { color: C.gold }]}>DEBUG INSPECTOR</Text>

          <ScrollView>
            <Text style={[st.section, { color: C.goldL }]}>NAVIGATION</Text>
            <Text style={[st.row, { color: C.text }]}>currentTab: {currentTab}</Text>
            <Text style={[st.row, { color: C.text }]}>mockApi: {String(mockApi)}</Text>
            <Text style={[st.row, { color: C.text }]}>bundleReady: {String(engineState?.bundleReady)}</Text>
            <Text style={[st.row, { color: C.text }]}>runMode: {engineState?.runMode ?? '—'}</Text>

            <Text style={[st.section, { color: C.goldL }]}>SNAPSHOT</Text>
            <Text style={[st.row, { color: C.text }]}>
              signal: {sig?.anyBuy ? 'BUY' : sig?.anySell ? 'SELL' : '—'} · allowed: {String(trade?.allowed)}
            </Text>
            <Text style={[st.row, { color: C.text }]}>
              setup: {trade?.setup ?? '—'} · entry: {trade?.entry ?? '—'} · sl: {trade?.sl ?? '—'}
            </Text>
            <Text style={[st.row, { color: C.text }]}>
              session: {snapshot?.session?.sessionLabel ?? '—'} · risk: {snapshot?.risk?.riskLevel ?? '—'}
            </Text>

            <Text style={[st.section, { color: C.goldL }]}>MOCK API LOG</Text>
            {apiLog.length === 0 ? (
              <Text style={[st.row, { color: C.dim }]}>No mock calls yet</Text>
            ) : (
              apiLog.slice(0, 20).map((row, i) => (
                <View key={`${row.ts}-${i}`} style={st.logRow}>
                  <Text style={[st.row, { color: C.teal }]}>
                    {new Date(row.ts).toISOString().slice(11, 19)} {row.path} — {row.detail}
                  </Text>
                </View>
              ))
            )}
          </ScrollView>

          <Pressable
            style={[st.btn, { borderColor: C.border }]}
            onPress={() => {
              clearLog();
              refreshLog();
            }}>
            <Text style={[st.btnTxt, { color: C.amber }]}>CLEAR LOG</Text>
          </Pressable>
          <Pressable style={[st.btn, { borderColor: C.gold, backgroundColor: 'rgba(212,180,90,0.2)' }]} onPress={onClose}>
            <Text style={[st.btnTxt, { color: C.goldL }]}>CLOSE</Text>
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

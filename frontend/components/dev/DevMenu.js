import React from 'react';
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { BlurView } from 'expo-blur';
import { useBilshenzTheme } from '../../contexts/ThemeContext';
import { useDevPreview } from '../../contexts/DevPreviewContext';
import { devScreens } from '../../lib/devPreview';
import DevDebugPanel from './DevDebugPanel';

const st = StyleSheet.create({
  fab: {
    position: 'absolute',
    right: 14,
    bottom: 88,
    width: 52,
    height: 52,
    borderRadius: 26,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: 'rgba(212,180,90,0.55)',
    backgroundColor: 'rgba(212,180,90,0.25)',
    zIndex: 9999,
    elevation: 12,
  },
  fabTxt: { fontSize: 18, fontWeight: '800', color: '#F2E2B0' },
  backdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.72)', justifyContent: 'flex-end' },
  sheet: {
    maxHeight: '88%',
    borderTopLeftRadius: 18,
    borderTopRightRadius: 18,
    borderWidth: 1,
    borderColor: 'rgba(212,180,90,0.35)',
    overflow: 'hidden',
  },
  sheetInner: { padding: 16, paddingBottom: 28 },
  title: { fontSize: 12, fontWeight: '800', letterSpacing: 1.4, color: '#D4B45A' },
  sub: { fontSize: 10, color: 'rgba(122,108,69,0.95)', marginTop: 4, marginBottom: 12 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  tile: {
    width: '48%',
    paddingVertical: 14,
    paddingHorizontal: 10,
    borderRadius: 12,
    borderWidth: 1,
    alignItems: 'center',
  },
  tileIcon: { fontSize: 20 },
  tileLbl: { marginTop: 6, fontSize: 10, fontWeight: '800', letterSpacing: 0.6 },
  close: { marginTop: 14, paddingVertical: 12, borderRadius: 10, alignItems: 'center', borderWidth: 1 },
  closeTxt: { fontSize: 11, fontWeight: '800', letterSpacing: 0.8 },
});

/**
 * Floating dev menu — jump to any app screen + debug panel.
 */
export default function DevMenu({ currentTab, onNavigate, engineState, snapshot }) {
  const { colors: C } = useBilshenzTheme();
  const { enabled, menuOpen, setMenuOpen, debugOpen, setDebugOpen, mockApi } = useDevPreview();

  if (!enabled) return null;

  return (
    <>
      <Pressable
        style={st.fab}
        onPress={() => setMenuOpen(true)}
        accessibilityLabel="Open dev menu">
        <Text style={st.fabTxt}>⚙</Text>
      </Pressable>

      <Modal visible={menuOpen} transparent animationType="slide" onRequestClose={() => setMenuOpen(false)}>
        <Pressable style={st.backdrop} onPress={() => setMenuOpen(false)}>
          <Pressable style={[st.sheet, { backgroundColor: C.panel }]} onPress={(e) => e.stopPropagation()}>
            <BlurView intensity={24} tint="dark" style={StyleSheet.absoluteFill} />
            <ScrollView contentContainerStyle={st.sheetInner}>
              <Text style={st.title}>DEV NAVIGATOR</Text>
              <Text style={st.sub}>
                Mock API {mockApi ? 'ON' : 'OFF'} · Hot reload active · Tab: {currentTab}
              </Text>

              <View style={st.grid}>
                {devScreens().map((s) => (
                  <Pressable
                    key={s.id}
                    onPress={() => {
                      onNavigate(s.id);
                      setMenuOpen(false);
                    }}
                    style={[
                      st.tile,
                      {
                        borderColor: currentTab === s.id ? C.gold : C.border,
                        backgroundColor: currentTab === s.id ? 'rgba(212,180,90,0.15)' : 'rgba(0,0,0,0.35)',
                      },
                    ]}>
                    <Text style={st.tileIcon}>{s.icon}</Text>
                    <Text style={[st.tileLbl, { color: currentTab === s.id ? C.goldL : C.text }]}>{s.label}</Text>
                  </Pressable>
                ))}
              </View>

              <Pressable
                style={[st.close, { borderColor: C.border, backgroundColor: 'rgba(64,196,255,0.12)' }]}
                onPress={() => {
                  setMenuOpen(false);
                  setDebugOpen(true);
                }}>
                <Text style={[st.closeTxt, { color: C.blue }]}>OPEN DEBUG INSPECTOR</Text>
              </Pressable>

              <Pressable
                style={[st.close, { borderColor: C.border }]}
                onPress={() => setMenuOpen(false)}>
                <Text style={[st.closeTxt, { color: C.dim }]}>CLOSE</Text>
              </Pressable>
            </ScrollView>
          </Pressable>
        </Pressable>
      </Modal>

      <DevDebugPanel
        visible={debugOpen}
        onClose={() => setDebugOpen(false)}
        currentTab={currentTab}
        engineState={engineState}
        snapshot={snapshot}
      />
    </>
  );
}

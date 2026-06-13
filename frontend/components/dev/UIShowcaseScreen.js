import React, { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { useBilshenzTheme } from '../../contexts/ThemeContext';
import StaticHexLogo from '../logo/StaticHexLogo';
import BilshenzHeader from '../BilshenzHeader';
import GeoPoliticalTicker from '../GeoPoliticalTicker';
import BootFallback from '../BootFallback';
import BinanceBridgePanel from '../BinanceBridgePanel';
import { darkPalette } from '../../theme/palettes';

const st = StyleSheet.create({
  root: { paddingBottom: 32 },
  hero: {
    alignItems: 'center',
    paddingVertical: 20,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(212,180,90,0.2)',
  },
  title: { fontSize: 13, fontWeight: '800', letterSpacing: 1.5, marginTop: 10 },
  sub: { fontSize: 10, marginTop: 4, letterSpacing: 0.5 },
  section: {
    marginTop: 16,
    marginHorizontal: 12,
    borderRadius: 14,
    borderWidth: 1,
    overflow: 'hidden',
  },
  sectionHead: { padding: 12, borderBottomWidth: 1 },
  sectionTitle: { fontSize: 10, fontWeight: '800', letterSpacing: 1.2 },
  sectionBody: { padding: 12 },
  swatchRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  swatch: { width: 72, height: 48, borderRadius: 8, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  swatchTxt: { fontSize: 8, fontWeight: '700' },
  pill: {
    alignSelf: 'flex-start',
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: 8,
    borderWidth: 1,
    marginTop: 8,
  },
  pillTxt: { fontSize: 10, fontWeight: '800' },
  btn: { marginTop: 10, paddingVertical: 12, borderRadius: 10, alignItems: 'center', borderWidth: 1 },
  btnTxt: { fontSize: 11, fontWeight: '800', letterSpacing: 0.6 },
});

function ColorSwatches({ C }) {
  const keys = ['gold', 'goldL', 'green', 'red', 'amber', 'blue', 'teal', 'text', 'dim', 'panel'];
  return (
    <View style={st.swatchRow}>
      {keys.map((k) => (
        <View key={k} style={[st.swatch, { backgroundColor: C[k] ?? darkPalette[k], borderColor: C.border }]}>
          <Text style={[st.swatchTxt, { color: k === 'text' || k === 'goldL' ? C.black : C.text }]}>{k}</Text>
        </View>
      ))}
    </View>
  );
}

function StatePills({ C }) {
  const states = [
    { label: 'READY', bg: C.greenD, border: C.green, color: C.green },
    { label: 'BLOCKED', bg: C.redD, border: C.red, color: C.red },
    { label: 'WARN', bg: 'rgba(255,179,0,0.12)', border: C.amber, color: C.amber },
    { label: 'WAIT', bg: 'rgba(64,196,255,0.1)', border: C.blue, color: C.blue },
  ];
  return (
    <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
      {states.map((s) => (
        <View key={s.label} style={[st.pill, { backgroundColor: s.bg, borderColor: s.border }]}>
          <Text style={[st.pillTxt, { color: s.color }]}>{s.label}</Text>
        </View>
      ))}
    </View>
  );
}

/**
 * UI component gallery — all reusable BSV3.2 surfaces in one scroll.
 */
export default function UIShowcaseScreen({ pad = 16 }) {
  const { colors: C, styles } = useBilshenzTheme();
  const { width } = useWindowDimensions();
  const [showFallback, setShowFallback] = useState(false);

  if (showFallback) {
    return (
      <BootFallback
        message="Demo error boundary — tap retry"
        onRetry={() => setShowFallback(false)}
      />
    );
  }

  return (
    <ScrollView style={st.root} contentContainerStyle={{ paddingBottom: 100 }}>
      <View style={st.hero}>
        <StaticHexLogo size={width > 400 ? 88 : 72} variant="splash" />
        <Text style={[st.title, { color: C.goldL }]}>UI SHOWCASE</Text>
        <Text style={[st.sub, { color: C.dim }]}>BSV3.2 · {width.toFixed(0)}px wide · Dev preview</Text>
      </View>

      <View style={[st.section, { borderColor: C.border, marginHorizontal: pad }]}>
        <View style={[st.sectionHead, { borderBottomColor: C.border, backgroundColor: 'rgba(0,0,0,0.35)' }]}>
          <Text style={[st.sectionTitle, { color: C.gold }]}>THEME PALETTE</Text>
        </View>
        <View style={st.sectionBody}>
          <ColorSwatches C={C} />
        </View>
      </View>

      <View style={[st.section, { borderColor: C.border, marginHorizontal: pad }]}>
        <View style={[st.sectionHead, { borderBottomColor: C.border }]}>
          <Text style={[st.sectionTitle, { color: C.gold }]}>TRADE STATES</Text>
        </View>
        <View style={st.sectionBody}>
          <StatePills C={C} />
        </View>
      </View>

      <View style={[st.section, { borderColor: C.border, marginHorizontal: pad }]}>
        <View style={[st.sectionHead, { borderBottomColor: C.border }]}>
          <Text style={[st.sectionTitle, { color: C.gold }]}>HEADER & TICKER</Text>
        </View>
        <View style={st.sectionBody}>
          <BilshenzHeader />
          <View style={{ marginTop: 8 }}>
            <GeoPoliticalTicker items={['DEV PREVIEW: MOCK API ON', 'XAUUSDT · NEW YORK SESSION', 'BSV3.2 UI SHOWCASE']} />
          </View>
        </View>
      </View>

      <View style={[st.section, { borderColor: C.border, marginHorizontal: pad }]}>
        <View style={[st.sectionHead, { borderBottomColor: C.border }]}>
          <Text style={[st.sectionTitle, { color: C.gold }]}>APP BUTTONS</Text>
        </View>
        <View style={st.sectionBody}>
          <Pressable style={[st.btn, styles.execBtn]}>
            <Text style={styles.execBtnTxt}>EXECUTE (PRIMARY)</Text>
          </Pressable>
          <Pressable style={[st.btn, { borderColor: C.border, backgroundColor: 'rgba(212,180,90,0.15)' }]}>
            <Text style={[st.btnTxt, { color: C.goldL }]}>SECONDARY GOLD</Text>
          </Pressable>
          <Pressable style={[st.btn, { borderColor: C.red, backgroundColor: C.redD }]}>
            <Text style={[st.btnTxt, { color: C.red }]}>DANGER</Text>
          </Pressable>
        </View>
      </View>

      <View style={[st.section, { borderColor: C.border, marginHorizontal: pad, backgroundColor: C.panel2 }]}>
        <View style={[st.sectionHead, { borderBottomColor: C.border }]}>
          <Text style={[st.sectionTitle, { color: C.gold }]}>BINANCE BRIDGE PANEL</Text>
        </View>
        <View style={st.sectionBody}>
          <BinanceBridgePanel />
        </View>
      </View>

      <View style={{ paddingHorizontal: pad, marginTop: 16 }}>
        <Pressable
          style={[st.btn, { borderColor: C.amber, backgroundColor: 'rgba(255,179,0,0.1)' }]}
          onPress={() => setShowFallback(true)}>
          <Text style={[st.btnTxt, { color: C.amber }]}>PREVIEW BOOT FALLBACK</Text>
        </Pressable>
      </View>
    </ScrollView>
  );
}

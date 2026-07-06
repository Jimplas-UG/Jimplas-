import React from 'react';
import { Platform, Pressable, StyleSheet, Text, View } from 'react-native';
import { useBilshenzTheme } from '../../contexts/ThemeContext';
import { radius, spacing, typography } from '../../theme/designTokens';

export function PilotCard({ children, style, onPress, accent }) {
  const { colors: C } = useBilshenzTheme();
  const body = (
    <View
      style={[
        st.card,
        {
          backgroundColor: C.panel,
          borderColor: accent ? C.accent : C.border,
          ...(accent ? { borderWidth: 1.5 } : {}),
        },
        style,
      ]}>
      {children}
    </View>
  );
  if (onPress) {
    return (
      <Pressable onPress={onPress} style={({ pressed }) => [pressed && { opacity: 0.92 }]}>
        {body}
      </Pressable>
    );
  }
  return body;
}

export function PilotSectionTitle({ title, right }) {
  const { colors: C } = useBilshenzTheme();
  return (
    <View style={st.sectionHead}>
      <Text style={[st.sectionTitle, { color: C.dim }]}>{title}</Text>
      {right}
    </View>
  );
}

export function PilotPill({ label, ok, warn, accent }) {
  const { colors: C } = useBilshenzTheme();
  const bg = accent ? C.accentDim : ok ? C.greenD : warn ? 'rgba(245,158,11,0.12)' : C.redD;
  const color = accent ? C.accentLight : ok ? C.green : warn ? C.amber : C.red;
  const border = accent ? 'rgba(124,108,240,0.35)' : ok ? 'rgba(34,197,94,0.35)' : warn ? 'rgba(245,158,11,0.35)' : 'rgba(239,68,68,0.35)';
  return (
    <View style={[st.pill, { backgroundColor: bg, borderColor: border }]}>
      <View style={[st.pillDot, { backgroundColor: color }]} />
      <Text style={[st.pillTxt, { color }]} numberOfLines={1}>
        {label}
      </Text>
    </View>
  );
}

export function PilotHeroBalance({ balance, floating, connected, onConnect }) {
  const { colors: C } = useBilshenzTheme();
  const floatVal = Number(floating ?? 0);
  const floatColor = floatVal >= 0 ? C.green : C.red;

  if (!connected) {
    return (
      <PilotCard accent onPress={onConnect} style={{ marginBottom: spacing.md }}>
        <Text style={[st.heroLbl, { color: C.accentLight }]}>Connect exchange</Text>
        <Text style={[st.heroSub, { color: C.dim }]}>
          Link Binance Futures to enable auto execution and live balance.
        </Text>
        <Text style={[st.heroCta, { color: C.accentLight }]}>Open settings →</Text>
      </PilotCard>
    );
  }

  return (
    <PilotCard style={{ marginBottom: spacing.md }}>
      <Text style={[st.heroLbl, { color: C.dim }]}>Portfolio</Text>
      <Text style={[st.heroBal, { color: C.text }]}>
        ${Math.round(balance ?? 0).toLocaleString()}
      </Text>
      <View style={st.heroRow}>
        <Text style={[st.heroSub, { color: C.dim }]}>Floating PnL</Text>
        <Text style={[st.heroFloat, { color: floatColor }]}>
          {floatVal >= 0 ? '+' : ''}${Math.round(floatVal).toLocaleString()}
        </Text>
      </View>
    </PilotCard>
  );
}

export function PilotScreenBody({ children, pad, style }) {
  return (
    <View style={[{ flex: 1, paddingHorizontal: pad }, style]}>
      {children}
    </View>
  );
}

const st = StyleSheet.create({
  card: {
    borderRadius: radius.lg,
    borderWidth: 1,
    padding: spacing.lg,
    ...Platform.select({
      ios: {
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 4 },
        shadowOpacity: 0.2,
        shadowRadius: 12,
      },
      android: { elevation: 3 },
      default: {},
    }),
  },
  sectionHead: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.sm,
    marginTop: spacing.xs,
  },
  sectionTitle: {
    ...typography.label,
    fontSize: 11,
    letterSpacing: 1.4,
  },
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 5,
    paddingHorizontal: 10,
    borderRadius: radius.pill,
    borderWidth: 1,
    gap: 6,
  },
  pillDot: { width: 6, height: 6, borderRadius: 3 },
  pillTxt: { fontSize: 10, fontWeight: '700' },
  heroLbl: { fontSize: 11, fontWeight: '600', letterSpacing: 0.3, marginBottom: 4 },
  heroBal: { fontSize: 32, fontWeight: '800', letterSpacing: -0.5 },
  heroRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginTop: 8 },
  heroSub: { fontSize: 12, lineHeight: 18 },
  heroFloat: { fontSize: 14, fontWeight: '700' },
  heroCta: { fontSize: 12, fontWeight: '700', marginTop: 10 },
});

import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useBilshenzTheme } from '../contexts/ThemeContext';
import { TRADING_PAIR_LABEL } from '../lib/tradingSymbol';

function StatusChip({ label, ok, warn, onPress }) {
  const { colors: C } = useBilshenzTheme();
  const border = ok ? 'rgba(0,230,118,0.45)' : warn ? 'rgba(255,179,0,0.45)' : 'rgba(255,61,87,0.35)';
  const bg = ok ? 'rgba(0,230,118,0.1)' : warn ? 'rgba(255,179,0,0.08)' : 'rgba(255,61,87,0.08)';
  const color = ok ? C.green : warn ? C.amber : C.red;
  const body = (
    <View style={[st.chip, { borderColor: border, backgroundColor: bg }]}>
      <View style={[st.dot, { backgroundColor: color }]} />
      <Text style={[st.chipTxt, { color }]} numberOfLines={1}>
        {label}
      </Text>
    </View>
  );
  if (onPress) {
    return (
      <Pressable onPress={onPress} style={({ pressed }) => [pressed && { opacity: 0.85 }]}>
        {body}
      </Pressable>
    );
  }
  return body;
}

/**
 * Compact Binance desk status — market feed, account, auto-exec.
 */
export default function BinanceStatusStrip({
  feedReady,
  feedError,
  connected,
  autoExecute,
  onPressConnect,
  style,
}) {
  const { colors: C } = useBilshenzTheme();
  const marketOk = !!feedReady;
  const marketWarn = !marketOk && !feedError;
  const marketLabel = marketOk ? 'Market live' : feedError ? 'Bridge offline' : 'Loading market…';
  const acctLabel = connected ? 'Account linked' : 'Tap to connect';
  const autoLabel = connected ? (autoExecute ? 'Auto-exec ON' : 'Auto-exec OFF') : 'Manual exec';

  return (
    <View style={[st.wrap, { borderColor: C.border }, style]}>
      <Text style={[st.pair, { color: C.goldL }]}>{TRADING_PAIR_LABEL} PERP</Text>
      <View style={st.row}>
        <StatusChip label={marketLabel} ok={marketOk} warn={marketWarn} />
        <StatusChip
          label={acctLabel}
          ok={connected}
          warn={!connected && marketOk}
          onPress={!connected && onPressConnect ? onPressConnect : undefined}
        />
        <StatusChip label={autoLabel} ok={connected && autoExecute} warn={connected && !autoExecute} />
      </View>
    </View>
  );
}

const st = StyleSheet.create({
  wrap: {
    borderWidth: 1,
    borderRadius: 12,
    paddingVertical: 10,
    paddingHorizontal: 12,
    backgroundColor: 'rgba(0,0,0,0.25)',
  },
  pair: { fontSize: 9, fontWeight: '800', letterSpacing: 1.2, marginBottom: 8 },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 6,
    paddingHorizontal: 8,
    borderRadius: 8,
    borderWidth: 1,
    maxWidth: '100%',
  },
  dot: { width: 6, height: 6, borderRadius: 3, marginRight: 6 },
  chipTxt: { fontSize: 10, fontWeight: '700' },
});
